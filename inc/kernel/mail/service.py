"""SMTP wrapper and durable outbox service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Protocol
from uuid import UUID

from aiosmtplib import SMTP
from pydantic import BaseModel, ValidationError

from inc.kernel.config import Settings, get_settings
from inc.kernel.db import UoWExecutor, new_uuid7
from inc.kernel.errors import COMMON_001, AppError
from inc.kernel.events import Event, EventBus, get_event_bus
from inc.kernel.logging import get_logger
from inc.kernel.security import Principal

from .errors import MAIL_001, MAIL_002
from .events import MAIL_EVENT_TYPES, MailSendFailedPayload
from .models import MailContext, MailOutbox, MailOutboxRead, MailStatus
from .registry import MailTemplate, MailTemplateRegistry, mail_template_registry
from .uow import MailUnitOfWork

logger = get_logger(__name__)


class MailTransport(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class SMTPTransport:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def send(self, message: EmailMessage) -> None:
        smtp = SMTP(
            hostname=self._settings.smtp_host,
            port=self._settings.smtp_port,
            username=self._settings.smtp_user or None,
            password=self._settings.smtp_password.get_secret_value() or None,
            start_tls=False,
        )
        await smtp.connect()
        try:
            await smtp.send_message(message)
        finally:
            await smtp.quit()


class MailService:
    MAX_ATTEMPTS = 5

    def __init__(
        self,
        executor: UoWExecutor[MailUnitOfWork],
        *,
        transport: MailTransport | None = None,
        settings: Settings | None = None,
        registry: MailTemplateRegistry | None = None,
        event_bus: EventBus | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._executor = executor
        self._settings = settings or get_settings()
        self._transport = transport or SMTPTransport(self._settings)
        self._registry = registry or mail_template_registry
        self._event_bus = event_bus or get_event_bus()
        self._clock = clock or (lambda: datetime.now(UTC))
        for event_type in MAIL_EVENT_TYPES:
            if not self._event_bus.is_registered(event_type):
                self._event_bus.register(event_type)

    async def enqueue(self, to: str, template: str, context: BaseModel) -> UUID:
        definition = self._template(template)
        try:
            normalized = definition.context_model.model_validate(context.model_dump())
        except (ValidationError, AttributeError) as exc:
            raise AppError(
                COMMON_001, detail={"template": template, "reason": "invalid context"}, cause=exc
            ) from exc

        async def operation(uow: MailUnitOfWork) -> UUID:
            row = MailOutbox(
                id=new_uuid7(),
                to_addr=to.strip(),
                template=template,
                context=MailContext.model_validate(normalized.model_dump()),
                status=MailStatus.PENDING.value,
            )
            await uow.outbox.add(row)
            return row.id

        mail_id = await self._executor.write(operation)
        await self._attempt(mail_id)
        return mail_id

    async def get(self, mail_id: UUID) -> MailOutboxRead:
        async def operation(uow: MailUnitOfWork) -> MailOutboxRead:
            row = await uow.outbox.get_or_none(mail_id)
            if row is None:
                raise AppError(MAIL_001, detail={"mail_id": str(mail_id), "reason": "not found"})
            return MailOutboxRead.model_validate(row)

        return await self._executor.read(operation)

    async def retry_failed(self, principal: Principal | None = None) -> int:
        del principal
        now = self._now()

        async def operation(uow: MailUnitOfWork) -> list[UUID]:
            rows = await uow.outbox.list_retryable(now)
            return [row.id for row in rows]

        mail_ids = await self._executor.write(operation)
        for mail_id in mail_ids:
            await self._attempt(mail_id)
        return len(mail_ids)

    async def _attempt(self, mail_id: UUID) -> None:
        now = self._now()
        lease = now + timedelta(minutes=10)

        async def claim(uow: MailUnitOfWork) -> tuple[str, str, MailContext, int] | None:
            claimed = await uow.outbox.claim_for_attempt(mail_id, now, lease)
            if claimed is None:
                return None
            row, attempt = claimed
            return row.to_addr, row.template, row.context, attempt

        snapshot = await self._executor.write(claim)
        if snapshot is None:
            return
        to_addr, template_name, context, attempt = snapshot
        try:
            definition = self._template(template_name)
            message = self._message(to_addr, definition, context)
        except Exception as exc:
            await self._mark_failed(
                mail_id, attempt, str(exc)[:1024], now, to_addr=to_addr, template=template_name
            )
            return
        try:
            await self._transport.send(message)
        except Exception as exc:
            await self._mark_failed(
                mail_id,
                attempt,
                str(exc)[:1024],
                self._now(),
                to_addr=to_addr,
                template=template_name,
            )
            return

        async def success(uow: MailUnitOfWork) -> None:
            row = await uow.outbox.get_for_update_or_none(mail_id)
            if row is None or row.status != MailStatus.SENDING.value or row.attempts != attempt:
                return
            row.status = MailStatus.SENT.value
            row.sent_at = self._now()
            row.last_error = None
            row.next_attempt_at = None

        await self._executor.write(success)

    async def _mark_failed(
        self,
        mail_id: UUID,
        attempt: int,
        error: str,
        now: datetime,
        *,
        to_addr: str,
        template: str,
    ) -> None:
        dead = attempt >= self.MAX_ATTEMPTS
        transitioned = False

        async def fail(uow: MailUnitOfWork) -> None:
            nonlocal transitioned
            row = await uow.outbox.get_for_update_or_none(mail_id)
            if row is None or row.status != MailStatus.SENDING.value or row.attempts != attempt:
                return
            transitioned = True
            row.last_error = error
            row.status = MailStatus.DEAD.value if dead else MailStatus.FAILED.value
            row.next_attempt_at = None if dead else now + timedelta(minutes=5)

        await self._executor.write(fail)
        if dead and transitioned:
            self._event_bus.publish(
                Event(
                    type="mail.send_failed",
                    payload=MailSendFailedPayload(
                        mail_id=mail_id,
                        to=to_addr,
                        template=template,
                        attempts=attempt,
                    ),
                )
            )
        logger.warning("mail_send_failed", mail_id=str(mail_id), attempts=attempt)

    def _template(self, name: str) -> MailTemplate:
        definition = self._registry.get(name)
        if definition is None:
            raise AppError(MAIL_002, detail={"template": name})
        return definition

    def _message(
        self, to_addr: str, definition: MailTemplate, context: MailContext
    ) -> EmailMessage:
        values = context.model_dump(mode="json")
        message = EmailMessage()
        message["From"] = self._settings.smtp_from
        message["To"] = to_addr
        message["Subject"] = definition.subject_template.format(**values)
        message.set_content(definition.body_template.format(**values))
        return message

    def _now(self) -> datetime:
        now = self._clock()
        return now if now.tzinfo is not None else now.replace(tzinfo=UTC)

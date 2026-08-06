"""Fire-and-forget append-only audit service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from inc.kernel.db import Page, UoWExecutor, new_uuid7
from inc.kernel.errors import COMMON_404, AppError
from inc.kernel.events import Event, EventBus, get_event_bus
from inc.kernel.security import Principal

from .events import AUDIT_EVENT_TYPES, AuditRecordPayload
from .models import AuditContext, AuditLog, AuditLogRead, AuditQuery
from .uow import AuditUnitOfWork


class AuditService:
    def __init__(
        self,
        executor: UoWExecutor[AuditUnitOfWork],
        *,
        event_bus: EventBus | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._executor = executor
        self._event_bus = event_bus or get_event_bus()
        self._clock = clock or (lambda: datetime.now(UTC))
        for event_type in AUDIT_EVENT_TYPES:
            if not self._event_bus.is_registered(event_type):
                self._event_bus.register(event_type)
        self._event_bus.subscribe("audit.recorded", self._handle_recorded)

    async def record(
        self,
        action: str,
        actor: Principal,
        *,
        target_type: str | None = None,
        target_id: UUID | None = None,
        context: AuditContext | None = None,
        ip: str | None = None,
    ) -> None:
        payload = AuditRecordPayload(
            actor_id=None if actor.is_anonymous else actor.id,
            actor_type=(
                "system_bot"
                if actor.is_system_bot
                else "anonymous"
                if actor.is_anonymous
                else "user"
            ),
            action=action,
            target_type=target_type,
            target_id=target_id,
            context=None if context is None else context.model_dump(mode="json"),
            ip=ip,
            occurred_at=self._now(),
        )
        self._event_bus.publish(Event(type="audit.recorded", payload=payload))

    async def query(self, query: AuditQuery | None = None) -> Page[AuditLogRead]:
        params = query or AuditQuery()

        async def operation(uow: AuditUnitOfWork) -> Page[AuditLogRead]:
            result = await uow.logs.list_filtered(
                action=params.action,
                actor_id=params.actor_id,
                created_from=params.created_from,
                created_to=params.created_to,
                page=params.page,
                size=params.size,
            )
            return Page(
                items=[AuditLogRead.model_validate(item) for item in result.items],
                total=result.total,
                page=result.page,
                size=result.size,
            )

        return await self._executor.read(operation)

    async def get(self, log_id: UUID) -> AuditLogRead:
        async def operation(uow: AuditUnitOfWork) -> AuditLogRead:
            item = await uow.logs.get_or_none(log_id)
            if item is None:
                raise AppError(COMMON_404)
            return AuditLogRead.model_validate(item)

        return await self._executor.read(operation)

    async def purge_old_logs(self, actor: Principal, *, retention_days: int = 180) -> int:
        cutoff = self._now() - timedelta(days=retention_days)

        async def operation(uow: AuditUnitOfWork) -> int:
            return await uow.logs.purge_before(cutoff)

        count = await self._executor.write(operation)
        await self.record("audit.purged", actor, context=AuditContext(extra={"count": str(count)}))
        return count

    async def _handle_recorded(self, event: Event) -> None:
        payload = AuditRecordPayload.model_validate(event.payload)

        async def operation(uow: AuditUnitOfWork) -> None:
            await uow.logs.add(
                AuditLog(
                    id=new_uuid7(),
                    actor_id=payload.actor_id,
                    actor_type=payload.actor_type,
                    action=payload.action,
                    target_type=payload.target_type,
                    target_id=payload.target_id,
                    context=None
                    if payload.context is None
                    else AuditContext.model_validate(payload.context),
                    ip=payload.ip,
                    created_at=payload.occurred_at,
                )
            )

        await self._executor.write(operation)

    def _now(self) -> datetime:
        now = self._clock()
        return now if now.tzinfo is not None else now.replace(tzinfo=UTC)

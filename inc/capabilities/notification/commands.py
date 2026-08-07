"""Notification commands.

Contract source: context/spec/capabilities/notification.md §5/§6.

RequestNotification is idempotent by (spec_key, idempotency_key): a repeat
returns the existing intent and never creates a second delivery. The
delivery workflow starts with the delivery id as its business key, so
duplicate requests cannot double-send.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from inc.capabilities.notification.events import NOTIFICATION_EVENT_SCHEMAS
from inc.capabilities.notification.models import (
    IntentVariables,
    NotificationDelivery,
    NotificationIntent,
    RecipientSnapshot,
)
from inc.capabilities.notification.ports import (
    NotificationProvider,
    RecipientResolver,
    RecipientTarget,
)
from inc.capabilities.notification.schemas import (
    NotificationDeliveryDTO,
    NotificationIntentDTO,
    RequestNotificationInput,
    RequestNotificationResult,
)
from inc.capabilities.notification.specs import NotificationSpec, NotificationSpecRegistry
from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock
from inc.kernel.workflow import WorkflowRunner

DELIVER_WORKFLOW_KEY = "notification.deliver.v1"

PERMISSION_REQUEST = "notification.request"
PERMISSION_CANCEL = "notification.cancel"
PERMISSION_RETRY = "notification.retry"


@dataclass(frozen=True, slots=True)
class CommandContext:
    uow_factory: UoWFactory
    clock: Clock
    outbox: OutboxWriter
    specs: NotificationSpecRegistry
    resolver: RecipientResolver
    providers: dict[str, NotificationProvider]
    runner: WorkflowRunner
    permissions: frozenset[str] = frozenset()
    actor_id: str | None = None
    trace_id: str | None = None


def _forbidden(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.FORBIDDEN, message=message)


def _conflict(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.CONFLICT, message=message)


def _not_found(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.NOT_FOUND, message=message)


def _require_permission(ctx: CommandContext, key: str) -> None:
    if key not in ctx.permissions:
        raise _forbidden("notification.forbidden", f"requires permission {key}")


def _require_spec(ctx: CommandContext, key: str) -> NotificationSpec:
    """Client-supplied spec keys are validation errors, not internal ones."""

    try:
        return ctx.specs.require(key)
    except KernelError as exc:
        if exc.code == "notification.unknown_spec":
            raise KernelError(
                code="notification.unknown_spec",
                category=ErrorCategory.VALIDATION,
                message=exc.message,
            ) from exc
        raise


def _validate_variables(spec: NotificationSpec, variables: dict[str, Any]) -> dict[str, Any]:
    return spec.variables_schema.model_validate(variables).model_dump(mode="json")


def _ensure_utc(value: Any) -> Any:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _mask_address(address: str) -> str:
    if "@" in address:
        local, _, domain = address.partition("@")
        visible = local[:2] if len(local) > 2 else local[:1]
        return f"{visible}***@{domain}"
    return address[:2] + "***"


def _to_intent_dto(row: NotificationIntent) -> NotificationIntentDTO:
    return NotificationIntentDTO(
        id=str(row.id),
        spec_key=row.spec_key,
        recipient_type=row.recipient_type,
        recipient_id=row.recipient_id,
        state=row.state,
        requested_at=_ensure_utc(row.requested_at),
        cancelled_at=_ensure_utc(row.cancelled_at) if row.cancelled_at is not None else None,
    )


def _to_delivery_dto(row: NotificationDelivery) -> NotificationDeliveryDTO:
    return NotificationDeliveryDTO(
        id=str(row.id),
        intent_id=str(row.intent_id),
        channel=row.channel,
        provider_key=row.provider_key,
        masked_address=row.recipient.masked_address,
        attempt=row.attempt,
        status=row.status,
        provider_ref=row.provider_ref,
        error_category=row.error_category,
        next_retry_at=_ensure_utc(row.next_retry_at) if row.next_retry_at is not None else None,
        delivered_at=_ensure_utc(row.delivered_at) if row.delivered_at is not None else None,
    )


async def _emit(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    key: str,
    delivery_id: str,
    intent_id: str,
    spec_key: str,
    channel: str,
    **values: Any,
) -> None:
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=key,
            occurred_at=ctx.clock.utc_now(),
            producer="notification",
            aggregate_type="notification",
            aggregate_id=delivery_id,
            trace_id=ctx.trace_id,
            payload=NOTIFICATION_EVENT_SCHEMAS[key]
            .model_validate(
                {
                    "delivery_id": delivery_id,
                    "intent_id": intent_id,
                    "spec_key": spec_key,
                    "channel": channel,
                    **values,
                }
            )
            .model_dump(mode="json"),
        ),
    )


class RequestNotification:
    """Create (or return) an intent and one pending delivery."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: RequestNotificationInput) -> RequestNotificationResult:
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_REQUEST)
        spec = _require_spec(ctx, input_.spec_key)
        if input_.recipient_type != spec.recipient_kind:
            raise KernelError(
                code="notification.recipient_kind_mismatch",
                category=ErrorCategory.VALIDATION,
                message=(
                    f"spec {spec.key} expects recipient kind {spec.recipient_kind!r}, "
                    f"got {input_.recipient_type!r}"
                ),
            )
        values = _validate_variables(spec, input_.variables)
        requested_at = input_.requested_at or ctx.clock.utc_now()

        async with ctx.uow_factory() as uow:
            existing = (
                (
                    await uow.session.execute(
                        select(NotificationIntent).where(
                            NotificationIntent.spec_key == input_.spec_key,
                            NotificationIntent.idempotency_key == input_.idempotency_key,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                delivery = (
                    (
                        await uow.session.execute(
                            select(NotificationDelivery).where(
                                NotificationDelivery.intent_id == existing.id
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if delivery is None:
                    raise _conflict(
                        "notification.intent_without_delivery",
                        "existing intent has no delivery",
                    )
                return RequestNotificationResult(
                    intent=_to_intent_dto(existing),
                    delivery=_to_delivery_dto(delivery),
                    created=False,
                )

            target = await self._resolve_target(ctx, spec, input_)
            intent = NotificationIntent(
                spec_key=input_.spec_key,
                idempotency_key=input_.idempotency_key,
                recipient_type=input_.recipient_type,
                recipient_id=input_.recipient_id,
                variables=IntentVariables(schema_version=spec.version, values=values),
                requested_at=requested_at,
                state="pending",
            )
            uow.session.add(intent)
            try:
                await uow.session.flush()  # assign id; unique violations surface here
            except IntegrityError as exc:
                raise _conflict(
                    "notification.duplicate_request",
                    "a request with this idempotency key already exists",
                ) from exc
            provider = _provider_for(ctx, spec, target.channel)
            delivery = NotificationDelivery(
                intent_id=intent.id,
                channel=target.channel,
                provider_key=provider.key,
                recipient=RecipientSnapshot(
                    channel=target.channel,
                    recipient_type=input_.recipient_type,
                    recipient_id=input_.recipient_id,
                    address_digest=_digest(target.address),
                    masked_address=target.masked_address,
                ),
                status="pending",
            )
            uow.session.add(delivery)
            await uow.session.flush()
            await _emit(
                ctx,
                uow,
                key="notification.requested.v1",
                delivery_id=str(delivery.id),
                intent_id=str(intent.id),
                spec_key=intent.spec_key,
                channel=delivery.channel,
            )
            await uow.commit()
        await ctx.runner.start(
            workflow_key=DELIVER_WORKFLOW_KEY,
            idempotency_key=f"delivery:{delivery.id}",
            input_data={"delivery_id": str(delivery.id)},
            trace_id=ctx.trace_id,
        )
        return RequestNotificationResult(
            intent=_to_intent_dto(intent),
            delivery=_to_delivery_dto(delivery),
            created=True,
        )

    async def _resolve_target(
        self, ctx: CommandContext, spec: NotificationSpec, input_: RequestNotificationInput
    ) -> RecipientTarget:
        errors: list[str] = []
        for channel in (*spec.channels, *spec.fallback_channels):
            if channel not in ctx.providers:
                continue
            target = await ctx.resolver.resolve(input_.recipient_type, input_.recipient_id, channel)
            if target is not None:
                return target
            errors.append(f"no address for {channel}")
        detail = ", ".join(errors) or "no provider bound for spec channels"
        raise KernelError(
            code="notification.unresolvable_recipient",
            category=ErrorCategory.VALIDATION,
            message=f"cannot resolve recipient {input_.recipient_type}:{input_.recipient_id}",
            details={"reason": detail},
        )


def _digest(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _provider_for(
    ctx: CommandContext, spec: NotificationSpec, channel: str
) -> NotificationProvider:
    provider = ctx.providers.get(channel)
    if provider is None:
        raise _conflict(
            "notification.channel_unbound",
            f"no provider bound for channel {channel!r} (spec {spec.key})",
        )
    return provider


class CancelPendingNotification:
    """Cancel a delivery that has not been handed to a provider."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, delivery_id: Any) -> NotificationDeliveryDTO:  # type: ignore[return]
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_CANCEL)
        async with ctx.uow_factory() as uow:
            delivery: NotificationDelivery | None = await uow.session.get(
                NotificationDelivery, delivery_id
            )
            if delivery is None:
                raise _not_found("notification.delivery_not_found", f"delivery {delivery_id}")
            if delivery.status not in ("pending", "sending"):
                raise _conflict(
                    "notification.not_cancellable",
                    f"delivery is {delivery.status}",
                )
            delivery.status = "cancelled"
            intent = await uow.session.get(NotificationIntent, delivery.intent_id)
            if intent is not None and intent.state == "pending":
                intent.state = "cancelled"
                intent.cancelled_at = ctx.clock.utc_now()
            await uow.commit()
            return _to_delivery_dto(delivery)


class RetryDelivery:
    """Explicit admin recovery: re-queue a delivery.

    Accepts terminal states (failed/dead/unknown/cancelled) plus
    ``sending``/``pending`` orphans left by a crashed run; the workflow
    restart is idempotent by ``delivery:<id>:retry:<attempt>``.
    """

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, delivery_id: Any) -> NotificationDeliveryDTO:
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_RETRY)
        async with ctx.uow_factory() as uow:
            delivery: NotificationDelivery | None = await uow.session.get(
                NotificationDelivery, delivery_id
            )
            if delivery is None:
                raise _not_found("notification.delivery_not_found", f"delivery {delivery_id}")
            if delivery.status not in (
                "failed",
                "dead",
                "unknown",
                "cancelled",
                "sending",
                "pending",
            ):
                raise _conflict(
                    "notification.not_retryable",
                    f"delivery is {delivery.status}",
                )
            delivery.status = "pending"
            delivery.next_retry_at = None
            delivery.error_category = None
            delivery.error_summary = None
            delivery.lease_owner = None
            delivery.lease_expires_at = None
            intent = await uow.session.get(NotificationIntent, delivery.intent_id)
            if intent is not None and intent.state == "cancelled":
                intent.state = "pending"
                intent.cancelled_at = None
            await uow.commit()
            delivery_id_str = str(delivery.id)
            next_attempt = delivery.attempt + 1
        await ctx.runner.start(
            workflow_key=DELIVER_WORKFLOW_KEY,
            idempotency_key=f"delivery:{delivery_id_str}:retry:{next_attempt}",
            input_data={"delivery_id": delivery_id_str},
            trace_id=ctx.trace_id,
        )
        async with ctx.uow_factory() as uow:
            refreshed: NotificationDelivery | None = await uow.session.get(
                NotificationDelivery, delivery_id
            )
        if refreshed is None:
            raise _not_found("notification.delivery_not_found", f"delivery {delivery_id}")
        return _to_delivery_dto(refreshed)

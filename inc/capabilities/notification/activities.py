"""Notification deliver activity.

Contract source: context/spec/capabilities/notification.md §5/§6.

One workflow per delivery (business key ``delivery:<id>``). The activity
renders the template, re-resolves the live address, calls the provider
with a stable idempotency key and records the outcome in the same UoW the
runner commits. Transient provider failures raise to the workflow retry
policy; the delivery state machine (attempt counting, dead marking) lives
in this activity so replayed or retried steps stay consistent.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select

from inc.capabilities.notification.commands import DELIVER_WORKFLOW_KEY
from inc.capabilities.notification.models import (
    NotificationDelivery,
    NotificationIntent,
    NotificationTemplate,
)
from inc.capabilities.notification.ports import (
    NotificationProvider,
    ProviderError,
    RecipientResolver,
)
from inc.capabilities.notification.specs import DeliveryPolicy, NotificationSpecRegistry
from inc.kernel.db import UnitOfWork
from inc.kernel.errors import ErrorCategory, KernelError, RetryCategory
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock
from inc.kernel.workflow import ActivityContext

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def render_template(subject: str, body: str, variables: dict[str, Any]) -> tuple[str, str]:
    """Simple placeholder substitution; never evaluates expressions."""

    def _sub(text: str) -> str:
        def _replace(match: re.Match[str]) -> str:
            key = match.group(1)
            value = variables.get(key)
            return str(value) if value is not None else match.group(0)

        return _PLACEHOLDER.sub(_replace, text)

    return _sub(subject), _sub(body)


class DeliverActivity:
    """One delivery attempt inside the workflow runner UoW."""

    def __init__(
        self,
        *,
        clock: Clock,
        outbox: OutboxWriter,
        specs: NotificationSpecRegistry,
        resolver: RecipientResolver,
        providers: dict[str, NotificationProvider],
    ) -> None:
        self._clock = clock
        self._outbox = outbox
        self._specs = specs
        self._resolver = resolver
        self._providers = providers

    async def __call__(
        self, uow: UnitOfWork, data: dict[str, Any], ctx: ActivityContext
    ) -> dict[str, Any]:
        workflow = data.get("workflow", {})
        delivery_id = workflow.get("delivery_id")
        if delivery_id is None:
            raise KernelError(
                code="notification.deliver_invalid_input",
                category=ErrorCategory.INTERNAL,
                message="deliver workflow input is missing delivery_id",
            )
        delivery: NotificationDelivery | None = await uow.session.get(
            NotificationDelivery, uuid.UUID(str(delivery_id))
        )
        if delivery is None or delivery.status in (
            "delivered",
            "cancelled",
            "dead",
            "failed",
        ):
            return {"skipped": True, "status": delivery.status if delivery is not None else "gone"}
        intent: NotificationIntent | None = await uow.session.get(
            NotificationIntent, delivery.intent_id
        )
        if intent is None:
            raise KernelError(
                code="notification.intent_missing",
                category=ErrorCategory.INTERNAL,
                message=f"delivery {delivery_id} has no intent",
            )
        try:
            spec = self._specs.require(intent.spec_key)
        except KernelError as exc:
            if exc.code == "notification.unknown_spec":
                await self._fail_permanently(
                    uow,
                    ctx,
                    delivery=delivery,
                    intent=intent,
                    reason="spec not registered",
                )
                return {"skipped": False, "status": "failed", "reason": "spec_missing"}
            raise

        now = self._clock.utc_now()
        delivery.status = "sending"
        delivery.attempt += 1
        delivery.lease_owner = f"workflow:{ctx.trace_id or 'runner'}"
        delivery.lease_expires_at = now

        template = await _find_template(uow, spec.template_keys[0], delivery.channel, spec.locale)
        if template is None:
            await self._fail_permanently(
                uow,
                ctx,
                delivery=delivery,
                intent=intent,
                reason="no active template",
            )
            return {"skipped": False, "status": "failed", "reason": "no_template"}

        target = await self._resolver.resolve(
            intent.recipient_type, intent.recipient_id, delivery.channel
        )
        if target is None:
            await self._fail_permanently(
                uow,
                ctx,
                delivery=delivery,
                intent=intent,
                reason="recipient unresolvable at delivery time",
            )
            return {"skipped": False, "status": "failed", "reason": "unresolvable"}

        provider = self._providers.get(delivery.channel)
        if provider is None:
            await self._fail_permanently(
                uow,
                ctx,
                delivery=delivery,
                intent=intent,
                reason=f"no provider bound for channel {delivery.channel!r}",
            )
            return {"skipped": False, "status": "failed", "reason": "channel_unbound"}
        subject, body = render_template(
            template.subject, template.body, dict(intent.variables.values)
        )
        result = await self._send(
            provider, target=target, subject=subject, body=body, delivery=delivery
        )

        delivery.lease_owner = None
        delivery.lease_expires_at = None
        if result.status == "delivered":
            delivery.status = "delivered"
            delivery.provider_ref = result.provider_ref
            delivery.delivered_at = now
            intent.state = "delivered"
            await self._emit(
                uow,
                ctx,
                delivery=delivery,
                intent=intent,
                key="notification.delivered.v1",
                provider_ref=result.provider_ref,
            )
            return {"skipped": False, "status": "delivered"}
        if result.status == "unknown":
            delivery.status = "unknown"
            delivery.provider_ref = result.provider_ref
            delivery.error_category = result.error_category or "timeout"
            delivery.error_summary = result.error_summary
            delivery.next_retry_at = None  # manual recovery only
            await self._emit(
                uow,
                ctx,
                delivery=delivery,
                intent=intent,
                key="notification.delivery_failed.v1",
                error_category=result.error_category or "timeout",
                attempt=delivery.attempt,
            )
            return {"skipped": False, "status": "unknown"}

        # failed
        category = result.error_category or RetryCategory.TRANSIENT.value
        # CANCELLED is declared a permanent category in the deliver workflow
        # retry policy; a cancelled delivery must terminate as failed, never
        # be re-sent.
        permanent = category in {
            RetryCategory.PERMANENT.value,
            RetryCategory.CANCELLED.value,
        }
        delivery.error_category = category
        delivery.error_summary = result.error_summary
        if permanent or delivery.attempt >= spec.delivery_policy.max_attempts:
            delivery.status = "dead" if not permanent else "failed"
            delivery.next_retry_at = None
            await self._emit(
                uow,
                ctx,
                delivery=delivery,
                intent=intent,
                key=(
                    "notification.delivery_dead.v1"
                    if delivery.status == "dead"
                    else "notification.delivery_failed.v1"
                ),
                error_category=category,
                attempt=delivery.attempt,
            )
            return {"skipped": False, "status": delivery.status}
        # transient: release the lease, schedule the next attempt and let
        # the workflow retry policy drive the actual retry
        delivery.status = "pending"
        delay = _retry_delay(spec.delivery_policy, delivery.attempt)
        delivery.next_retry_at = now + delay
        delivery.lease_owner = None
        delivery.lease_expires_at = None
        raise ProviderError(
            message=result.error_summary or "provider failure",
            category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
        )

    async def _fail_permanently(
        self,
        uow: UnitOfWork,
        ctx: ActivityContext,
        *,
        delivery: NotificationDelivery,
        intent: NotificationIntent,
        reason: str,
    ) -> None:
        delivery.status = "failed"
        delivery.error_category = RetryCategory.PERMANENT.value
        delivery.error_summary = reason
        delivery.lease_owner = None
        delivery.lease_expires_at = None
        delivery.next_retry_at = None
        await self._emit(
            uow,
            ctx,
            delivery=delivery,
            intent=intent,
            key="notification.delivery_failed.v1",
            error_category="permanent",
            attempt=delivery.attempt,
        )

    async def _send(
        self,
        provider: NotificationProvider,
        *,
        target: Any,
        subject: str,
        body: str,
        delivery: NotificationDelivery,
    ) -> Any:
        from inc.capabilities.notification.ports import ProviderResult

        try:
            return await provider.send(
                target=target,
                subject=subject,
                body=body,
                idempotency_key=f"{delivery.id}:{delivery.attempt}",
            )
        except ProviderError as exc:
            return ProviderResult(
                status="failed",
                error_category=exc.retry_category.value,
                error_summary=exc.message,
            )
        except Exception as exc:  # noqa: BLE001 - adapters raise raw SDK errors
            return ProviderResult(
                status="unknown",
                error_category="timeout",
                error_summary=f"provider raised {type(exc).__name__}",
            )

    async def _emit(
        self,
        uow: UnitOfWork,
        ctx: ActivityContext,
        *,
        delivery: NotificationDelivery,
        intent: NotificationIntent,
        key: str,
        **values: Any,
    ) -> None:
        from inc.capabilities.notification.events import NOTIFICATION_EVENT_SCHEMAS

        await self._outbox.append(
            uow,
            EventEnvelope(
                event_id=uuid.uuid7(),
                event_key=key,
                occurred_at=self._clock.utc_now(),
                producer="notification",
                aggregate_type="notification",
                aggregate_id=str(delivery.id),
                trace_id=ctx.trace_id,
                payload=NOTIFICATION_EVENT_SCHEMAS[key]
                .model_validate(
                    {
                        "delivery_id": str(delivery.id),
                        "intent_id": str(intent.id),
                        "spec_key": intent.spec_key,
                        "channel": delivery.channel,
                        **values,
                    }
                )
                .model_dump(mode="json"),
            ),
        )


async def _find_template(
    uow: UnitOfWork, template_key: str, channel: str, locale: str
) -> NotificationTemplate | None:
    for candidate_locale in (locale, "en"):
        row: NotificationTemplate | None = (
            (
                await uow.session.execute(
                    select(NotificationTemplate).where(
                        NotificationTemplate.template_key == template_key,
                        NotificationTemplate.channel == channel,
                        NotificationTemplate.locale == candidate_locale,
                        NotificationTemplate.status == "active",
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is not None:
            return row
    return None


def _retry_delay(policy: DeliveryPolicy, attempt: int) -> Any:
    from datetime import timedelta

    delay = min(policy.base_delay_seconds * (2 ** max(0, attempt - 1)), policy.max_delay_seconds)
    return timedelta(seconds=delay)


def build_deliver_workflow_spec(
    *, activity: DeliverActivity, policy: DeliveryPolicy | None = None
) -> Any:
    from inc.kernel.workflow import ActivitySpec, RetryPolicy, WorkflowSpec

    policy = policy or DeliveryPolicy()
    return WorkflowSpec(
        key=DELIVER_WORKFLOW_KEY,
        version="1",
        activities=(
            ActivitySpec(
                key="notification.deliver.step.v1",
                timeout_seconds=60.0,
                retry=RetryPolicy(
                    max_attempts=policy.max_attempts,
                    base_delay_seconds=policy.base_delay_seconds,
                    max_delay_seconds=policy.max_delay_seconds,
                    permanent_categories=frozenset(
                        {RetryCategory.PERMANENT, RetryCategory.CANCELLED}
                    ),
                ),
                handler=activity,
            ),
        ),
    )

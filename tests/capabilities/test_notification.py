"""Notification capability tests.

Contract source: context/spec/capabilities/notification.md §8.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from inc.capabilities.notification.activities import DeliverActivity, build_deliver_workflow_spec
from inc.capabilities.notification.commands import (
    CancelPendingNotification,
    CommandContext,
    RequestNotification,
    RetryDelivery,
    UpdateNotificationTemplate,
)
from inc.capabilities.notification.diagnostics import NotificationDiagnostics
from inc.capabilities.notification.events import NOTIFICATION_EVENT_SCHEMAS
from inc.capabilities.notification.models import (
    IntentVariables,
    NotificationDelivery,
    NotificationDeliveryAttempt,
    NotificationIntent,
    RecipientSnapshot,
)
from inc.capabilities.notification.ports import (
    ProviderError,
    ProviderResult,
    RecipientTarget,
)
from inc.capabilities.notification.retention import cleanup_notifications_in_uow
from inc.capabilities.notification.schemas import (
    RequestNotificationInput,
    UpdateNotificationTemplateInput,
)
from inc.capabilities.notification.specs import (
    DeliveryPolicy,
    NotificationSpec,
    NotificationSpecRegistry,
)
from inc.kernel.db import UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import EventSchemaRegistry, OutboxWriter
from inc.kernel.workflow import WorkflowRegistry, WorkflowRunner

NOTIFY_KEY = "moderation.submitted.v1"


class NotifyVariables(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_title: str
    content_id: str


def make_spec(*, max_attempts: int = 3) -> NotificationSpec:
    return NotificationSpec(
        key=NOTIFY_KEY,
        version="1",
        channels=("email",),
        template_keys=("moderation_submitted",),
        variables_schema=NotifyVariables,
        recipient_kind="identity",
        sensitivity="normal",
        locale="en",
        delivery_policy=DeliveryPolicy(
            max_attempts=max_attempts, base_delay_seconds=1.0, max_delay_seconds=10.0
        ),
    )


class FakeResolver:
    def __init__(self, *, address: str = "admin@example.com") -> None:
        self._address = address
        self.resolved: list[tuple[str, str]] = []

    async def resolve(
        self, recipient_type: str, recipient_id: str, channel: str
    ) -> RecipientTarget | None:
        if recipient_type != "identity":
            return None
        self.resolved.append((recipient_type, recipient_id))
        return RecipientTarget(
            channel=channel, address=self._address, masked_address="ad***@example.com"
        )


@dataclass
class FakeProvider:
    key: str = "email"
    results: list[ProviderResult] = field(default_factory=list)
    sends: list[dict[str, Any]] = field(default_factory=list)
    raise_error: ProviderError | None = None
    fail_once: bool = False

    async def check_availability(self) -> tuple[bool, str | None]:
        return True, None

    async def send(
        self, *, target: RecipientTarget, subject: str, body: str, idempotency_key: str
    ) -> ProviderResult:
        self.sends.append(
            {
                "address": target.address,
                "subject": subject,
                "body": body,
                "idempotency_key": idempotency_key,
            }
        )
        if self.raise_error is not None:
            error = self.raise_error
            self.raise_error = None
            raise error
        if self.fail_once:
            self.fail_once = False
            return ProviderResult(status="failed", error_category="transient", error_summary="nope")
        result = self.results.pop(0) if self.results else ProviderResult(status="delivered")
        return result


@pytest.fixture
def specs() -> NotificationSpecRegistry:
    registry = NotificationSpecRegistry(allowed_triggers=frozenset({NOTIFY_KEY}))
    registry.register(make_spec())
    return registry


@pytest.fixture
def schema_registry() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    for key, schema in NOTIFICATION_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    from inc.capabilities.audit.schemas import AUDIT_EVENT_KEY, AuditEntryRecorded

    registry.register(AUDIT_EVENT_KEY, AuditEntryRecorded)
    return registry


@pytest.fixture
def ctx(
    uow_factory: UoWFactory,
    clock: Any,
    specs: NotificationSpecRegistry,
    schema_registry: EventSchemaRegistry,
    seeded_template: None,
) -> CommandContext:
    workflow_registry = WorkflowRegistry()
    runner = WorkflowRunner(uow_factory=uow_factory, registry=workflow_registry, clock=clock)
    provider = FakeProvider(key="email.primary")
    providers = {"email": (provider,)}
    activity = DeliverActivity(
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        specs=specs,
        resolver=FakeResolver(),
        providers=providers,
    )
    workflow_registry.register(
        build_deliver_workflow_spec(
            activity=activity, policy=DeliveryPolicy(base_delay_seconds=0.1, max_attempts=3)
        )
    )
    return CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        specs=specs,
        resolver=FakeResolver(),
        providers=providers,
        runner=runner,
        permissions=frozenset(
            {
                "notification.request",
                "notification.cancel",
                "notification.retry",
                "notification.templates.manage",
            }
        ),
        actor_id="moderator",
        trace_id="trace-1",
    )


@pytest.fixture
async def seeded_template(uow_factory: UoWFactory) -> None:
    from inc.capabilities.notification.models import NotificationTemplate

    async with uow_factory() as uow:
        uow.session.add(
            NotificationTemplate(
                trigger_name=NOTIFY_KEY,
                template_key="moderation_submitted",
                version="1",
                channel="email",
                locale="en",
                subject="New submission: {content_title}",
                body="Review {content_title} ({content_id})",
                variables_schema_version="1",
            )
        )
        await uow.commit()


def request_input(**overrides: Any) -> RequestNotificationInput:
    base = {
        "trigger_name": NOTIFY_KEY,
        "recipient_type": "identity",
        "recipient_id": "user-1",
        "variables": {"content_title": "Hello", "content_id": "content-1"},
        "idempotency_key": "idem-1",
    }
    base.update(overrides)
    return RequestNotificationInput(**base)


async def _run_due(ctx: CommandContext) -> None:
    await ctx.runner.run_due()


async def _delivery_count(uow_factory: UoWFactory) -> int:
    async with uow_factory() as uow:
        return (await uow.session.execute(select(func.count(NotificationDelivery.id)))).scalar_one()


# --- spec registry --------------------------------------------------------


def test_spec_registry_rejects_duplicates_and_bad_declarations() -> None:
    registry = NotificationSpecRegistry(allowed_triggers=frozenset({NOTIFY_KEY}))
    registry.register(make_spec())
    with pytest.raises(KernelError) as excinfo:
        registry.register(make_spec())
    assert excinfo.value.code == "notification.duplicate_spec"
    with pytest.raises(ValueError, match="unknown channels"):
        NotificationSpec(
            key="bad.spec.v1",
            version="1",
            channels=("fax",),
            template_keys=("t",),
            variables_schema=NotifyVariables,
        )
    with pytest.raises(ValueError, match="Pydantic variables schema"):
        NotificationSpec(
            key="bad.spec.v1",
            version="1",
            channels=("email",),
            template_keys=("t",),
            variables_schema=dict,  # type: ignore[arg-type]
        )


# --- request --------------------------------------------------------------


async def test_request_is_idempotent_by_business_key(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    first = await RequestNotification(ctx)(request_input())
    assert first.created is True
    second = await RequestNotification(ctx)(request_input())
    assert second.created is False
    assert second.intent.id == first.intent.id
    assert second.delivery.id == first.delivery.id
    assert await _delivery_count(uow_factory) == 1


async def test_request_validates_variables_and_spec(
    ctx: CommandContext,
) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        await RequestNotification(ctx)(request_input(variables={"bogus": 1}))
    with pytest.raises(KernelError) as excinfo:
        await RequestNotification(ctx)(request_input(trigger_name="ghost"))
    assert excinfo.value.code == "notification.unknown_trigger"
    assert excinfo.value.category.value == "validation"
    with pytest.raises(KernelError) as excinfo:
        await RequestNotification(ctx)(request_input(recipient_type="page"))
    assert excinfo.value.code == "notification.recipient_kind_mismatch"
    with pytest.raises(ValidationError):
        await RequestNotification(ctx)(request_input(idempotency_key=""))


async def test_request_requires_permission(
    uow_factory: UoWFactory,
    clock: Any,
    specs: NotificationSpecRegistry,
    schema_registry: EventSchemaRegistry,
) -> None:
    from inc.kernel.workflow import WorkflowRegistry, WorkflowRunner

    runner = WorkflowRunner(uow_factory=uow_factory, registry=WorkflowRegistry(), clock=clock)
    restricted = CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        specs=specs,
        resolver=FakeResolver(),
        providers={"email": (FakeProvider(),)},
        runner=runner,
        permissions=frozenset(),
    )
    with pytest.raises(KernelError) as excinfo:
        await RequestNotification(restricted)(request_input())
    assert excinfo.value.code == "notification.forbidden"


async def test_template_update_requires_exact_registered_trigger_variables(
    ctx: CommandContext,
) -> None:
    updated = await UpdateNotificationTemplate(ctx)(
        trigger_name=NOTIFY_KEY,
        locale="en",
        input_=UpdateNotificationTemplateInput(
            subject="New submission: {content_title}",
            body="Review {content_title} ({content_id})",
        ),
    )
    assert updated.trigger_name == NOTIFY_KEY
    with pytest.raises(KernelError) as missing:
        await UpdateNotificationTemplate(ctx)(
            trigger_name=NOTIFY_KEY,
            locale="en",
            input_=UpdateNotificationTemplateInput(
                subject="New submission: {content_title}", body="Review {content_title}"
            ),
        )
    assert missing.value.code == "notification.template_variables_invalid"
    with pytest.raises(KernelError) as unknown:
        await UpdateNotificationTemplate(ctx)(
            trigger_name="unknown.trigger",
            locale="en",
            input_=UpdateNotificationTemplateInput(
                subject="New submission: {content_title}",
                body="Review {content_title} ({content_id})",
            ),
        )
    assert unknown.value.code == "notification.unknown_trigger"


# --- delivery -------------------------------------------------------------


async def test_deliver_flow_with_template_rendering(
    ctx: CommandContext, uow_factory: UoWFactory, clock: Any
) -> None:
    result = await RequestNotification(ctx)(request_input())
    await _run_due(ctx)

    async with uow_factory() as uow:
        delivery = await uow.session.get(NotificationDelivery, uuid.UUID(result.delivery.id))
        intent = await uow.session.get(NotificationIntent, uuid.UUID(result.intent.id))
    assert delivery is not None and delivery.status == "delivered"
    assert delivery.delivered_at is not None
    assert intent is not None and intent.state == "delivered"

    provider = ctx.providers["email"][0]
    assert len(provider.sends) == 1
    sent = provider.sends[0]
    assert sent["subject"] == "New submission: Hello"
    assert sent["body"] == "Review Hello (content-1)"
    assert sent["idempotency_key"] == f"{result.delivery.id}:email.primary"
    assert sent["address"] == "admin@example.com"

    # replay of the executed step must not re-send
    await _run_due(ctx)
    assert len(provider.sends) == 1


async def test_transient_failure_retries_then_dead(
    ctx: CommandContext, uow_factory: UoWFactory, clock: Any
) -> None:
    provider = ctx.providers["email"][0]
    provider.results = [
        ProviderResult(status="failed", error_category="transient", error_summary="busy"),
        ProviderResult(status="failed", error_category="transient", error_summary="busy"),
        ProviderResult(status="failed", error_category="transient", error_summary="busy"),
    ]
    result = await RequestNotification(ctx)(request_input())
    for _ in range(6):
        clock.advance(timedelta(seconds=30))
        await _run_due(ctx)
    async with uow_factory() as uow:
        delivery = await uow.session.get(NotificationDelivery, uuid.UUID(result.delivery.id))
    assert delivery is not None
    assert delivery.status == "dead"
    assert delivery.attempt == 3
    assert len(provider.sends) == 3


async def test_permanent_failure_marks_failed_without_retry(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    provider = ctx.providers["email"][0]
    provider.results = [
        ProviderResult(status="failed", error_category="permanent", error_summary="bad address")
    ]
    result = await RequestNotification(ctx)(request_input())
    await _run_due(ctx)
    async with uow_factory() as uow:
        delivery = await uow.session.get(NotificationDelivery, uuid.UUID(result.delivery.id))
    assert delivery is not None and delivery.status == "failed"
    assert delivery.error_category == "permanent"
    assert len(provider.sends) == 1


async def test_provider_timeout_marks_unknown_no_automatic_retry(
    ctx: CommandContext, uow_factory: UoWFactory, clock: Any
) -> None:
    provider = ctx.providers["email"][0]
    provider.results = [
        ProviderResult(status="unknown", error_category="timeout", error_summary="lost"),
    ]
    result = await RequestNotification(ctx)(request_input())
    await _run_due(ctx)
    clock.advance(timedelta(minutes=10))
    await _run_due(ctx)
    async with uow_factory() as uow:
        delivery = await uow.session.get(NotificationDelivery, uuid.UUID(result.delivery.id))
    assert delivery is not None and delivery.status == "unknown"
    assert delivery.attempt == 1
    assert len(provider.sends) == 1  # never auto re-sent


async def test_provider_chain_skips_unavailable_and_records_each_provider(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    primary = FakeProvider(
        key="email.smtp",
        results=[
            ProviderResult(
                status="unavailable",
                error_category="disabled",
                error_summary="SMTP disabled",
            )
        ],
    )
    secondary = FakeProvider(
        key="email.smtp2go",
        results=[ProviderResult(status="delivered", provider_ref="smtp2go-1")],
    )
    ctx.providers["email"] = (primary, secondary)

    result = await RequestNotification(ctx)(request_input())
    await _run_due(ctx)

    async with uow_factory() as uow:
        delivery = await uow.session.get(NotificationDelivery, uuid.UUID(result.delivery.id))
        attempts = list(
            (
                await uow.session.execute(
                    select(NotificationDeliveryAttempt)
                    .where(NotificationDeliveryAttempt.delivery_id == uuid.UUID(result.delivery.id))
                    .order_by(NotificationDeliveryAttempt.provider_sequence)
                )
            )
            .scalars()
            .all()
        )
    assert delivery is not None and delivery.status == "delivered"
    assert delivery.provider_key == "email.smtp2go"
    assert delivery.provider_ref == "smtp2go-1"
    assert [attempt.status for attempt in attempts] == ["unavailable", "delivered"]
    assert [attempt.provider_key for attempt in attempts] == ["email.smtp", "email.smtp2go"]
    assert len(primary.sends) == 1 and len(secondary.sends) == 1


async def test_provider_chain_falls_back_only_when_adapter_confirms_not_accepted(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    primary = FakeProvider(
        key="email.smtp",
        results=[
            ProviderResult(
                status="failed",
                error_category="rate_limited",
                error_summary="rate limited",
                fallback_allowed=True,
            )
        ],
    )
    secondary = FakeProvider(key="email.smtp2go")
    ctx.providers["email"] = (primary, secondary)

    result = await RequestNotification(ctx)(request_input())
    await _run_due(ctx)

    async with uow_factory() as uow:
        delivery = await uow.session.get(NotificationDelivery, uuid.UUID(result.delivery.id))
    assert delivery is not None and delivery.status == "delivered"
    assert delivery.provider_key == "email.smtp2go"
    assert len(secondary.sends) == 1


async def test_provider_chain_stops_on_unknown_outcome(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    primary = FakeProvider(
        key="email.smtp",
        results=[ProviderResult(status="unknown", error_category="timeout")],
    )
    secondary = FakeProvider(key="email.smtp2go")
    ctx.providers["email"] = (primary, secondary)

    result = await RequestNotification(ctx)(request_input())
    await _run_due(ctx)

    async with uow_factory() as uow:
        delivery = await uow.session.get(NotificationDelivery, uuid.UUID(result.delivery.id))
    assert delivery is not None and delivery.status == "unknown"
    assert delivery.provider_key == "email.smtp"
    assert secondary.sends == []


async def test_provider_chain_all_unavailable_fails_without_workflow_retry(
    ctx: CommandContext, uow_factory: UoWFactory, clock: Any
) -> None:
    providers = (
        FakeProvider(key="email.smtp", results=[ProviderResult(status="unavailable")]),
        FakeProvider(key="email.smtp2go", results=[ProviderResult(status="unavailable")]),
    )
    ctx.providers["email"] = providers

    result = await RequestNotification(ctx)(request_input())
    await _run_due(ctx)
    clock.advance(timedelta(minutes=30))
    await _run_due(ctx)

    async with uow_factory() as uow:
        delivery = await uow.session.get(NotificationDelivery, uuid.UUID(result.delivery.id))
    assert delivery is not None and delivery.status == "failed"
    assert delivery.error_category == "permanent"
    assert delivery.error_summary == "notification.no_available_provider"
    assert [len(provider.sends) for provider in providers] == [1, 1]


async def test_provider_exception_retries_then_delivers(
    ctx: CommandContext, uow_factory: UoWFactory, clock: Any
) -> None:
    provider = ctx.providers["email"][0]
    provider.raise_error = ProviderError(
        message="smtp down", category=ErrorCategory.DEPENDENCY_UNAVAILABLE
    )
    result = await RequestNotification(ctx)(request_input())
    await _run_due(ctx)
    async with uow_factory() as uow:
        delivery = await uow.session.get(NotificationDelivery, uuid.UUID(result.delivery.id))
    assert delivery is not None and delivery.status == "pending"
    assert delivery.attempt == 1
    assert delivery.next_retry_at is not None
    assert delivery.lease_expires_at is None
    clock.advance(timedelta(seconds=30))
    await _run_due(ctx)  # retry path
    async with uow_factory() as uow:
        delivery = await uow.session.get(NotificationDelivery, uuid.UUID(result.delivery.id))
    assert delivery is not None and delivery.status == "delivered"
    assert delivery.attempt == 2
    assert len(provider.sends) == 2


async def test_retry_delivery_requeues_unknown(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    provider = ctx.providers["email"][0]
    provider.results = [ProviderResult(status="unknown", error_category="timeout")]
    result = await RequestNotification(ctx)(request_input())
    await _run_due(ctx)

    provider.results = [ProviderResult(status="delivered")]
    await RetryDelivery(ctx)(uuid.UUID(result.delivery.id))
    await _run_due(ctx)
    async with uow_factory() as uow:
        delivery = await uow.session.get(NotificationDelivery, uuid.UUID(result.delivery.id))
    assert delivery is not None and delivery.status == "delivered"
    assert delivery.attempt == 2
    assert len(provider.sends) == 2


async def test_cancel_pending_only_before_provider(
    ctx: CommandContext, uow_factory: UoWFactory, clock: Any
) -> None:
    result = await RequestNotification(ctx)(request_input())
    # do not run the workflow: delivery stays pending
    cancelled = await CancelPendingNotification(ctx)(uuid.UUID(result.delivery.id))
    assert cancelled.status == "cancelled"
    with pytest.raises(KernelError) as excinfo:
        await CancelPendingNotification(ctx)(uuid.UUID(result.delivery.id))
    assert excinfo.value.code == "notification.not_cancellable"


async def test_diagnostics_report_only(
    ctx: CommandContext, uow_factory: UoWFactory, clock: Any
) -> None:
    diagnostics = NotificationDiagnostics(uow_factory=uow_factory, specs=ctx.specs, clock=clock)
    results = await diagnostics.run()
    codes = {r.code: r.status.value for r in results}
    assert codes["notification.pending_old"] == "ok"
    assert codes["notification.expired_lease"] == "ok"
    assert codes["notification.unknown_dead_backlog"] == "ok"
    assert codes["notification.spec_drift"] == "ok"
    assert codes["notification.template_seed"] == "ok"

    async with uow_factory() as uow:
        from inc.capabilities.notification.models import NotificationTemplate

        template = (
            (
                await uow.session.execute(
                    select(NotificationTemplate).where(
                        NotificationTemplate.template_key == "moderation_submitted"
                    )
                )
            )
            .scalars()
            .one()
        )
        template.status = "archived"
        await uow.commit()
    results = await diagnostics.run()
    codes = {r.code: r.status.value for r in results}
    assert codes["notification.template_seed"] == "degraded"

    result = await RequestNotification(ctx)(request_input())
    async with uow_factory() as uow:
        delivery = await uow.session.get(NotificationDelivery, uuid.UUID(result.delivery.id))
        assert delivery is not None
        delivery.status = "unknown"
        await uow.commit()
    results = await diagnostics.run()
    codes = {r.code: r.status.value for r in results}
    assert codes["notification.unknown_dead_backlog"] == "degraded"


async def test_retention_deletes_only_terminal_notification_history(
    uow_factory: UoWFactory, clock: Any
) -> None:
    old = clock.utc_now() - timedelta(days=31)
    recent = clock.utc_now() - timedelta(days=1)
    old_terminal_intent = NotificationIntent(
        id=uuid.uuid4(),
        spec_key=NOTIFY_KEY,
        idempotency_key="retention-old-terminal",
        recipient_type="identity",
        recipient_id="user-old",
        variables=IntentVariables(schema_version="1", values={}),
        requested_at=old,
        created_at=old,
        updated_at=old,
    )
    old_pending_intent = NotificationIntent(
        id=uuid.uuid4(),
        spec_key=NOTIFY_KEY,
        idempotency_key="retention-old-pending",
        recipient_type="identity",
        recipient_id="user-pending",
        variables=IntentVariables(schema_version="1", values={}),
        requested_at=old,
        created_at=old,
        updated_at=old,
    )
    recent_intent = NotificationIntent(
        id=uuid.uuid4(),
        spec_key=NOTIFY_KEY,
        idempotency_key="retention-recent",
        recipient_type="identity",
        recipient_id="user-recent",
        variables=IntentVariables(schema_version="1", values={}),
        requested_at=recent,
        created_at=recent,
        updated_at=recent,
    )
    recipient = RecipientSnapshot(
        channel="email",
        recipient_type="identity",
        recipient_id="user-old",
        address_digest="digest",
        masked_address="u***@example.com",
    )
    old_delivery = NotificationDelivery(
        id=uuid.uuid4(),
        intent_id=old_terminal_intent.id,
        channel="email",
        provider_key="email.primary",
        recipient=recipient,
        status="delivered",
        created_at=old,
        updated_at=old,
    )
    old_attempt = NotificationDeliveryAttempt(
        id=uuid.uuid4(),
        delivery_id=old_delivery.id,
        delivery_attempt=1,
        provider_sequence=1,
        provider_key="email.primary",
        status="delivered",
        started_at=old,
        finished_at=old,
        created_at=old,
        updated_at=old,
    )
    pending_delivery = NotificationDelivery(
        id=uuid.uuid4(),
        intent_id=old_pending_intent.id,
        channel="email",
        provider_key="email.primary",
        recipient=recipient,
        status="pending",
        created_at=old,
        updated_at=old,
    )
    recent_delivery = NotificationDelivery(
        id=uuid.uuid4(),
        intent_id=recent_intent.id,
        channel="email",
        provider_key="email.primary",
        recipient=recipient,
        status="delivered",
        created_at=recent,
        updated_at=recent,
    )
    async with uow_factory() as uow:
        uow.session.add_all(
            [
                old_terminal_intent,
                old_pending_intent,
                recent_intent,
                old_delivery,
                old_attempt,
                pending_delivery,
                recent_delivery,
            ]
        )
        await uow.session.flush()
        counts = await cleanup_notifications_in_uow(uow, clock.utc_now() - timedelta(days=30))
        await uow.commit()

    assert counts == {
        "notification_attempts_deleted": 1,
        "notification_deliveries_deleted": 1,
        "notification_intents_deleted": 1,
    }
    async with uow_factory() as uow:
        assert await uow.session.get(NotificationDelivery, old_delivery.id) is None
        assert await uow.session.get(NotificationDeliveryAttempt, old_attempt.id) is None
        assert await uow.session.get(NotificationIntent, old_terminal_intent.id) is None
        assert await uow.session.get(NotificationDelivery, pending_delivery.id) is not None
        assert await uow.session.get(NotificationDelivery, recent_delivery.id) is not None

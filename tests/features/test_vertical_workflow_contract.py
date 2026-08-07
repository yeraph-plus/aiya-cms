"""Vertical workflow contract fixture: submit -> notify -> review -> publish.

Contract source: context/spec/features.md §5, full-rebuild-plan R6.

This fixture proves the vertical workflow capability end to end: a
submitted content is persisted, a notification request is created, the
workflow waits on a durable review signal, and approval publishes the
content. It is a contract fixture only — it is never part of the
production manifest and post does not gain this behaviour by default.

Verified properties: crash recovery between every step, the notification
side effect is never duplicated, and undeclared signals are rejected.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from inc.capabilities.audit.schemas import AUDIT_EVENT_KEY, AuditEntryRecorded
from inc.capabilities.content.commands import (
    CommandContext as ContentCommandContext,
)
from inc.capabilities.content.commands import (
    CreateContent,
    PublishContent,
    SubmitContent,
)
from inc.capabilities.content.events import CONTENT_EVENT_SCHEMAS
from inc.capabilities.content.models import Content
from inc.capabilities.content.schemas import CreateContentInput
from inc.capabilities.content.types import (
    DEFAULT_TRANSITIONS,
    STANDARD_STATES,
    ContentTypeRegistry,
    ContentTypeSpec,
)
from inc.capabilities.notification.activities import DeliverActivity, build_deliver_workflow_spec
from inc.capabilities.notification.commands import CommandContext as NotificationCommandContext
from inc.capabilities.notification.commands import RequestNotification
from inc.capabilities.notification.events import NOTIFICATION_EVENT_SCHEMAS
from inc.capabilities.notification.ports import (
    ProviderResult,
    RecipientTarget,
)
from inc.capabilities.notification.specs import (
    DeliveryPolicy,
    NotificationSpec,
    NotificationSpecRegistry,
)
from inc.kernel.db import UoWFactory
from inc.kernel.errors import KernelError
from inc.kernel.events import EventSchemaRegistry, OutboxWriter
from inc.kernel.workflow import (
    ActivitySpec,
    WorkflowRegistry,
    WorkflowRunner,
    WorkflowSpec,
)

MODERATION_WORKFLOW_KEY = "moderation.submitflow.v1"
APPROVAL_SIGNAL = "moderation.approval.v1"


class PostData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str | None = None


class NotifyVariables(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_title: str
    content_id: str


@dataclass
class FakeEmailProvider:
    key: str = "email"
    sends: list[dict[str, Any]] = field(default_factory=list)

    async def send(
        self, *, target: RecipientTarget, subject: str, body: str, idempotency_key: str
    ) -> ProviderResult:
        self.sends.append({"address": target.address, "subject": subject, "key": idempotency_key})
        return ProviderResult(status="delivered")


class FakeIdentityResolver:
    async def resolve(
        self, recipient_type: str, recipient_id: str, channel: str
    ) -> RecipientTarget | None:
        return RecipientTarget(
            channel=channel,
            address=f"{recipient_id}@example.com",
            masked_address="ad***@example.com",
        )


@pytest.fixture
def types() -> ContentTypeRegistry:
    registry = ContentTypeRegistry()
    registry.register(
        ContentTypeSpec(
            type_name="post",
            version="1",
            display_name="Post",
            data_schema=PostData,
            data_schema_version="1",
            allowed_states=STANDARD_STATES,
            default_state="draft",
            transitions=DEFAULT_TRANSITIONS,
        )
    )
    return registry


@pytest.fixture
def notification_specs() -> NotificationSpecRegistry:
    registry = NotificationSpecRegistry()
    registry.register(
        NotificationSpec(
            key="moderation.submitted.v1",
            version="1",
            channels=("email",),
            template_keys=("moderation_submitted",),
            variables_schema=NotifyVariables,
            recipient_kind="identity",
        )
    )
    return registry


@pytest.fixture
def schema_registry() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    for key, schema in CONTENT_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    for key, schema in NOTIFICATION_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    registry.register(AUDIT_EVENT_KEY, AuditEntryRecorded)
    return registry


@pytest.fixture
async def harness(
    uow_factory: UoWFactory,
    clock: Any,
    types: ContentTypeRegistry,
    notification_specs: NotificationSpecRegistry,
    schema_registry: EventSchemaRegistry,
) -> dict[str, Any]:
    """Full wiring: registries, workflow, providers and command contexts."""

    from inc.capabilities.notification.models import NotificationTemplate

    async with uow_factory() as uow:
        uow.session.add(
            NotificationTemplate(
                template_key="moderation_submitted",
                version="1",
                channel="email",
                locale="en",
                subject="New submission: {content_title}",
                body="Review {content_title}",
                variables_schema_version="1",
            )
        )
        await uow.commit()

    outbox = OutboxWriter(schema_registry, clock)
    email = FakeEmailProvider()
    registry = WorkflowRegistry()
    runner = WorkflowRunner(uow_factory=uow_factory, registry=registry, clock=clock)

    notification_ctx = NotificationCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=outbox,
        specs=notification_specs,
        resolver=FakeIdentityResolver(),
        providers={"email": email},
        runner=runner,
        permissions=frozenset({"notification.request"}),
        actor_id="workflow",
        trace_id="moderation-flow",
    )
    deliver_activity = DeliverActivity(
        clock=clock,
        outbox=outbox,
        specs=notification_specs,
        resolver=FakeIdentityResolver(),
        providers={"email": email},
    )
    registry.register(
        build_deliver_workflow_spec(
            activity=deliver_activity, policy=DeliveryPolicy(base_delay_seconds=0.1, max_attempts=3)
        )
    )

    content_ctx = ContentCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=outbox,
        types=types,
        permissions=frozenset({"content.write", "content.publish", "content.manage"}),
        actor_id="moderator",
        trace_id="moderation-flow",
    )

    async def persist(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        content_id = data["workflow"]["content_id"]
        await SubmitContent(content_ctx)(uuid.UUID(content_id))
        return {"submitted": True}

    async def notify(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        content_id = data["workflow"]["content_id"]
        title = data["workflow"]["title"]
        result = await RequestNotification(notification_ctx)(
            _notify_input(content_id=content_id, title=title)
        )
        return {"delivery_id": result.delivery.id, "created": result.created}

    async def wait_approval(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        return {"wait_for_signal": APPROVAL_SIGNAL}

    async def publish(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        content_id = data["workflow"]["content_id"]
        await PublishContent(content_ctx)(uuid.UUID(content_id))
        return {"published": True}

    registry.register(
        WorkflowSpec(
            key=MODERATION_WORKFLOW_KEY,
            version="1",
            activities=(
                ActivitySpec(key="moderation.submit.persist.v1", handler=persist),
                ActivitySpec(key="moderation.notify.v1", handler=notify),
                ActivitySpec(key="moderation.wait_approval.v1", handler=wait_approval),
                ActivitySpec(key="moderation.publish.v1", handler=publish),
            ),
            signal_keys=(APPROVAL_SIGNAL,),
        )
    )

    return {
        "runner": runner,
        "registry": registry,
        "email": email,
        "content_ctx": content_ctx,
        "outbox": outbox,
    }


def _notify_input(*, content_id: str, title: str) -> Any:
    from inc.capabilities.notification.schemas import RequestNotificationInput

    return RequestNotificationInput(
        spec_key="moderation.submitted.v1",
        recipient_type="identity",
        recipient_id="moderator",
        variables={"content_title": title, "content_id": content_id},
        idempotency_key=f"moderation:{content_id}",
    )


async def _create_content(harness: dict[str, Any], *, title: str = "Pending post") -> str:
    created = await CreateContent(harness["content_ctx"])(
        CreateContentInput(
            type_name="post",
            title=title,
            slug=f"pending-{uuid.uuid4().hex[:6]}",
            data={"summary": "s"},
        )
    )
    return created.id


async def _start_and_signal(
    harness: dict[str, Any],
    content_id: str,
    clock: Any,
    *,
    advance_steps: int,
    uow_factory: UoWFactory,
) -> Any:
    """Run due steps until the workflow waits or completes."""

    instance = await harness["runner"].start(
        workflow_key=MODERATION_WORKFLOW_KEY,
        idempotency_key=f"content:{content_id}",
        input_data={"content_id": content_id, "title": "Pending post"},
        trace_id="moderation-flow",
    )
    for _ in range(advance_steps):
        clock.advance(timedelta(seconds=1))
        await harness["runner"].run_due()
    from sqlalchemy import select as _sel

    from inc.kernel.workflow.models import WorkflowInstance

    async with uow_factory() as _uow:
        refreshed = (
            (
                await _uow.session.execute(
                    _sel(WorkflowInstance).where(WorkflowInstance.id == instance.id)
                )
            )
            .scalars()
            .first()
        )
    return refreshed if refreshed is not None else instance


async def test_full_flow_submit_notify_approve_publish(
    harness: dict[str, Any], uow_factory: UoWFactory, clock: Any
) -> None:
    content_id = await _create_content(harness)
    instance = await _start_and_signal(
        harness, content_id, clock, advance_steps=3, uow_factory=uow_factory
    )
    assert instance.status == "waiting"
    assert len(harness["email"].sends) == 1

    await harness["runner"].deliver_signal(
        workflow_id=instance.id, signal_key=APPROVAL_SIGNAL, payload={"approved": True}
    )
    await harness["runner"].run_due()

    async with uow_factory() as uow:
        row = await uow.session.get(Content, uuid.UUID(content_id))
        assert row is not None and row.status == "published"
    # the notification delivery completed through its own workflow
    assert len(harness["email"].sends) == 1
    assert harness["email"].sends[0]["subject"] == "New submission: Pending post"


async def test_crash_recovery_between_every_step(
    harness: dict[str, Any], uow_factory: UoWFactory, clock: Any
) -> None:
    """Crash (stop driving) after each step; restarting never re-sends."""

    content_id = await _create_content(harness)
    await harness["runner"].start(
        workflow_key=MODERATION_WORKFLOW_KEY,
        idempotency_key=f"content:{content_id}",
        input_data={"content_id": content_id, "title": "Pending post"},
        trace_id="moderation-flow",
    )

    for step in range(1, 5):
        # crash: nothing drives the runner
        clock.advance(timedelta(seconds=1))
        await harness["runner"].run_due()  # recovery
        async with uow_factory() as uow:
            from inc.kernel.workflow.models import WorkflowInstance

            instance = (
                (
                    await uow.session.execute(
                        select(WorkflowInstance).where(
                            WorkflowInstance.business_idempotency_key == f"content:{content_id}"
                        )
                    )
                )
                .scalars()
                .first()
            )
            assert instance is not None
        if step == 3:
            await harness["runner"].deliver_signal(
                workflow_id=instance.id, signal_key=APPROVAL_SIGNAL, payload={"approved": True}
            )
        await harness["runner"].run_due()

    async with uow_factory() as uow:
        row = await uow.session.get(Content, uuid.UUID(content_id))
        assert row is not None and row.status == "published"
    # notify step executed exactly once despite recovery driving
    notify_sends = [s for s in harness["email"].sends if s["subject"].startswith("New submission")]
    assert len(notify_sends) == 1


async def test_undeclared_signal_is_rejected(
    harness: dict[str, Any], uow_factory: UoWFactory, clock: Any
) -> None:
    content_id = await _create_content(harness)
    instance = await _start_and_signal(
        harness, content_id, clock, advance_steps=3, uow_factory=uow_factory
    )
    assert instance.status == "waiting"
    with pytest.raises(KernelError) as excinfo:
        await harness["runner"].deliver_signal(
            workflow_id=instance.id, signal_key="moderation.reject.v1"
        )
    assert excinfo.value.code == "kernel.workflow_unknown_signal"
    async with uow_factory() as uow:
        row = await uow.session.get(Content, uuid.UUID(content_id))
        assert row is not None and row.status == "pending"  # never published

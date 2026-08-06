"""Outbox/inbox fault-injection tests (events.md §7 exit gate).

Proves, against SQLite with the same UoW/JSONB code paths:

- business state and outbox row commit or vanish together;
- a crash right after commit still delivers after restart;
- duplicate delivery never double-applies (inbox receipts);
- retry backoff, dead letter and unknown-version quarantine;
- leases are not re-claimed while valid and are reclaimed after expiry.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from inc.kernel.db import UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import (
    EventEnvelope,
    EventHandlerRegistry,
    EventSchemaRegistry,
    InboxGuard,
    OutboxDispatcher,
    OutboxRepository,
    OutboxWriter,
)
from inc.kernel.events.models import OutboxMessage
from inc.kernel.time.fake import FakeClock
from inc.kernel.workflow.spec import RetryPolicy
from tests.kernel.conftest import AppliedEvent


class _FactPayload(BaseModel):
    value: int = 0


EVENT_KEY = "test.fact.occurred.v1"


@pytest.fixture
def schema_registry() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    registry.register(EVENT_KEY, _FactPayload)
    registry.register("test.fact.legacy.v9", _FactPayload)
    return registry


@pytest.fixture
def handler_registry() -> EventHandlerRegistry:
    return EventHandlerRegistry()


class RecordingHandler:
    """Handler with optional failures (raised before any work), recording
    applied effects in the database."""

    def __init__(self, key: str, clock: FakeClock) -> None:
        self.key = key
        self._clock = clock
        self.applied: list[str] = []
        self.fail_transiently = False
        self.fail_permanently = False

    async def handle(self, envelope: EventEnvelope, uow: Any) -> None:
        if self.fail_transiently:
            self.fail_transiently = False
            raise RuntimeError("transient boom")
        if self.fail_permanently:
            raise KernelError(
                code="test.handler.rejected",
                category=ErrorCategory.VALIDATION,
                message="permanent rejection",
            )

        async def work() -> None:
            uow.session.add(AppliedEvent(handler_key=self.key, event_id=envelope.event_id))
            self.applied.append(envelope.event_key)

        await InboxGuard.process(
            uow,
            handler_key=self.key,
            event_id=envelope.event_id,
            work=work,
            processed_at=self._clock.utc_now(),
        )


async def append_message(
    uow_factory: UoWFactory,
    schema_registry: EventSchemaRegistry,
    clock: FakeClock,
    *,
    event_key: str = EVENT_KEY,
    payload: dict[str, Any] | None = None,
) -> EventEnvelope:
    envelope = EventEnvelope(
        event_id=uuid.uuid7(),
        event_key=event_key,
        occurred_at=clock.utc_now(),
        producer="tests",
        payload=payload or {"value": 1},
    )
    async with uow_factory() as uow:
        await OutboxWriter(schema_registry, clock).append(uow, envelope)
        await uow.commit()
    return envelope


def make_dispatcher(
    uow_factory: UoWFactory,
    schema_registry: EventSchemaRegistry,
    handler_registry: EventHandlerRegistry,
    clock: FakeClock,
) -> OutboxDispatcher:
    return OutboxDispatcher(
        uow_factory=uow_factory,
        schema_registry=schema_registry,
        handler_registry=handler_registry,
        clock=clock,
        retry_policy=RetryPolicy(base_delay_seconds=1.0, factor=2.0, jitter_seconds=0.0),
    )


async def test_business_state_and_outbox_commit_atomically(
    uow_factory: UoWFactory,
    schema_registry: EventSchemaRegistry,
    clock: FakeClock,
) -> None:
    envelope = EventEnvelope(
        event_id=uuid.uuid7(),
        event_key=EVENT_KEY,
        occurred_at=clock.utc_now(),
        producer="tests",
        payload={"value": 1},
    )
    async with uow_factory() as uow:
        await OutboxWriter(schema_registry, clock).append(uow, envelope)
        uow.session.add(AppliedEvent(handler_key="atomic", event_id=envelope.event_id))
        await uow.commit()

    async with uow_factory() as uow:
        rows = (await uow.session.execute(select(AppliedEvent))).scalars().all()
        assert len(rows) == 1
        messages = (await uow.session.execute(select(OutboxMessage))).scalars().all()
        assert len(messages) == 1


async def test_rollback_discards_business_state_and_outbox(
    uow_factory: UoWFactory,
    schema_registry: EventSchemaRegistry,
    clock: FakeClock,
) -> None:
    envelope = EventEnvelope(
        event_id=uuid.uuid7(),
        event_key=EVENT_KEY,
        occurred_at=clock.utc_now(),
        producer="tests",
        payload={"value": 1},
    )
    with pytest.raises(RuntimeError):
        async with uow_factory() as uow:
            await OutboxWriter(schema_registry, clock).append(uow, envelope)
            uow.session.add(AppliedEvent(handler_key="atomic", event_id=envelope.event_id))
            raise RuntimeError("boom before commit")

    async with uow_factory() as uow:
        assert (await uow.session.execute(select(AppliedEvent))).scalars().all() == []
        assert (await uow.session.execute(select(OutboxMessage))).scalars().all() == []


async def test_crash_after_commit_still_delivers(
    uow_factory: UoWFactory,
    schema_registry: EventSchemaRegistry,
    handler_registry: EventHandlerRegistry,
    clock: FakeClock,
) -> None:
    handler = RecordingHandler("test.crash.handler.v1", clock)
    handler_registry.register(EVENT_KEY, handler)
    await append_message(uow_factory, schema_registry, clock)

    dispatcher = make_dispatcher(uow_factory, schema_registry, handler_registry, clock)
    processed = await dispatcher.dispatch_cycle(lease_seconds=60)
    assert processed == 1
    assert handler.applied == [EVENT_KEY]

    async with uow_factory() as uow:
        assert await OutboxRepository(uow).count_by_status("delivered") == 1


async def test_redelivery_after_crash_does_not_double_apply(
    uow_factory: UoWFactory,
    schema_registry: EventSchemaRegistry,
    handler_registry: EventHandlerRegistry,
    clock: FakeClock,
) -> None:
    """Crash window: handler committed business + receipt, message not yet
    marked delivered. After lease expiry the message is re-claimed and
    re-delivered; the inbox receipt makes the second delivery a no-op."""

    handler = RecordingHandler("test.crash.handler.v1", clock)
    handler_registry.register(EVENT_KEY, handler)
    await append_message(uow_factory, schema_registry, clock)

    # Simulate the dispatcher crashing right after the handler commit.
    async with uow_factory() as claim_uow:
        messages = await OutboxRepository(claim_uow).claim_due(
            batch=10, lease_owner="crash-sim", lease_seconds=60, now=clock.utc_now()
        )
        await claim_uow.commit()
    assert len(messages) == 1
    async with uow_factory() as uow:
        await handler.handle(messages[0].envelope, uow)
        await uow.commit()
    assert handler.applied == [EVENT_KEY]
    # Process "crashed": message stays claimed with an unexpired lease.

    dispatcher = make_dispatcher(uow_factory, schema_registry, handler_registry, clock)
    assert await dispatcher.dispatch_cycle(lease_seconds=60) == 0  # lease still valid

    clock.advance(timedelta(seconds=120))
    assert await dispatcher.dispatch_cycle(lease_seconds=60) == 1
    assert handler.applied == [EVENT_KEY]  # not double-applied

    async with uow_factory() as uow:
        assert await OutboxRepository(uow).count_by_status("delivered") == 1
        receipts = (await uow.session.execute(select(AppliedEvent))).scalars().all()
        assert len(receipts) == 1


async def test_transient_failure_retries_then_delivers(
    uow_factory: UoWFactory,
    schema_registry: EventSchemaRegistry,
    handler_registry: EventHandlerRegistry,
    clock: FakeClock,
) -> None:
    handler = RecordingHandler("test.retry.handler.v1", clock)
    handler.fail_transiently = True
    handler_registry.register(EVENT_KEY, handler)
    await append_message(uow_factory, schema_registry, clock)

    dispatcher = make_dispatcher(uow_factory, schema_registry, handler_registry, clock)
    assert await dispatcher.dispatch_cycle(lease_seconds=60) == 1

    async with uow_factory() as uow:
        message = (await uow.session.execute(select(OutboxMessage))).scalars().first()
        assert message is not None
        assert message.status == "pending"
        assert message.attempts == 1
        assert message.last_error_category == "transient"
        assert message.next_attempt_at is not None

    clock.advance(timedelta(seconds=30))
    assert await dispatcher.dispatch_cycle(lease_seconds=60) == 1
    assert handler.applied == [EVENT_KEY]

    async with uow_factory() as uow:
        assert await OutboxRepository(uow).count_by_status("delivered") == 1


async def test_permanent_failure_goes_to_dead_letter(
    uow_factory: UoWFactory,
    schema_registry: EventSchemaRegistry,
    handler_registry: EventHandlerRegistry,
    clock: FakeClock,
) -> None:
    handler = RecordingHandler("test.dead.handler.v1", clock)
    handler.fail_permanently = True
    handler_registry.register(EVENT_KEY, handler)
    await append_message(uow_factory, schema_registry, clock)

    dispatcher = make_dispatcher(uow_factory, schema_registry, handler_registry, clock)
    assert await dispatcher.dispatch_cycle(lease_seconds=60) == 1

    async with uow_factory() as uow:
        message = (await uow.session.execute(select(OutboxMessage))).scalars().first()
        assert message is not None
        assert message.status == "dead"
        assert message.last_error_category == "permanent"
        assert handler.applied == []


async def test_unknown_event_version_is_quarantined(
    uow_factory: UoWFactory,
    schema_registry: EventSchemaRegistry,
    handler_registry: EventHandlerRegistry,
    clock: FakeClock,
) -> None:
    # Write the event while its schema is known; deliver with a registry that
    # no longer knows the version (downgraded/legacy deployment scenario).
    await append_message(uow_factory, schema_registry, clock, event_key="test.fact.legacy.v9")

    unknown_registry = EventSchemaRegistry()
    dispatcher = make_dispatcher(uow_factory, unknown_registry, handler_registry, clock)
    assert await dispatcher.dispatch_cycle(lease_seconds=60) == 1

    async with uow_factory() as uow:
        message = (await uow.session.execute(select(OutboxMessage))).scalars().first()
        assert message is not None
        assert message.status == "dead"
        assert "unknown event schema" in (message.error_summary or "")


async def test_outbox_writer_rejects_unregistered_event(
    uow_factory: UoWFactory,
    schema_registry: EventSchemaRegistry,
    clock: FakeClock,
) -> None:
    envelope = EventEnvelope(
        event_id=uuid.uuid7(),
        event_key="test.never.registered.v1",
        occurred_at=clock.utc_now(),
        producer="tests",
        payload={},
    )
    with pytest.raises(KernelError) as excinfo:
        async with uow_factory() as uow:
            await OutboxWriter(schema_registry, clock).append(uow, envelope)
    assert excinfo.value.code == "kernel.event_unknown_schema"


async def test_outbox_writer_validates_payload_schema(
    uow_factory: UoWFactory,
    schema_registry: EventSchemaRegistry,
    clock: FakeClock,
) -> None:
    envelope = EventEnvelope(
        event_id=uuid.uuid7(),
        event_key=EVENT_KEY,
        occurred_at=clock.utc_now(),
        producer="tests",
        payload={"value": "not-an-integer"},
    )
    with pytest.raises(ValidationError):
        async with uow_factory() as uow:
            await OutboxWriter(schema_registry, clock).append(uow, envelope)


async def test_lease_blocks_reclaim_until_expiry(
    uow_factory: UoWFactory,
    schema_registry: EventSchemaRegistry,
    handler_registry: EventHandlerRegistry,
    clock: FakeClock,
) -> None:
    handler = RecordingHandler("test.lease.handler.v1", clock)
    handler_registry.register(EVENT_KEY, handler)
    await append_message(uow_factory, schema_registry, clock)

    async with uow_factory() as claim_uow:
        messages = await OutboxRepository(claim_uow).claim_due(
            batch=10, lease_owner="worker-a", lease_seconds=60, now=clock.utc_now()
        )
        await claim_uow.commit()
    assert len(messages) == 1

    async with uow_factory() as other_uow:
        others = await OutboxRepository(other_uow).claim_due(
            batch=10, lease_owner="worker-b", lease_seconds=60, now=clock.utc_now()
        )
        await other_uow.commit()
    assert others == []  # unexpired lease blocks worker-b

    clock.advance(timedelta(seconds=120))
    async with uow_factory() as other_uow:
        others = await OutboxRepository(other_uow).claim_due(
            batch=10, lease_owner="worker-b", lease_seconds=60, now=clock.utc_now()
        )
        await other_uow.commit()
    assert len(others) == 1
    assert others[0].lease_owner == "worker-b"

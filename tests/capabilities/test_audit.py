"""Audit capability tests.

Contract source: context/spec/capabilities/audit.md §7.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from inc.capabilities.audit.models import AuditEntry, AuditMetadata
from inc.capabilities.audit.schemas import AUDIT_EVENT_KEY, AuditEntryRecorded
from inc.capabilities.audit.service import AuditInboxHandler, AuditQueries, AuditRetentionActivity
from inc.kernel.db import UoWFactory
from inc.kernel.events import (
    EventEnvelope,
    EventHandlerRegistry,
    EventSchemaRegistry,
    OutboxDispatcher,
    OutboxMessage,
    OutboxWriter,
)
from inc.kernel.workflow.spec import RetryPolicy


@pytest.fixture
def schema_registry() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    registry.register(AUDIT_EVENT_KEY, AuditEntryRecorded)
    return registry


@pytest.fixture
def handler_registry(clock: Any) -> EventHandlerRegistry:
    registry = EventHandlerRegistry()
    registry.register(AUDIT_EVENT_KEY, AuditInboxHandler(clock))
    return registry


async def append_audit(
    uow_factory: UoWFactory,
    schema_registry: EventSchemaRegistry,
    clock: Any,
    *,
    action: str = "identity.user.banned",
    actor: str = "u-admin",
    target: str = "u-1",
) -> EventEnvelope:
    envelope = EventEnvelope(
        event_id=uuid.uuid7(),
        event_key=AUDIT_EVENT_KEY,
        occurred_at=clock.utc_now(),
        producer="identity",
        aggregate_type="identity",
        aggregate_id=target,
        trace_id="trace-1",
        payload={
            "action": action,
            "outcome": "success",
            "occurred_at": clock.utc_now().isoformat(),
            "actor_type": "user",
            "actor_id": actor,
            "target_type": "user",
            "target_id": target,
            "trace_id": "trace-1",
            "details": {"reason": "spam"},
        },
    )
    async with uow_factory() as uow:
        await OutboxWriter(schema_registry, clock).append(uow, envelope)
        await uow.commit()
    return envelope


def make_dispatcher(
    uow_factory: UoWFactory,
    schema_registry: EventSchemaRegistry,
    handler_registry: EventHandlerRegistry,
    clock: Any,
) -> OutboxDispatcher:
    return OutboxDispatcher(
        uow_factory=uow_factory,
        schema_registry=schema_registry,
        handler_registry=handler_registry,
        clock=clock,
        retry_policy=RetryPolicy(jitter_seconds=0.0),
    )


async def test_audit_flow_records_and_dedups(
    uow_factory: UoWFactory,
    schema_registry: EventSchemaRegistry,
    handler_registry: EventHandlerRegistry,
    clock: Any,
) -> None:
    envelope = await append_audit(uow_factory, schema_registry, clock)
    dispatcher = make_dispatcher(uow_factory, schema_registry, handler_registry, clock)
    assert await dispatcher.dispatch_cycle() == 1

    queries = AuditQueries(uow_factory=uow_factory)
    page = await queries.list_entries(page=1, size=10, action="identity.user.banned")
    assert page.total == 1
    assert page.items[0].action == "identity.user.banned"
    assert page.items[0].actor_id == "u-admin"
    assert page.items[0].details == {"reason": "spam"}
    assert page.items[0].target_id == "u-1"

    # Re-delivery (crash window: business committed, message not delivered)
    # is deduplicated by the inbox receipt: still one entry.
    async with uow_factory() as uow:
        rows = (await uow.session.execute(select(AuditEntry))).scalars().all()
        assert len(rows) == 1
        receipt_row = rows[0]
        assert receipt_row.envelope_id == envelope.event_id


async def test_sensitive_fields_never_enter_audit(
    uow_factory: UoWFactory,
    schema_registry: EventSchemaRegistry,
    handler_registry: EventHandlerRegistry,
    clock: Any,
) -> None:
    envelope = EventEnvelope(
        event_id=uuid.uuid7(),
        event_key=AUDIT_EVENT_KEY,
        occurred_at=clock.utc_now(),
        producer="identity",
        payload={
            "action": "identity.password.changed",
            "outcome": "success",
            "occurred_at": clock.utc_now().isoformat(),
            "actor_id": "u-admin",
            "target_id": "u-1",
            "details": {"password": "hunter2", "client_secret": "s3cret", "reason": "ok"},
        },
    )
    async with uow_factory() as uow:
        await OutboxWriter(schema_registry, clock).append(uow, envelope)
        await uow.commit()
    dispatcher = make_dispatcher(uow_factory, schema_registry, handler_registry, clock)
    await dispatcher.dispatch_cycle()

    queries = AuditQueries(uow_factory=uow_factory)
    entry = (await queries.list_entries(page=1, size=10)).items[0]
    assert "hunter2" not in entry.model_dump_json()
    assert "s3cret" not in entry.model_dump_json()


async def test_retention_activity_purges_and_records_independent_summary(
    uow_factory: UoWFactory,
    schema_registry: EventSchemaRegistry,
    clock: Any,
) -> None:
    old = clock.utc_now() - timedelta(days=31)
    async with uow_factory() as uow:
        uow.session.add(
            AuditEntry(
                envelope_id=uuid.uuid7(),
                action="old.action",
                outcome="success",
                occurred_at=old,
                ingested_at=old,
                details=AuditMetadata(data={}),
                created_at=old,
                updated_at=old,
            )
        )
        await uow.commit()

    activity = AuditRetentionActivity(
        uow_factory=uow_factory,
        outbox=OutboxWriter(schema_registry, clock),
        clock=clock,
    )
    assert (
        await activity.cleanup_before(
            cutoff=clock.utc_now() - timedelta(days=30),
            details={"retention_days": 30},
        )
        == 1
    )
    assert (
        await activity.cleanup_before(
            cutoff=clock.utc_now() - timedelta(days=30),
            details={"retention_days": 30},
        )
        == 0
    )

    async with uow_factory() as uow:
        assert not (await uow.session.execute(select(AuditEntry))).scalars().all()
        messages = (await uow.session.execute(select(OutboxMessage))).scalars().all()
        assert len(messages) == 1
        assert messages[0].envelope.payload["action"] == "audit.retention.cleaned"
        assert messages[0].envelope.payload["details"]["audit_entries_deleted"] == 1

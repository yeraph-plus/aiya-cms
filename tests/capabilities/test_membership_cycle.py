"""Membership prepare/attach cycle contract tests."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest

from inc.capabilities.membership.commands import (
    AttachPointsGrant,
    CommandContext,
    MarkCycleFailed,
    PrepareSubscriptionCycle,
)
from inc.capabilities.membership.events import MEMBERSHIP_EVENT_SCHEMAS
from inc.capabilities.membership.levels import MembershipLevelRegistry, MembershipLevelSpec
from inc.capabilities.membership.queries import MembershipQueries
from inc.capabilities.membership.schemas import (
    AttachPointsGrantInput,
    MarkCycleFailedInput,
    PrepareSubscriptionCycleInput,
)
from inc.kernel.db import UoWFactory
from inc.kernel.errors import KernelError
from inc.kernel.events import EventSchemaRegistry, OutboxWriter


@pytest.fixture
def levels() -> MembershipLevelRegistry:
    registry = MembershipLevelRegistry()
    registry.register(
        MembershipLevelSpec(
            key="basic",
            display_name="Basic",
            tier_rank=1,
            cycle_days=30,
            cycle_points_amount=100,
        )
    )
    return registry


@pytest.fixture
def ctx(
    uow_factory: UoWFactory,
    clock: Any,
    levels: MembershipLevelRegistry,
) -> CommandContext:
    schemas = EventSchemaRegistry()
    for key, schema in MEMBERSHIP_EVENT_SCHEMAS.items():
        schemas.register(key, schema)
    return CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schemas, clock),
        levels=levels,
    )


@pytest.fixture
def queries(uow_factory: UoWFactory, levels: MembershipLevelRegistry) -> MembershipQueries:
    return MembershipQueries(uow_factory=uow_factory, levels=levels)


def prepare_input(**values: Any) -> PrepareSubscriptionCycleInput:
    payload = {
        "subject_type": "identity",
        "subject_id": "user-1",
        "level_key": "basic",
        "source_type": "payment_order",
        "source_ref": "order-1",
        "idempotency_key": "prepare-1",
    }
    payload.update(values)
    return PrepareSubscriptionCycleInput(**payload)


async def test_prepared_cycle_does_not_activate_subscription(
    ctx: CommandContext, queries: MembershipQueries, clock: Any
) -> None:
    cycle = await PrepareSubscriptionCycle(ctx)(prepare_input())

    assert cycle.state == "prepared"
    assert cycle.points_entry_ref is None
    assert cycle.cycle_points_amount == 100
    assert cycle.cycle_start == clock.utc_now()
    assert cycle.cycle_end == clock.utc_now() + timedelta(days=30)
    subscription = await queries.get_subscription(subject_type="identity", subject_id="user-1")
    assert subscription is not None
    assert subscription.status == "pending_activation"
    assert subscription.cycle_id == cycle.cycle_id


async def test_prepare_replay_returns_same_cycle(
    ctx: CommandContext, queries: MembershipQueries
) -> None:
    first = await PrepareSubscriptionCycle(ctx)(prepare_input())
    replay = await PrepareSubscriptionCycle(ctx)(prepare_input())

    assert replay == first
    cycles = await queries.list_membership_cycles(page=1, size=10)
    assert cycles.total == 1


async def test_prepare_replay_rejects_changed_business_input(ctx: CommandContext) -> None:
    await PrepareSubscriptionCycle(ctx)(prepare_input())
    with pytest.raises(KernelError) as excinfo:
        await PrepareSubscriptionCycle(ctx)(prepare_input(source_ref="order-2"))
    assert excinfo.value.code == "membership.idempotency_conflict"


async def test_attach_activates_and_replay_cannot_rebind(
    ctx: CommandContext, queries: MembershipQueries
) -> None:
    cycle = await PrepareSubscriptionCycle(ctx)(prepare_input())
    entry_ref = str(uuid.uuid4())
    body = AttachPointsGrantInput(
        cycle_id=cycle.cycle_id,
        points_entry_ref=entry_ref,
        idempotency_key="attach-1",
    )

    activated = await AttachPointsGrant(ctx)(body)
    replay = await AttachPointsGrant(ctx)(body.model_copy(update={"idempotency_key": "attach-2"}))
    assert activated.state == "activated"
    assert replay == activated
    subscription = await queries.get_subscription(subject_type="identity", subject_id="user-1")
    assert subscription is not None and subscription.status == "active"

    with pytest.raises(KernelError) as excinfo:
        await AttachPointsGrant(ctx)(
            body.model_copy(
                update={"points_entry_ref": str(uuid.uuid4()), "idempotency_key": "attach-3"}
            )
        )
    assert excinfo.value.code == "membership.points_grant_already_attached"


async def test_attach_requires_uuid_points_entry_ref(ctx: CommandContext) -> None:
    cycle = await PrepareSubscriptionCycle(ctx)(prepare_input())
    with pytest.raises(KernelError) as excinfo:
        await AttachPointsGrant(ctx)(
            AttachPointsGrantInput(
                cycle_id=cycle.cycle_id,
                points_entry_ref="not-an-entry",
                idempotency_key="attach-1",
            )
        )
    assert excinfo.value.code == "membership.invalid_points_entry_ref"


async def test_failure_only_applies_to_prepared_cycle(
    ctx: CommandContext, queries: MembershipQueries
) -> None:
    cycle = await PrepareSubscriptionCycle(ctx)(prepare_input())
    failed = await MarkCycleFailed(ctx)(
        MarkCycleFailedInput(
            cycle_id=cycle.cycle_id,
            failure_code="points.credit_rejected",
            idempotency_key="fail-1",
        )
    )
    assert failed.state == "failed"
    assert failed.failure_code == "points.credit_rejected"
    subscription = await queries.get_subscription(subject_type="identity", subject_id="user-1")
    assert subscription is not None and subscription.status == "failed"

    with pytest.raises(KernelError) as excinfo:
        await AttachPointsGrant(ctx)(
            AttachPointsGrantInput(
                cycle_id=cycle.cycle_id,
                points_entry_ref=str(uuid.uuid4()),
                idempotency_key="attach-1",
            )
        )
    assert excinfo.value.code == "membership.cycle_not_prepared"


async def test_activated_cycle_cannot_be_failed(ctx: CommandContext) -> None:
    cycle = await PrepareSubscriptionCycle(ctx)(prepare_input())
    await AttachPointsGrant(ctx)(
        AttachPointsGrantInput(
            cycle_id=cycle.cycle_id,
            points_entry_ref=str(uuid.uuid4()),
            idempotency_key="attach-1",
        )
    )
    with pytest.raises(KernelError) as excinfo:
        await MarkCycleFailed(ctx)(
            MarkCycleFailedInput(
                cycle_id=cycle.cycle_id,
                failure_code="abandoned",
                idempotency_key="fail-1",
            )
        )
    assert excinfo.value.code == "membership.cycle_not_prepared"

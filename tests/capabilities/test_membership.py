"""Membership lifecycle tests outside the prepare/attach protocol."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest

from inc.capabilities.membership.commands import (
    AttachPointsGrant,
    CancelSubscription,
    CommandContext,
    ExpireSubscription,
    PrepareSubscriptionCycle,
    TerminateSubscription,
)
from inc.capabilities.membership.events import MEMBERSHIP_EVENT_SCHEMAS
from inc.capabilities.membership.levels import MembershipLevelRegistry, MembershipLevelSpec
from inc.capabilities.membership.queries import MembershipQueries
from inc.capabilities.membership.schemas import (
    AttachPointsGrantInput,
    CancelInput,
    PrepareSubscriptionCycleInput,
    TerminateInput,
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
def ctx(uow_factory: UoWFactory, clock: Any, levels: MembershipLevelRegistry) -> CommandContext:
    schemas = EventSchemaRegistry()
    for key, schema in MEMBERSHIP_EVENT_SCHEMAS.items():
        schemas.register(key, schema)
    return CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schemas, clock),
        levels=levels,
        permissions=frozenset({"membership.subscriptions.manage"}),
    )


@pytest.fixture
def queries(uow_factory: UoWFactory, levels: MembershipLevelRegistry) -> MembershipQueries:
    return MembershipQueries(uow_factory=uow_factory, levels=levels)


async def _activate(ctx: CommandContext) -> str:
    cycle = await PrepareSubscriptionCycle(ctx)(
        PrepareSubscriptionCycleInput(
            subject_type="identity",
            subject_id="user-1",
            level_key="basic",
            source_type="payment_order",
            source_ref="order-1",
            idempotency_key="prepare-1",
            auto_renew=True,
        )
    )
    await AttachPointsGrant(ctx)(
        AttachPointsGrantInput(
            cycle_id=cycle.cycle_id,
            points_entry_ref=str(uuid.uuid4()),
            idempotency_key="attach-1",
        )
    )
    return cycle.subscription_id


async def test_cancel_preserves_current_entitlement_until_expiry(
    ctx: CommandContext, queries: MembershipQueries, clock: Any
) -> None:
    subscription_id = await _activate(ctx)
    cancelled = await CancelSubscription(ctx)(
        CancelInput(subscription_id=subscription_id, reason="stop renewal")
    )
    assert cancelled.status == "cancelled"
    assert cancelled.auto_renew is False

    clock.advance(timedelta(days=31))
    expired = await ExpireSubscription(ctx)()
    assert [item.id for item in expired] == [subscription_id]
    current = await queries.get_subscription(subject_type="identity", subject_id="user-1")
    assert current is not None and current.status == "expired"


async def test_terminate_requires_permission(
    ctx: CommandContext, uow_factory: UoWFactory, clock: Any, levels: MembershipLevelRegistry
) -> None:
    restricted = CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=ctx.outbox,
        levels=levels,
    )
    with pytest.raises(KernelError) as excinfo:
        await TerminateSubscription(restricted)(
            TerminateInput(subscription_id=str(uuid.uuid4()), reason="admin action")
        )
    assert excinfo.value.code == "membership.forbidden"


async def test_terminate_ends_entitlement_without_points_dependency(ctx: CommandContext) -> None:
    subscription_id = await _activate(ctx)
    terminated = await TerminateSubscription(ctx)(
        TerminateInput(subscription_id=subscription_id, reason="admin action")
    )
    assert terminated.status == "terminated"
    assert terminated.terminated_at is not None


async def test_cycle_queries_support_recovery_and_reconciliation(
    ctx: CommandContext, queries: MembershipQueries
) -> None:
    await _activate(ctx)
    page = await queries.list_membership_cycles(page=1, size=10, state="activated")
    assert page.total == 1
    cycle = await queries.get_membership_cycle(page.items[0].cycle_id)
    assert cycle == page.items[0]

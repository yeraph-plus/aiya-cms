"""Membership <-> points integration tests.

Contract source: context/spec/capabilities/membership.md §4/§11.

The composition root binds PointsLedgerPort to points' public CreditPoints
command. These tests exercise that binding end-to-end: subscribing grants
points into an expiring bucket with expires_at = cycle end, spending works
while active, and the points expiration sweep zeroes the remaining quota
at cycle end without any settlement logic in membership.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from inc.capabilities.membership.commands import (
    CommandContext as MembershipCommandContext,
)
from inc.capabilities.membership.commands import (
    ExpireSubscription,
    SubscribeLevel,
)
from inc.capabilities.membership.events import MEMBERSHIP_EVENT_SCHEMAS
from inc.capabilities.membership.levels import (
    MembershipLevelRegistry,
    MembershipLevelSpec,
)
from inc.capabilities.membership.ports import PointsLedgerPort
from inc.capabilities.membership.schemas import SubscribeInput
from inc.capabilities.points import (
    CommandContext as PointsCommandContext,
)
from inc.capabilities.points import (
    PointBehaviorRegistry,
    PointBehaviorSpec,
)
from inc.capabilities.points.commands import (
    CreditPoints,
    DebitPoints,
    ExpireBuckets,
    OpenPointsAccount,
)
from inc.capabilities.points.events import POINTS_EVENT_SCHEMAS
from inc.capabilities.points.models import PointsProgram
from inc.capabilities.points.queries import PointsQueries
from inc.capabilities.points.schemas import CreditDebitInput
from inc.kernel.db import UoWFactory
from inc.kernel.events import EventSchemaRegistry, OutboxWriter

MEMBERSHIP_BEHAVIOR = "membership.grant"
SPEND_BEHAVIOR = "download.consume"

SUBJECT = ("identity", "user-1")


@pytest.fixture
def schema_registry() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    for key, schema in POINTS_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    for key, schema in MEMBERSHIP_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    return registry


@pytest.fixture
def behaviors() -> PointBehaviorRegistry:
    registry = PointBehaviorRegistry()
    registry.register(
        PointBehaviorSpec(
            key=MEMBERSHIP_BEHAVIOR,
            version="1",
            program_key="default",
            direction="credit",
            min_amount=1,
            max_amount=1_000_000,
            allowed_source_types=("membership",),
        )
    )
    registry.register(
        PointBehaviorSpec(
            key=SPEND_BEHAVIOR,
            version="1",
            program_key="default",
            direction="debit",
            fixed_amount=1,
        )
    )
    return registry


@pytest.fixture
def levels() -> MembershipLevelRegistry:
    registry = MembershipLevelRegistry()
    registry.register(
        MembershipLevelSpec(
            key="basic",
            display_name="Basic",
            tier_rank=1,
            cycle_days=30,
            grant_points=100,
        )
    )
    return registry


@pytest.fixture
async def program(uow_factory: UoWFactory) -> None:
    async with uow_factory() as uow:
        uow.session.add(
            PointsProgram(
                program_key="default", display_name="Default", unit="points", status="active"
            )
        )
        await uow.commit()


async def _exists(subject_type: str, subject_id: str) -> bool:
    return True


class RealPointsLedger(PointsLedgerPort):
    """Composition-root binding: points' public CreditPoints command."""

    def __init__(self, points_ctx: PointsCommandContext) -> None:
        self._points_ctx = points_ctx

    async def grant_points(
        self,
        *,
        subject_type: str,
        subject_id: str,
        amount: int,
        expires_at: Any,
        idempotency_key: str,
        source_ref: str,
    ) -> dict[str, Any]:
        async with self._points_ctx.uow_factory() as uow:
            result = await self.grant_points_in_uow(
                uow,
                subject_type=subject_type,
                subject_id=subject_id,
                amount=amount,
                expires_at=expires_at,
                idempotency_key=idempotency_key,
                source_ref=source_ref,
            )
            await uow.commit()
            return result

    async def grant_points_in_uow(
        self,
        uow: Any,
        *,
        subject_type: str,
        subject_id: str,
        amount: int,
        expires_at: Any,
        idempotency_key: str,
        source_ref: str,
    ) -> dict[str, Any]:
        entry = await CreditPoints(self._points_ctx).credit_in_uow(
            uow,
            MEMBERSHIP_BEHAVIOR,
            CreditDebitInput(
                subject_type=subject_type,
                subject_id=subject_id,
                amount=amount,
                source_type="membership",
                source_id=source_ref,
                idempotency_key=idempotency_key,
                actor_type="system",
                actor_id="membership",
                expires_at=expires_at,
            ),
        )
        return {"entry_id": entry.id}


@pytest.fixture
def points_ctx(
    uow_factory: UoWFactory,
    clock: Any,
    behaviors: PointBehaviorRegistry,
    schema_registry: EventSchemaRegistry,
) -> PointsCommandContext:
    return PointsCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        behaviors=behaviors,
        permissions=frozenset(),
        actor_id="system",
        trace_id="trace-1",
    )


@pytest.fixture
def membership_ctx(
    uow_factory: UoWFactory,
    clock: Any,
    levels: MembershipLevelRegistry,
    schema_registry: EventSchemaRegistry,
    points_ctx: PointsCommandContext,
) -> MembershipCommandContext:
    return MembershipCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        levels=levels,
        subject_exists=_exists,
        points_ledger=RealPointsLedger(points_ctx),
        permissions=frozenset(),
        actor_id="system",
        trace_id="trace-1",
    )


@pytest.fixture
def points_queries(uow_factory: UoWFactory, behaviors: PointBehaviorRegistry) -> PointsQueries:
    return PointsQueries(uow_factory=uow_factory, behaviors=behaviors)


async def _spend(points_ctx: PointsCommandContext, amount: int, key: str) -> Any:
    return await DebitPoints(points_ctx)(
        SPEND_BEHAVIOR,
        CreditDebitInput(
            subject_type=SUBJECT[0],
            subject_id=SUBJECT[1],
            amount=amount,
            source_type="system",
            source_id=f"download-{key}",
            idempotency_key=f"spend-{key}",
        ),
    )


async def test_subscribe_grants_points_into_expiring_bucket(
    membership_ctx: MembershipCommandContext,
    points_ctx: PointsCommandContext,
    points_queries: PointsQueries,
    program: None,
) -> None:
    await OpenPointsAccount(points_ctx)(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    sub = await SubscribeLevel(membership_ctx)(
        SubscribeInput(
            subject_type=SUBJECT[0],
            subject_id=SUBJECT[1],
            level_key="basic",
            idempotency_key="sub-1",
        )
    )
    balance = await points_queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert balance.balance == 100

    from inc.capabilities.points.models import PointsBucket

    async with points_ctx.uow_factory() as uow:
        from sqlalchemy import select

        rows = (await uow.session.execute(select(PointsBucket))).scalars().all()
    expiring = [r for r in rows if r.bucket_type == "expiring"]
    assert len(expiring) == 1
    assert expiring[0].expiration_identity == MEMBERSHIP_BEHAVIOR
    assert expiring[0].amount == 100
    # expires_at equals the subscription cycle end, not created_at + days
    assert expiring[0].expires_at.replace(tzinfo=None) == sub.cycle_end.replace(tzinfo=None)


async def test_membership_points_spendable_while_active(
    membership_ctx: MembershipCommandContext,
    points_ctx: PointsCommandContext,
    points_queries: PointsQueries,
    program: None,
) -> None:
    await OpenPointsAccount(points_ctx)(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    await SubscribeLevel(membership_ctx)(
        SubscribeInput(
            subject_type=SUBJECT[0],
            subject_id=SUBJECT[1],
            level_key="basic",
            idempotency_key="sub-1",
        )
    )
    await _spend(points_ctx, 1, "a")
    balance = await points_queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert balance.balance == 99


async def test_expiry_zeroes_remaining_quota_without_membership_settlement(
    membership_ctx: MembershipCommandContext,
    points_ctx: PointsCommandContext,
    points_queries: PointsQueries,
    clock: Any,
    program: None,
) -> None:
    """Cycle ends: points sweep zeroes the remaining quota; membership only
    converges subscription status and never settles points itself."""
    await OpenPointsAccount(points_ctx)(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    await SubscribeLevel(membership_ctx)(
        SubscribeInput(
            subject_type=SUBJECT[0],
            subject_id=SUBJECT[1],
            level_key="basic",
            idempotency_key="sub-1",
        )
    )
    await _spend(points_ctx, 40, "a")
    balance = await points_queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert balance.balance == 60

    clock.advance(timedelta(days=31))

    # points' own expiration sweep zeroes the remaining 60
    entries = await ExpireBuckets(points_ctx)()
    assert len(entries) == 1
    assert entries[0].entry_type == "expiration"
    assert entries[0].amount == -60
    balance = await points_queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert balance.balance == 0

    # membership only marks the subscription expired; it never debited
    expired = await ExpireSubscription(membership_ctx)()
    assert len(expired) == 1
    assert expired[0].status == "expired"
    from inc.capabilities.points.models import PointsLedgerEntry

    async with points_ctx.uow_factory() as uow:
        from sqlalchemy import select

        rows = (
            (
                await uow.session.execute(
                    select(PointsLedgerEntry).where(
                        PointsLedgerEntry.behavior_key == MEMBERSHIP_BEHAVIOR
                    )
                )
            )
            .scalars()
            .all()
        )
    # only the original grant and the points-side expiration entry exist;
    # membership never issued a settlement debit
    assert sorted(r.entry_type for r in rows) == ["credit", "expiration"]


async def test_renew_grants_new_cycle_quota_with_new_expiry(
    membership_ctx: MembershipCommandContext,
    points_ctx: PointsCommandContext,
    points_queries: PointsQueries,
    clock: Any,
    program: None,
) -> None:
    from inc.capabilities.membership.commands import RenewSubscription
    from inc.capabilities.membership.schemas import RenewInput

    await OpenPointsAccount(points_ctx)(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    sub = await SubscribeLevel(membership_ctx)(
        SubscribeInput(
            subject_type=SUBJECT[0],
            subject_id=SUBJECT[1],
            level_key="basic",
            idempotency_key="sub-1",
        )
    )
    clock.advance(timedelta(days=31))
    renewed = await RenewSubscription(membership_ctx)(
        RenewInput(subscription_id=sub.id, idempotency_key="renew-1")
    )
    balance = await points_queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert balance.balance == 200
    from inc.capabilities.points.models import PointsBucket

    async with points_ctx.uow_factory() as uow:
        from sqlalchemy import select

        rows = (await uow.session.execute(select(PointsBucket))).scalars().all()
    expiring = [r for r in rows if r.bucket_type == "expiring"]
    assert len(expiring) == 2  # one bucket per cycle end
    expiries = sorted(r.expires_at for r in expiring)
    assert expiries[0].replace(tzinfo=None) == sub.cycle_end.replace(tzinfo=None)
    assert expiries[1].replace(tzinfo=None) == renewed.cycle_end.replace(tzinfo=None)

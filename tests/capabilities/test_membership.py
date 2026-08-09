"""Membership capability tests.

Contract source: context/spec/capabilities/membership.md §3/§5/§11.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from inc.capabilities.membership.commands import (
    CancelSubscription,
    CommandContext,
    ExpireSubscription,
    RenewSubscription,
    SubscribeLevel,
    TerminateSubscription,
)
from inc.capabilities.membership.diagnostics import MembershipDiagnostics
from inc.capabilities.membership.events import MEMBERSHIP_EVENT_SCHEMAS
from inc.capabilities.membership.levels import (
    MembershipLevelRegistry,
    MembershipLevelSpec,
)
from inc.capabilities.membership.models import MembershipRenewalRecord
from inc.capabilities.membership.ports import (
    RecordingPointsLedger,
    SubjectExistsPort,
)
from inc.capabilities.membership.queries import MembershipQueries
from inc.capabilities.membership.schemas import (
    CancelInput,
    RenewInput,
    SubscribeInput,
    TerminateInput,
)
from inc.kernel.db import UoWFactory
from inc.kernel.errors import KernelError
from inc.kernel.events import EventSchemaRegistry, OutboxWriter


def make_levels() -> MembershipLevelRegistry:
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
    registry.register(
        MembershipLevelSpec(
            key="pro",
            display_name="Pro",
            tier_rank=2,
            cycle_days=30,
            grant_points=500,
            renewal_allowed=False,
        )
    )
    return registry


@pytest.fixture
def levels() -> MembershipLevelRegistry:
    return make_levels()


@pytest.fixture
def schema_registry() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    for key, schema in MEMBERSHIP_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    return registry


async def _exists(subject_type: str, subject_id: str) -> bool:
    return subject_id in ("user-1", "user-2")


@pytest.fixture
def subject_exists() -> SubjectExistsPort:
    return _exists


@pytest.fixture
def points_ledger() -> RecordingPointsLedger:
    return RecordingPointsLedger()


@pytest.fixture
def ctx(
    uow_factory: UoWFactory,
    clock: Any,
    levels: MembershipLevelRegistry,
    subject_exists: SubjectExistsPort,
    points_ledger: RecordingPointsLedger,
    schema_registry: EventSchemaRegistry,
) -> CommandContext:
    return CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        levels=levels,
        subject_exists=subject_exists,
        points_ledger=points_ledger,
        permissions=frozenset({"membership.manage"}),
        actor_id="admin-1",
        trace_id="trace-1",
    )


@pytest.fixture
def queries(uow_factory: UoWFactory, levels: MembershipLevelRegistry) -> MembershipQueries:
    return MembershipQueries(uow_factory=uow_factory, levels=levels)


SUBJECT = ("identity", "user-1")


def subscribe_input(**overrides: Any) -> SubscribeInput:
    base = {
        "subject_type": SUBJECT[0],
        "subject_id": SUBJECT[1],
        "level_key": "basic",
        "idempotency_key": "sub-1",
    }
    base.update(overrides)
    return SubscribeInput(**base)


# --- subscribe -------------------------------------------------------------


async def test_subscribe_opens_active_cycle_and_grants_points(
    ctx: CommandContext,
    clock: Any,
    points_ledger: RecordingPointsLedger,
    queries: MembershipQueries,
) -> None:
    sub = await SubscribeLevel(ctx)(subscribe_input())
    assert sub.status == "active"
    assert sub.level_key == "basic"
    assert sub.granted_points == 100
    assert sub.renewal_count == 0
    assert sub.cycle_start == clock.utc_now()
    assert sub.cycle_end == clock.utc_now() + timedelta(days=30)
    assert len(points_ledger.grants) == 1
    grant = points_ledger.grants[0]
    assert grant["amount"] == 100
    assert grant["expires_at"] == sub.cycle_end
    assert grant["idempotency_key"].startswith("membership:grant:")
    fetched = await queries.get_subscription(subject_type=SUBJECT[0], subject_id=SUBJECT[1])
    assert fetched is not None and fetched.id == sub.id


async def test_subscribe_rejects_unknown_subject(
    ctx: CommandContext, points_ledger: RecordingPointsLedger
) -> None:
    with pytest.raises(KernelError) as excinfo:
        await SubscribeLevel(ctx)(subscribe_input(subject_id="ghost"))
    assert excinfo.value.code == "membership.subject_not_found"
    assert points_ledger.grants == []


async def test_subscribe_rejects_unknown_level(
    ctx: CommandContext, points_ledger: RecordingPointsLedger
) -> None:
    with pytest.raises(KernelError) as excinfo:
        await SubscribeLevel(ctx)(subscribe_input(level_key="gold"))
    assert excinfo.value.code == "membership.unknown_level"
    assert points_ledger.grants == []


async def test_subscribe_same_level_active_is_idempotent(
    ctx: CommandContext, points_ledger: RecordingPointsLedger
) -> None:
    first = await SubscribeLevel(ctx)(subscribe_input())
    second = await SubscribeLevel(ctx)(subscribe_input())
    assert second.id == first.id
    assert second.cycle_start == first.cycle_start
    assert len(points_ledger.grants) == 1


async def test_subscribe_switches_level_ends_previous_cycle(
    ctx: CommandContext, clock: Any, points_ledger: RecordingPointsLedger
) -> None:
    first = await SubscribeLevel(ctx)(subscribe_input())
    second = await SubscribeLevel(ctx)(subscribe_input(level_key="pro", idempotency_key="sub-2"))
    assert second.id == first.id
    assert second.level_key == "pro"
    assert second.granted_points == 500
    assert second.renewal_count == 1
    assert len(points_ledger.grants) == 2
    # the basic grant keeps its own expiry (cycle_end of the first cycle)
    assert points_ledger.grants[0]["expires_at"] == first.cycle_end


# --- renew -----------------------------------------------------------------


async def test_renew_advances_cycle_and_grants_again(
    ctx: CommandContext, clock: Any, points_ledger: RecordingPointsLedger
) -> None:
    sub = await SubscribeLevel(ctx)(subscribe_input())
    clock.advance(timedelta(days=31))
    renewed = await RenewSubscription(ctx)(
        RenewInput(subscription_id=sub.id, idempotency_key="renew-1")
    )
    assert renewed.status == "active"
    assert renewed.renewal_count == 1
    assert renewed.granted_points == 200
    assert renewed.cycle_start == clock.utc_now()
    assert renewed.cycle_end == clock.utc_now() + timedelta(days=30)
    assert len(points_ledger.grants) == 2
    assert points_ledger.grants[1]["expires_at"] == renewed.cycle_end


async def test_renew_before_cycle_end_is_rejected(
    ctx: CommandContext, points_ledger: RecordingPointsLedger
) -> None:
    sub = await SubscribeLevel(ctx)(subscribe_input())
    with pytest.raises(KernelError) as excinfo:
        await RenewSubscription(ctx)(RenewInput(subscription_id=sub.id, idempotency_key="renew-1"))
    assert excinfo.value.code == "membership.cycle_not_over"
    assert len(points_ledger.grants) == 1


async def test_renew_blocked_when_level_forbids(
    ctx: CommandContext, clock: Any, points_ledger: RecordingPointsLedger
) -> None:
    sub = await SubscribeLevel(ctx)(subscribe_input(level_key="pro"))
    clock.advance(timedelta(days=31))
    with pytest.raises(KernelError) as excinfo:
        await RenewSubscription(ctx)(RenewInput(subscription_id=sub.id, idempotency_key="renew-1"))
    assert excinfo.value.code == "membership.renewal_not_allowed"


# --- cancel / terminate / expire -------------------------------------------


async def test_cancel_keeps_cycle_until_end(
    ctx: CommandContext, queries: MembershipQueries
) -> None:
    sub = await SubscribeLevel(ctx)(subscribe_input())
    cancelled = await CancelSubscription(ctx)(
        CancelInput(subscription_id=sub.id, reason="no thanks")
    )
    assert cancelled.status == "active"
    assert cancelled.auto_renew is False
    assert cancelled.cancelled_at is not None


async def test_terminate_requires_permission_and_ends_cycle(
    ctx: CommandContext,
    uow_factory: UoWFactory,
    clock: Any,
    levels: MembershipLevelRegistry,
    subject_exists: SubjectExistsPort,
    points_ledger: RecordingPointsLedger,
    schema_registry: EventSchemaRegistry,
) -> None:
    restricted = CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        levels=levels,
        subject_exists=subject_exists,
        points_ledger=points_ledger,
        permissions=frozenset(),
    )
    with pytest.raises(KernelError) as excinfo:
        await TerminateSubscription(restricted)(
            TerminateInput(subscription_id=str(uuid.uuid4()), reason="x")
        )
    assert excinfo.value.code == "membership.forbidden"


async def test_expire_converges_ended_cycles(
    ctx: CommandContext, clock: Any, queries: MembershipQueries
) -> None:
    sub = await SubscribeLevel(ctx)(subscribe_input())
    clock.advance(timedelta(days=31))
    expired = await ExpireSubscription(ctx)()
    assert len(expired) == 1
    assert expired[0].id == sub.id
    assert expired[0].status == "expired"
    fetched = await queries.get_subscription(subject_type=SUBJECT[0], subject_id=SUBJECT[1])
    assert fetched is not None and fetched.status == "expired"
    # a second sweep finds nothing
    assert await ExpireSubscription(ctx)() == []


async def test_expire_does_not_touch_active_cycles(ctx: CommandContext, clock: Any) -> None:
    await SubscribeLevel(ctx)(subscribe_input())
    clock.advance(timedelta(days=10))
    assert await ExpireSubscription(ctx)() == []


# --- records & diagnostics --------------------------------------------------


async def test_renewal_records_track_grants(
    ctx: CommandContext, clock: Any, uow_factory: UoWFactory, queries: MembershipQueries
) -> None:
    sub = await SubscribeLevel(ctx)(subscribe_input())
    clock.advance(timedelta(days=31))
    await RenewSubscription(ctx)(RenewInput(subscription_id=sub.id, idempotency_key="renew-1"))
    records = await queries.list_renewal_records(subscription_id=sub.id, page=1, size=10)
    assert records.total == 2
    assert records.items[0].granted_points == 100
    assert records.items[0].points_source_id.startswith("membership:")
    async with uow_factory() as uow:
        rows = (await uow.session.execute(select(MembershipRenewalRecord))).scalars().all()
    assert len(rows) == 2


async def test_diagnostics_report_only(
    ctx: CommandContext,
    clock: Any,
    levels: MembershipLevelRegistry,
    uow_factory: UoWFactory,
    schema_registry: EventSchemaRegistry,
) -> None:
    from inc.capabilities.membership.models import MembershipLevel

    async with uow_factory() as uow:
        for spec in levels.specs():
            uow.session.add(
                MembershipLevel(
                    level_key=spec.key,
                    display_name=spec.display_name,
                    tier_rank=spec.tier_rank,
                    status="active",
                    cycle_days=spec.cycle_days,
                    grant_points=spec.grant_points,
                    renewal_allowed=spec.renewal_allowed,
                )
            )
        await uow.commit()
    diagnostics = MembershipDiagnostics(uow_factory=uow_factory, levels=levels, clock=clock)
    results = await diagnostics.run()
    codes = {r.code: r.status.value for r in results}
    assert codes["membership.active_overdue"] == "ok"
    assert codes["membership.missing_grant_record"] == "ok"
    assert codes["membership.level_drift"] == "ok"


async def test_level_drift_is_reported(
    ctx: CommandContext, clock: Any, levels: MembershipLevelRegistry, uow_factory: UoWFactory
) -> None:
    diagnostics = MembershipDiagnostics(uow_factory=uow_factory, levels=levels, clock=clock)
    results = await diagnostics.run()
    codes = {r.code: r.status.value for r in results}
    assert codes["membership.level_drift"] == "degraded"

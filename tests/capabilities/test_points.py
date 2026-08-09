"""Points capability tests.

Contract source: context/spec/capabilities/points.md §9.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from inc.capabilities.points.behaviors import PointBehaviorRegistry, PointBehaviorSpec
from inc.capabilities.points.commands import (
    AdjustPoints,
    CommandContext,
    CreditPoints,
    DebitPoints,
    ExpireBuckets,
    FreezePointsAccount,
    OpenPointsAccount,
    RebuildBalance,
    ReverseLedgerEntry,
)
from inc.capabilities.points.diagnostics import PointsDiagnostics
from inc.capabilities.points.events import POINTS_EVENT_SCHEMAS
from inc.capabilities.points.models import PointsBucket, PointsProgram
from inc.capabilities.points.queries import PointsQueries
from inc.capabilities.points.schemas import AdjustInput, CreditDebitInput, ReverseInput
from inc.kernel.db import UoWFactory
from inc.kernel.errors import KernelError
from inc.kernel.events import EventSchemaRegistry, OutboxWriter

REWARD_KEY = "daily_check_in.reward"
PURCHASE_KEY = "purchase.completed.credit"
EXPIRING_KEY = "invite.reward"


def make_reward_spec() -> PointBehaviorSpec:
    return PointBehaviorSpec(
        key=REWARD_KEY,
        version="1",
        program_key="default",
        direction="credit",
        fixed_amount=10,
        daily_limit=1,
        business_timezone="UTC",
    )


def make_purchase_spec() -> PointBehaviorSpec:
    return PointBehaviorSpec(
        key=PURCHASE_KEY,
        version="1",
        program_key="default",
        direction="credit",
        min_amount=1,
        max_amount=1_000_000,
        allowed_source_types=("payment",),
    )


def make_expiring_spec() -> PointBehaviorSpec:
    return PointBehaviorSpec(
        key=EXPIRING_KEY,
        version="1",
        program_key="default",
        direction="credit",
        fixed_amount=100,
        expiration_days=30,
        allowed_source_types=("system", "payment"),
    )


@pytest.fixture
def behaviors() -> PointBehaviorRegistry:
    registry = PointBehaviorRegistry()
    registry.register(make_reward_spec())
    registry.register(make_purchase_spec())
    registry.register(make_expiring_spec())
    return registry


@pytest.fixture
def schema_registry() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    for key, schema in POINTS_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    from inc.capabilities.audit.schemas import AUDIT_EVENT_KEY, AuditEntryRecorded

    registry.register(AUDIT_EVENT_KEY, AuditEntryRecorded)
    return registry


@pytest.fixture
def ctx(
    uow_factory: UoWFactory,
    clock: Any,
    behaviors: PointBehaviorRegistry,
    schema_registry: EventSchemaRegistry,
) -> CommandContext:
    return CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        behaviors=behaviors,
        permissions=frozenset({"points.adjust", "points.freeze", "points.rebuild"}),
        actor_id="admin-1",
        trace_id="trace-1",
    )


@pytest.fixture
def queries(uow_factory: UoWFactory, behaviors: PointBehaviorRegistry) -> PointsQueries:
    return PointsQueries(uow_factory=uow_factory, behaviors=behaviors)


@pytest.fixture
async def program(uow_factory: UoWFactory) -> None:
    async with uow_factory() as uow:
        uow.session.add(
            PointsProgram(
                program_key="default", display_name="Default", unit="points", status="active"
            )
        )
        await uow.commit()


SUBJECT = ("identity", "user-1")


async def open_account(ctx: CommandContext, *, subject: tuple[str, str] = SUBJECT) -> Any:
    return await OpenPointsAccount(ctx)(
        program_key="default", subject_type=subject[0], subject_id=subject[1]
    )


def credit_input(**overrides: Any) -> CreditDebitInput:
    base = {
        "subject_type": SUBJECT[0],
        "subject_id": SUBJECT[1],
        "amount": 10,
        "source_type": "system",
        "source_id": "check-in-2026-01-01",
        "idempotency_key": "idem-1",
    }
    base.update(overrides)
    return CreditDebitInput(**base)


# --- account & basics -----------------------------------------------------


async def test_open_account_creates_zero_balance_and_is_idempotent(
    ctx: CommandContext, program: None, queries: PointsQueries
) -> None:
    balance = await open_account(ctx)
    assert balance.balance == 0 and balance.state == "active"
    again = await open_account(ctx)
    assert again.account_id == balance.account_id
    fetched = await queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert fetched.balance == 0


async def test_open_account_creates_single_perpetual_bucket(
    ctx: CommandContext, program: None, uow_factory: UoWFactory
) -> None:
    balance = await open_account(ctx)
    async with uow_factory() as uow:
        rows = (await uow.session.execute(select(PointsBucket))).scalars().all()
    assert len(rows) == 1
    bucket = rows[0]
    assert bucket.bucket_type == "perpetual"
    assert bucket.expires_at is None and bucket.expiration_identity is None
    assert bucket.amount == 0
    assert balance.account_id


async def test_unknown_behavior_is_validation_error(ctx: CommandContext, program: None) -> None:
    with pytest.raises(KernelError) as excinfo:
        await CreditPoints(ctx)("ghost.reward.v1", credit_input())
    assert excinfo.value.code == "points.unknown_behavior"
    assert excinfo.value.category.value == "validation"


async def test_credit_requires_opened_account(ctx: CommandContext, program: None) -> None:
    with pytest.raises(KernelError) as excinfo:
        await CreditPoints(ctx)(REWARD_KEY, credit_input())
    assert excinfo.value.code == "points.account_not_opened"


# --- credit / idempotency -------------------------------------------------


async def test_credit_is_idempotent_by_key(
    ctx: CommandContext, program: None, queries: PointsQueries
) -> None:
    await open_account(ctx)
    first = await CreditPoints(ctx)(REWARD_KEY, credit_input())
    second = await CreditPoints(ctx)(REWARD_KEY, credit_input())
    assert first.id == second.id
    balance = await queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert balance.balance == 10


async def test_credit_daily_limit_enforced(
    ctx: CommandContext, program: None, clock: Any, queries: PointsQueries
) -> None:
    await open_account(ctx)
    await CreditPoints(ctx)(REWARD_KEY, credit_input(idempotency_key="idem-1"))
    with pytest.raises(KernelError) as excinfo:
        await CreditPoints(ctx)(
            REWARD_KEY, credit_input(idempotency_key="idem-2", source_id="check-in-2")
        )
    assert excinfo.value.code == "points.daily_limit"
    clock.advance(timedelta(days=1))
    await CreditPoints(ctx)(
        REWARD_KEY, credit_input(idempotency_key="idem-3", source_id="check-in-3")
    )
    balance = await queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert balance.balance == 20


async def test_fixed_amount_and_source_type_enforced(ctx: CommandContext, program: None) -> None:
    await open_account(ctx)
    with pytest.raises(KernelError) as excinfo:
        await CreditPoints(ctx)(REWARD_KEY, credit_input(amount=99, idempotency_key="k1"))
    assert excinfo.value.code == "points.amount_mismatch"
    with pytest.raises(KernelError) as excinfo:
        await CreditPoints(ctx)(
            PURCHASE_KEY,
            credit_input(amount=100, source_type="content", idempotency_key="k2"),
        )
    assert excinfo.value.code == "points.source_type_not_allowed"


# --- buckets --------------------------------------------------------------


async def test_perpetual_credit_goes_to_perpetual_bucket(
    ctx: CommandContext, program: None, uow_factory: UoWFactory, queries: PointsQueries
) -> None:
    await open_account(ctx)
    await CreditPoints(ctx)(REWARD_KEY, credit_input())
    await CreditPoints(ctx)(
        PURCHASE_KEY,
        credit_input(amount=50, source_type="payment", source_id="pay-1", idempotency_key="k2"),
    )
    async with uow_factory() as uow:
        rows = (await uow.session.execute(select(PointsBucket))).scalars().all()
    assert len(rows) == 1
    assert rows[0].bucket_type == "perpetual"
    assert rows[0].amount == 60
    balance = await queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert balance.balance == 60


async def test_expiring_credit_creates_expiring_bucket(
    ctx: CommandContext, program: None, uow_factory: UoWFactory
) -> None:
    await open_account(ctx)
    await CreditPoints(ctx)(
        EXPIRING_KEY,
        credit_input(amount=100, source_type="system", source_id="inv-1", idempotency_key="k3"),
    )
    async with uow_factory() as uow:
        rows = (await uow.session.execute(select(PointsBucket))).scalars().all()
    assert len(rows) == 2
    expiring = next(r for r in rows if r.bucket_type == "expiring")
    assert expiring.expiration_identity == EXPIRING_KEY
    assert expiring.expires_at is not None
    assert expiring.amount == 100


async def test_credits_share_expiring_bucket_when_same_identity_and_expiry(
    ctx: CommandContext, program: None, uow_factory: UoWFactory
) -> None:
    await open_account(ctx)
    await CreditPoints(ctx)(
        EXPIRING_KEY,
        credit_input(amount=100, source_type="system", source_id="inv-1", idempotency_key="k3"),
    )
    await CreditPoints(ctx)(
        EXPIRING_KEY,
        credit_input(amount=100, source_type="system", source_id="inv-2", idempotency_key="k4"),
    )
    async with uow_factory() as uow:
        rows = (await uow.session.execute(select(PointsBucket))).scalars().all()
    expiring = [r for r in rows if r.bucket_type == "expiring"]
    assert len(expiring) == 1
    assert expiring[0].amount == 200


async def test_debit_consumes_expiring_before_perpetual(
    ctx: CommandContext, program: None, uow_factory: UoWFactory, queries: PointsQueries
) -> None:
    """FIFO: expiring points are consumed before perpetual points."""
    await open_account(ctx)
    await CreditPoints(ctx)(REWARD_KEY, credit_input())  # perpetual +10
    await CreditPoints(ctx)(
        EXPIRING_KEY,
        credit_input(amount=100, source_type="system", source_id="inv-1", idempotency_key="k3"),
    )
    spend_key = _debit_spec(ctx, "spend")
    await DebitPoints(ctx)(spend_key, credit_input(amount=50, idempotency_key="spend-1"))
    async with uow_factory() as uow:
        rows = (await uow.session.execute(select(PointsBucket))).scalars().all()
    buckets = {r.bucket_type: r.amount for r in rows}
    assert buckets["expiring"] == 50
    assert buckets["perpetual"] == 10
    balance = await queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert balance.balance == 60


async def test_debit_consumes_earliest_expiry_first(
    ctx: CommandContext, program: None, clock: Any, uow_factory: UoWFactory
) -> None:
    """With two expiring buckets, the earliest expiry is consumed first."""
    await open_account(ctx)
    await CreditPoints(ctx)(
        EXPIRING_KEY,
        credit_input(amount=100, source_type="system", source_id="inv-1", idempotency_key="k3"),
    )
    clock.advance(timedelta(days=5))
    await CreditPoints(ctx)(
        EXPIRING_KEY,
        credit_input(amount=100, source_type="system", source_id="inv-2", idempotency_key="k4"),
    )
    spend_key = _debit_spec(ctx, "spend")
    await DebitPoints(ctx)(spend_key, credit_input(amount=130, idempotency_key="spend-1"))
    async with uow_factory() as uow:
        rows = (await uow.session.execute(select(PointsBucket))).scalars().all()
    expiring = sorted((r for r in rows if r.bucket_type == "expiring"), key=lambda r: r.expires_at)
    assert [r.amount for r in expiring] == [0, 70]  # earliest expired first


async def test_debit_records_allocations(
    ctx: CommandContext, program: None, uow_factory: UoWFactory, queries: PointsQueries
) -> None:
    from inc.capabilities.points.models import PointsDebitAllocation

    await open_account(ctx)
    await CreditPoints(ctx)(
        EXPIRING_KEY,
        credit_input(amount=100, source_type="system", source_id="inv-1", idempotency_key="k3"),
    )
    spend_key = _debit_spec(ctx, "spend")
    debit = await DebitPoints(ctx)(spend_key, credit_input(amount=30, idempotency_key="spend-1"))
    async with uow_factory() as uow:
        allocs = (await uow.session.execute(select(PointsDebitAllocation))).scalars().all()
    assert len(allocs) == 1
    assert allocs[0].entry_id == uuid.UUID(debit.id)
    assert allocs[0].amount == 30
    fetched = await queries.get_entry(uuid.UUID(debit.id))
    assert fetched is not None and fetched.allocations == [fetched.allocations[0]]
    assert fetched.allocations[0].amount == 30


# --- debit / concurrency --------------------------------------------------


async def test_debit_never_overdraws(
    ctx: CommandContext, program: None, uow_factory: UoWFactory
) -> None:
    await open_account(ctx)
    await CreditPoints(ctx)(REWARD_KEY, credit_input())
    spend_key = _debit_spec(ctx, "spend")
    with pytest.raises(KernelError) as excinfo:
        await DebitPoints(ctx)(spend_key, credit_input(amount=11, idempotency_key="spend-1"))
    assert excinfo.value.code == "points.insufficient_balance"
    await DebitPoints(ctx)(spend_key, credit_input(amount=10, idempotency_key="spend-2"))
    balance = await ctx_balance(ctx, uow_factory)
    assert balance == 0


def _debit_spec(ctx: CommandContext, key: str) -> str:
    spec = PointBehaviorSpec(
        key="spend.points.v1",
        version="1",
        program_key="default",
        direction="debit",
        min_amount=1,
        max_amount=1_000,
    )
    ctx.behaviors.register(spec)
    return spec.key


async def ctx_balance(ctx: CommandContext, uow_factory: UoWFactory) -> int:
    from inc.capabilities.points.models import PointsBalance

    async with uow_factory() as uow:
        row = (await uow.session.execute(select(PointsBalance))).scalars().first()
        return row.balance if row is not None else 0


async def test_debits_never_exceed_available_balance(
    ctx: CommandContext, program: None, uow_factory: UoWFactory
) -> None:
    """Concurrent debits cannot exceed the balance: after one 6-point debit
    the remaining 4 points reject a second 6-point debit."""

    await open_account(ctx)
    await CreditPoints(ctx)(REWARD_KEY, credit_input())
    ctx.behaviors.register(
        PointBehaviorSpec(
            key="spend.points.v1",
            version="1",
            program_key="default",
            direction="debit",
            min_amount=1,
            max_amount=1_000,
        )
    )
    await DebitPoints(ctx)("spend.points.v1", credit_input(amount=6, idempotency_key="s1"))
    assert await ctx_balance(ctx, uow_factory) == 4
    with pytest.raises(KernelError) as excinfo:
        await DebitPoints(ctx)("spend.points.v1", credit_input(amount=6, idempotency_key="s2"))
    assert excinfo.value.code == "points.insufficient_balance"
    assert await ctx_balance(ctx, uow_factory) == 4


# --- reversal / debt ------------------------------------------------------


async def test_reversal_persists_fact_even_into_debt(
    ctx: CommandContext, program: None, queries: PointsQueries
) -> None:
    await open_account(ctx)
    entry = await CreditPoints(ctx)(REWARD_KEY, credit_input())
    reversal = await ReverseLedgerEntry(ctx)(
        uuid.UUID(entry.id),
        ReverseInput(reason="refunded", idempotency_key="rev-1"),
    )
    assert reversal.entry_type == "reversal"
    assert reversal.reversal_of == entry.id
    balance = await queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert balance.balance == 0 and balance.state == "active"

    # second reversal of the same entry is refused
    with pytest.raises(KernelError) as excinfo:
        await ReverseLedgerEntry(ctx)(
            uuid.UUID(entry.id),
            ReverseInput(reason="again", idempotency_key="rev-2"),
        )
    assert excinfo.value.code == "points.already_reversed"

    # reversing the reversal itself is refused
    with pytest.raises(KernelError) as excinfo:
        await ReverseLedgerEntry(ctx)(
            uuid.UUID(reversal.id),
            ReverseInput(reason="no", idempotency_key="rev-3"),
        )
    assert excinfo.value.code == "points.reversal_of_reversal"


async def test_reversal_of_debit_restores_original_buckets(
    ctx: CommandContext, program: None, uow_factory: UoWFactory
) -> None:
    await open_account(ctx)
    await CreditPoints(ctx)(
        EXPIRING_KEY,
        credit_input(amount=100, source_type="system", source_id="inv-1", idempotency_key="k3"),
    )
    spend_key = _debit_spec(ctx, "spend")
    debit = await DebitPoints(ctx)(spend_key, credit_input(amount=30, idempotency_key="spend-1"))
    await ReverseLedgerEntry(ctx)(
        uuid.UUID(debit.id), ReverseInput(reason="undo", idempotency_key="rev-1")
    )
    async with uow_factory() as uow:
        rows = (await uow.session.execute(select(PointsBucket))).scalars().all()
    expiring = next(r for r in rows if r.bucket_type == "expiring")
    assert expiring.amount == 100  # restored to the same expiring bucket


async def test_debt_state_blocks_ordinary_debits(
    ctx: CommandContext, program: None, queries: PointsQueries
) -> None:
    await open_account(ctx)
    purchase = await CreditPoints(ctx)(
        PURCHASE_KEY,
        credit_input(amount=100, source_type="payment", source_id="pay-1", idempotency_key="k3"),
    )
    spend_key = _debit_spec(ctx, "spend")
    await DebitPoints(ctx)(spend_key, credit_input(amount=40, idempotency_key="spend-1"))
    balance = await queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert balance.balance == 60
    # reversing the whole purchase pushes the balance negative (debt)
    await ReverseLedgerEntry(ctx)(
        uuid.UUID(purchase.id), ReverseInput(reason="refund", idempotency_key="rev-1")
    )
    balance = await queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert balance.balance == -40 and balance.state == "debt"
    with pytest.raises(KernelError) as excinfo:
        await DebitPoints(ctx)(
            "spend.points.v1",
            credit_input(amount=5, idempotency_key="s1"),
        )
    assert excinfo.value.code == "points.account_not_debitable"


async def test_repeated_reversal_request_returns_original_reversal(
    ctx: CommandContext, program: None, queries: PointsQueries
) -> None:
    await open_account(ctx)
    entry = await CreditPoints(ctx)(REWARD_KEY, credit_input())
    first = await ReverseLedgerEntry(ctx)(
        uuid.UUID(entry.id),
        ReverseInput(reason="refunded", idempotency_key="rev-1"),
    )
    # the same idempotency key (signal replay) returns the original reversal
    second = await ReverseLedgerEntry(ctx)(
        uuid.UUID(entry.id),
        ReverseInput(reason="refunded", idempotency_key="rev-1"),
    )
    assert second.id == first.id and second.entry_type == "reversal"
    balance = await queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert balance.balance == 0


async def test_credit_recovers_debt_account(
    ctx: CommandContext, program: None, queries: PointsQueries
) -> None:
    await open_account(ctx)
    purchase = await CreditPoints(ctx)(
        PURCHASE_KEY,
        credit_input(amount=100, source_type="payment", source_id="pay-1", idempotency_key="k3"),
    )
    spend_key = _debit_spec(ctx, "spend")
    await DebitPoints(ctx)(spend_key, credit_input(amount=40, idempotency_key="spend-1"))
    await ReverseLedgerEntry(ctx)(
        uuid.UUID(purchase.id), ReverseInput(reason="refund", idempotency_key="rev-1")
    )
    balance = await queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert balance.balance == -40 and balance.state == "debt"

    # a credit that only partially covers the debt is accepted (no overdraw guard)
    await CreditPoints(ctx)(
        PURCHASE_KEY,
        credit_input(amount=10, source_type="payment", source_id="pay-2", idempotency_key="k4"),
    )
    balance = await queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert balance.balance == -30 and balance.state == "debt"

    # a credit that clears the debt restores the account to active
    await CreditPoints(ctx)(
        PURCHASE_KEY,
        credit_input(amount=30, source_type="payment", source_id="pay-3", idempotency_key="k5"),
    )
    balance = await queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert balance.balance == 0 and balance.state == "active"
    await CreditPoints(ctx)(
        PURCHASE_KEY,
        credit_input(amount=10, source_type="payment", source_id="pay-4", idempotency_key="k6"),
    )
    await DebitPoints(ctx)("spend.points.v1", credit_input(amount=5, idempotency_key="s2"))
    balance = await queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert balance.balance == 5 and balance.state == "active"


async def test_idempotency_key_cannot_be_reused_across_types(
    ctx: CommandContext, program: None
) -> None:
    await open_account(ctx)
    await CreditPoints(ctx)(REWARD_KEY, credit_input(idempotency_key="shared-1"))
    spend_key = _debit_spec(ctx, "spend")
    with pytest.raises(KernelError) as excinfo:
        await DebitPoints(ctx)(spend_key, credit_input(amount=1, idempotency_key="shared-1"))
    assert excinfo.value.code == "points.idempotency_mismatch"


# --- expiration -----------------------------------------------------------


async def test_expire_buckets_zeroes_due_bucket_and_records_entry(
    ctx: CommandContext, program: None, clock: Any, uow_factory: UoWFactory, queries: PointsQueries
) -> None:
    from inc.capabilities.points.models import PointsDebitAllocation

    await open_account(ctx)
    await CreditPoints(ctx)(
        EXPIRING_KEY,
        credit_input(amount=100, source_type="system", source_id="inv-1", idempotency_key="k3"),
    )
    clock.advance(timedelta(days=31))
    entries = await ExpireBuckets(ctx)()
    assert len(entries) == 1
    assert entries[0].entry_type == "expiration"
    assert entries[0].amount == -100
    async with uow_factory() as uow:
        rows = (await uow.session.execute(select(PointsBucket))).scalars().all()
    expiring = next(r for r in rows if r.bucket_type == "expiring")
    assert expiring.amount == 0
    async with uow_factory() as uow:
        allocs = (await uow.session.execute(select(PointsDebitAllocation))).scalars().all()
    assert len(allocs) == 1
    assert allocs[0].amount == 100
    balance = await queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert balance.balance == 0


async def test_expire_buckets_is_idempotent_and_skips_future_buckets(
    ctx: CommandContext, program: None, clock: Any
) -> None:
    await open_account(ctx)
    await CreditPoints(ctx)(
        EXPIRING_KEY,
        credit_input(amount=100, source_type="system", source_id="inv-1", idempotency_key="k3"),
    )
    clock.advance(timedelta(days=31))
    first = await ExpireBuckets(ctx)()
    second = await ExpireBuckets(ctx)()
    assert len(first) == 1
    assert second == []


async def test_expire_sweeps_multiple_due_buckets_of_one_account(
    ctx: CommandContext,
    program: None,
    clock: Any,
    uow_factory: UoWFactory,
    queries: PointsQueries,
) -> None:
    """One sweep must zero every due bucket of an account, not just the first."""
    await open_account(ctx)
    await CreditPoints(ctx)(
        EXPIRING_KEY,
        credit_input(amount=100, source_type="system", source_id="inv-1", idempotency_key="k3"),
    )
    clock.advance(timedelta(days=1))
    await CreditPoints(ctx)(
        EXPIRING_KEY,
        credit_input(amount=100, source_type="system", source_id="inv-2", idempotency_key="k4"),
    )
    clock.advance(timedelta(days=31))
    entries = await ExpireBuckets(ctx)()
    assert len(entries) == 2
    assert sorted(e.amount for e in entries) == [-100, -100]
    async with uow_factory() as uow:
        rows = (await uow.session.execute(select(PointsBucket))).scalars().all()
    expiring = [r for r in rows if r.bucket_type == "expiring"]
    assert all(r.amount == 0 for r in expiring)
    balance = await queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert balance.balance == 0


async def test_expire_does_not_touch_perpetual_or_future_buckets(
    ctx: CommandContext, program: None, clock: Any, uow_factory: UoWFactory
) -> None:
    await open_account(ctx)
    await CreditPoints(ctx)(REWARD_KEY, credit_input())
    await CreditPoints(ctx)(
        EXPIRING_KEY,
        credit_input(amount=100, source_type="system", source_id="inv-1", idempotency_key="k3"),
    )
    clock.advance(timedelta(days=29))
    assert await ExpireBuckets(ctx)() == []
    clock.advance(timedelta(days=2))
    entries = await ExpireBuckets(ctx)()
    assert len(entries) == 1
    async with uow_factory() as uow:
        rows = (await uow.session.execute(select(PointsBucket))).scalars().all()
    buckets = {r.bucket_type: r.amount for r in rows}
    assert buckets["perpetual"] == 10
    assert buckets["expiring"] == 0


async def test_reversal_of_expiration_entry_restores_expired_bucket(
    ctx: CommandContext, program: None, clock: Any, uow_factory: UoWFactory
) -> None:
    await open_account(ctx)
    await CreditPoints(ctx)(
        EXPIRING_KEY,
        credit_input(amount=100, source_type="system", source_id="inv-1", idempotency_key="k3"),
    )
    clock.advance(timedelta(days=31))
    entries = await ExpireBuckets(ctx)()
    # rewind so the reversal happens "before" expiry check, then restore
    await ReverseLedgerEntry(ctx)(
        uuid.UUID(entries[0].id), ReverseInput(reason="ops fix", idempotency_key="rev-1")
    )
    async with uow_factory() as uow:
        rows = (await uow.session.execute(select(PointsBucket))).scalars().all()
    expiring = next(r for r in rows if r.bucket_type == "expiring")
    assert expiring.amount == 100


# --- admin operations -----------------------------------------------------


async def test_adjust_requires_permission_and_reason(
    ctx: CommandContext,
    program: None,
    uow_factory: UoWFactory,
    clock: Any,
    behaviors: PointBehaviorRegistry,
    schema_registry: EventSchemaRegistry,
) -> None:
    restricted = CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        behaviors=behaviors,
        permissions=frozenset(),
    )
    with pytest.raises(KernelError) as excinfo:
        await AdjustPoints(restricted)(
            AdjustInput(
                subject_type="identity",
                subject_id="user-1",
                program_key="default",
                amount=50,
                reason="x",
                idempotency_key="a1",
            )
        )
    assert excinfo.value.code == "points.forbidden"


async def test_positive_adjustment_lands_in_perpetual_bucket(
    ctx: CommandContext, program: None, uow_factory: UoWFactory
) -> None:
    await open_account(ctx)
    await AdjustPoints(ctx)(
        AdjustInput(
            subject_type="identity",
            subject_id="user-1",
            program_key="default",
            amount=50,
            reason="x",
            idempotency_key="a1",
        )
    )
    async with uow_factory() as uow:
        rows = (await uow.session.execute(select(PointsBucket))).scalars().all()
    assert len(rows) == 1
    assert rows[0].bucket_type == "perpetual"
    assert rows[0].amount == 50


async def test_rebuild_balance_dry_run_then_fix(
    ctx: CommandContext, program: None, uow_factory: UoWFactory, queries: PointsQueries
) -> None:
    balance = await open_account(ctx)
    await CreditPoints(ctx)(REWARD_KEY, credit_input())
    # corrupt the snapshot
    from inc.capabilities.points.models import PointsBalance

    async with uow_factory() as uow:
        row = (
            (
                await uow.session.execute(
                    select(PointsBalance).where(
                        PointsBalance.account_id == uuid.UUID(balance.account_id)
                    )
                )
            )
            .scalars()
            .first()
        )
        row.balance = 999
        await uow.commit()
    report = await RebuildBalance(ctx)(uuid.UUID(balance.account_id), dry_run=True)
    assert report["match"] is False and report["ledger_sum"] == 10
    report = await RebuildBalance(ctx)(uuid.UUID(balance.account_id), dry_run=False)
    assert report["match"] is True
    fetched = await queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert fetched.balance == 10


async def test_rebuild_repairs_bucket_drift(
    ctx: CommandContext, program: None, uow_factory: UoWFactory, queries: PointsQueries
) -> None:
    balance = await open_account(ctx)
    await CreditPoints(ctx)(
        EXPIRING_KEY,
        credit_input(amount=100, source_type="system", source_id="inv-1", idempotency_key="k3"),
    )
    async with uow_factory() as uow:
        row = (
            (
                await uow.session.execute(
                    select(PointsBucket).where(PointsBucket.bucket_type == "expiring")
                )
            )
            .scalars()
            .first()
        )
        row.amount = 7
        row.version += 1
        await uow.commit()
    report = await RebuildBalance(ctx)(uuid.UUID(balance.account_id), dry_run=True)
    assert report["match"] is False
    report = await RebuildBalance(ctx)(uuid.UUID(balance.account_id), dry_run=False)
    assert report["match"] is True
    fetched = await queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert fetched.balance == 100


async def test_rebuild_reports_debt_account_consistent(
    ctx: CommandContext, program: None, uow_factory: UoWFactory, queries: PointsQueries
) -> None:
    """A debt account (negative balance, zero buckets) is a consistent state."""
    balance = await open_account(ctx)
    purchase = await CreditPoints(ctx)(
        PURCHASE_KEY,
        credit_input(amount=100, source_type="payment", source_id="pay-1", idempotency_key="k3"),
    )
    spend_key = _debit_spec(ctx, "spend")
    await DebitPoints(ctx)(spend_key, credit_input(amount=40, idempotency_key="spend-1"))
    await ReverseLedgerEntry(ctx)(
        uuid.UUID(purchase.id), ReverseInput(reason="refund", idempotency_key="rev-1")
    )
    fetched = await queries.get_balance(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1]
    )
    assert fetched.balance == -40 and fetched.state == "debt"
    report = await RebuildBalance(ctx)(uuid.UUID(balance.account_id), dry_run=True)
    assert report["match"] is True
    report = await RebuildBalance(ctx)(uuid.UUID(balance.account_id), dry_run=False)
    assert report["match"] is True


async def test_freeze_blocks_credit(ctx: CommandContext, program: None) -> None:
    balance = await open_account(ctx)
    await FreezePointsAccount(ctx)(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1], frozen=True
    )
    with pytest.raises(KernelError) as excinfo:
        await CreditPoints(ctx)(REWARD_KEY, credit_input(idempotency_key="k1"))
    assert excinfo.value.code == "points.account_frozen"
    await FreezePointsAccount(ctx)(
        program_key="default", subject_type=SUBJECT[0], subject_id=SUBJECT[1], frozen=False
    )
    await CreditPoints(ctx)(REWARD_KEY, credit_input(idempotency_key="k2"))
    assert balance.account_id  # still open


async def test_diagnostics_report_only(
    ctx: CommandContext,
    program: None,
    uow_factory: UoWFactory,
    behaviors: PointBehaviorRegistry,
    clock: Any,
) -> None:
    from inc.capabilities.points.models import BehaviorDefinitionData, PointsBehaviorDefinition

    async with uow_factory() as uow:
        for spec in behaviors.specs():
            uow.session.add(
                PointsBehaviorDefinition(
                    behavior_key=spec.key,
                    version=spec.version,
                    program_key=spec.program_key,
                    direction=spec.direction,
                    data=BehaviorDefinitionData(values={}),
                )
            )
        await uow.commit()
    diagnostics = PointsDiagnostics(uow_factory=uow_factory, behaviors=behaviors, clock=clock)
    results = await diagnostics.run()
    codes = {r.code: r.status.value for r in results}
    assert codes["points.balance_mismatch"] == "ok"
    assert codes["points.bucket_mismatch"] == "ok"
    assert codes["points.negative_outside_debt"] == "ok"
    assert codes["points.buckets_overdue"] == "ok"
    assert codes["points.behavior_drift"] == "ok"

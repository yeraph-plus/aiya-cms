"""Points commands.

Contract source: context/spec/capabilities/points.md §5.

The ledger is the source of truth; balance is updated atomically with the
entry. Debits consume buckets FIFO by ``expires_at`` (earliest expiring
first) and never overdraw; every consumption records a debit allocation so
reversals restore the exact buckets and balances can be rebuilt from the
ledger. Expiration entries are created by ExpireBuckets and are idempotent
per bucket.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from inc.capabilities.points.behaviors import PointBehaviorRegistry, PointBehaviorSpec
from inc.capabilities.points.constants import DEFAULT_PROGRAM_KEY
from inc.capabilities.points.events import POINTS_EVENT_SCHEMAS
from inc.capabilities.points.models import (
    LedgerMetadata,
    PointsAccount,
    PointsBalance,
    PointsBucket,
    PointsDebitAllocation,
    PointsLedgerEntry,
    PointsProgram,
)
from inc.capabilities.points.schemas import (
    AdjustInput,
    BalanceDTO,
    CreditDebitInput,
    LedgerEntryDTO,
    ReverseInput,
)
from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock

PERMISSION_ADJUST = "points.adjust"
PERMISSION_FREEZE = "points.freeze"
PERMISSION_REBUILD = "points.rebuild"

AUDIT_EVENT_KEY = "audit.entry.recorded.v1"


@dataclass(frozen=True, slots=True)
class CommandContext:
    uow_factory: UoWFactory
    clock: Clock
    outbox: OutboxWriter
    behaviors: PointBehaviorRegistry
    permissions: frozenset[str] = frozenset()
    actor_id: str | None = None
    trace_id: str | None = None


def _forbidden(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.FORBIDDEN, message=message)


def _conflict(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.CONFLICT, message=message)


def _validation(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.VALIDATION, message=message)


def _not_found(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.NOT_FOUND, message=message)


def _require_permission(ctx: CommandContext, key: str) -> None:
    if key not in ctx.permissions:
        raise _forbidden("points.forbidden", f"requires permission {key}")


async def _append_audit(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    action: str,
    target_type: str,
    target_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=AUDIT_EVENT_KEY,
            occurred_at=ctx.clock.utc_now(),
            producer="points",
            aggregate_type="points",
            aggregate_id=target_id,
            trace_id=ctx.trace_id,
            payload={
                "action": action,
                "outcome": "success",
                "occurred_at": ctx.clock.utc_now().isoformat(),
                "actor_type": "user" if ctx.actor_id else None,
                "actor_id": ctx.actor_id,
                "target_type": target_type,
                "target_id": target_id,
                "trace_id": ctx.trace_id,
                "details": details or {},
            },
        ),
    )


def _require_behavior(ctx: CommandContext, key: str) -> PointBehaviorSpec:
    try:
        return ctx.behaviors.require(key)
    except KernelError as exc:
        if exc.code == "points.unknown_behavior":
            raise _validation("points.unknown_behavior", exc.message) from exc
        raise


def _ensure_utc(value: Any) -> Any:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


async def _require_program(uow: UnitOfWork, program_key: str) -> PointsProgram:
    program: PointsProgram | None = (
        (
            await uow.session.execute(
                select(PointsProgram).where(PointsProgram.program_key == program_key)
            )
        )
        .scalars()
        .first()
    )
    if program is None or program.status != "active":
        raise _validation("points.program_inactive", f"program {program_key!r} is not active")
    return program


async def _get_account(
    uow: UnitOfWork, program_id: Any, subject_type: str, subject_id: str
) -> PointsAccount:
    account: PointsAccount | None = (
        (
            await uow.session.execute(
                select(PointsAccount).where(
                    PointsAccount.program_id == program_id,
                    PointsAccount.subject_type == subject_type,
                    PointsAccount.subject_id == subject_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if account is None:
        raise _not_found("points.account_not_opened", "points account is not opened")
    return account


async def _ensure_account(
    ctx: CommandContext,
    uow: UnitOfWork,
    program: PointsProgram,
    subject_type: str,
    subject_id: str,
) -> PointsAccount:
    """Create the account inside the first points write transaction."""

    account: PointsAccount | None = (
        (
            await uow.session.execute(
                select(PointsAccount).where(
                    PointsAccount.program_id == program.id,
                    PointsAccount.subject_type == subject_type,
                    PointsAccount.subject_id == subject_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if account is not None:
        await _bucket_target(uow, account, bucket_type="perpetual")
        return account

    account = PointsAccount(
        program_id=program.id,
        subject_type=subject_type,
        subject_id=subject_id,
        state="active",
        version=1,
    )
    uow.session.add(account)
    try:
        await uow.session.flush()
    except IntegrityError as exc:
        raise _conflict("points.account_exists", "account already exists for this subject") from exc
    uow.session.add(PointsBalance(account_id=account.id, balance=0, version=1))
    await _bucket_target(uow, account, bucket_type="perpetual")
    await _emit(ctx, uow, key="points.account_opened.v1", account=account, program=program)
    return account


async def _get_balance(uow: UnitOfWork, account_id: Any) -> PointsBalance:
    balance: PointsBalance | None = (
        (
            await uow.session.execute(
                select(PointsBalance)
                .where(PointsBalance.account_id == account_id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .first()
    )
    if balance is None:
        raise KernelError(
            code="points.balance_missing",
            category=ErrorCategory.INTERNAL,
            message=f"balance row missing for account {account_id}",
        )
    return balance


async def _get_buckets(uow: UnitOfWork, account_id: Any) -> list[PointsBucket]:
    statement = select(PointsBucket).where(
        PointsBucket.account_id == account_id, PointsBucket.amount > 0
    )
    rows = (await uow.session.execute(statement)).scalars().all()
    return list(rows)


async def _apply_balance(
    uow: UnitOfWork,
    account: PointsAccount,
    *,
    amount: int,
    allow_negative: bool,
) -> int:
    """Atomic balance update; returns the new balance.

    ``allow_negative=False`` guards with ``balance + amount >= 0`` so
    concurrent debits cannot overdraw. ``allow_negative=True`` (credit into
    debt, reversal, admin adjustment) always applies and moves the account
    to debt when the result is negative; a credit that brings the balance
    back to zero or above restores the account to active.
    """

    balance = await _get_balance(uow, account.id)
    new_balance = balance.balance + amount
    if not allow_negative and new_balance < 0:
        raise _conflict("points.insufficient_balance", "balance would go negative")
    statement = (
        update(PointsBalance)
        .where(
            PointsBalance.account_id == account.id,
            PointsBalance.version == balance.version,
        )
        .values(balance=balance.balance + amount, version=PointsBalance.version + 1)
        .execution_options(synchronize_session=False)
    )
    result = await uow.session.execute(statement)
    if result.rowcount == 0:
        raise _conflict("points.balance_conflict", "balance changed concurrently; retry")
    _sync_account_state(uow, account, new_balance)
    return new_balance


def _sync_account_state(uow: UnitOfWork, account: PointsAccount, new_balance: int) -> None:
    if new_balance < 0:
        if account.state != "debt":
            account.state = "debt"
            account.version += 1
            uow.session.add(account)
    elif account.state == "debt":
        account.state = "active"
        account.version += 1
        uow.session.add(account)


async def _bucket_target(
    uow: UnitOfWork,
    account: PointsAccount,
    *,
    bucket_type: str,
    expiration_identity: str | None = None,
    expires_at: Any = None,
) -> PointsBucket:
    """Find or create the bucket for a routing target.

    Perpetual bucket is created at open time; this helper also repairs
    accounts opened before buckets existed. Concurrency is guarded by the
    partial unique index: a raced duplicate creation raises a conflict that
    the caller maps to a retryable error.
    """

    statement = select(PointsBucket).where(
        PointsBucket.account_id == account.id,
        PointsBucket.bucket_type == bucket_type,
    )
    if bucket_type == "expiring":
        statement = statement.where(
            PointsBucket.expiration_identity == expiration_identity,
            PointsBucket.expires_at == expires_at,
        )
    else:
        statement = statement.where(
            PointsBucket.expiration_identity.is_(None), PointsBucket.expires_at.is_(None)
        )
    existing: PointsBucket | None = (await uow.session.execute(statement)).scalars().first()
    if existing is not None:
        return existing
    bucket = PointsBucket(
        account_id=account.id,
        bucket_type=bucket_type,
        expiration_identity=expiration_identity if bucket_type == "expiring" else None,
        expires_at=expires_at if bucket_type == "expiring" else None,
        amount=0,
        version=1,
    )
    uow.session.add(bucket)
    try:
        await uow.session.flush()
    except IntegrityError as exc:
        await uow.session.rollback()
        raise _conflict(
            "points.bucket_conflict", f"bucket raced with another writer for account {account.id}"
        ) from exc
    return bucket


async def _add_to_bucket(
    uow: UnitOfWork, account: PointsAccount, bucket: PointsBucket, amount: int
) -> None:
    result = await uow.session.execute(
        update(PointsBucket)
        .where(
            PointsBucket.id == bucket.id,
            PointsBucket.version == bucket.version,
        )
        .values(amount=PointsBucket.amount + amount, version=PointsBucket.version + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        raise _conflict("points.bucket_conflict", "bucket changed concurrently; retry")
    bucket.amount += amount
    bucket.version += 1


async def _consume_buckets(
    uow: UnitOfWork,
    account: PointsAccount,
    amount: int,
    *,
    allow_negative: bool,
) -> tuple[int, list[tuple[PointsBucket, int]]]:
    """Consume ``amount`` from buckets FIFO (earliest expiry first).

    Returns ``(new_balance, allocations)`` where allocations are
    ``(bucket, consumed)`` pairs. ``allow_negative=False`` refuses to spend
    more than available; the positive balance that exists in buckets is
    always fully consumed first.
    """

    buckets = await _get_buckets(uow, account.id)
    buckets.sort(
        key=lambda b: (
            b.expires_at is None,
            b.expires_at or datetime.min.replace(tzinfo=UTC),
            b.created_at,
        )
    )
    balance = await _get_balance(uow, account.id)
    available = sum(b.amount for b in buckets)
    if amount > available and not allow_negative:
        raise _conflict("points.insufficient_balance", "balance would go negative")
    remaining = amount
    allocations: list[tuple[PointsBucket, int]] = []
    for bucket in buckets:
        if remaining <= 0:
            break
        take = min(bucket.amount, remaining)
        result = await uow.session.execute(
            update(PointsBucket)
            .where(
                PointsBucket.id == bucket.id,
                PointsBucket.version == bucket.version,
                PointsBucket.amount >= take,
            )
            .values(amount=PointsBucket.amount - take, version=PointsBucket.version + 1)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 0:
            raise _conflict("points.bucket_conflict", "bucket changed concurrently; retry")
        bucket.amount -= take
        bucket.version += 1
        allocations.append((bucket, take))
        remaining -= take
    new_balance = balance.balance - amount
    statement = (
        update(PointsBalance)
        .where(
            PointsBalance.account_id == account.id,
            PointsBalance.version == balance.version,
        )
        .values(balance=new_balance, version=PointsBalance.version + 1)
        .execution_options(synchronize_session=False)
    )
    result = await uow.session.execute(statement)
    if result.rowcount == 0:
        raise _conflict("points.balance_conflict", "balance changed concurrently; retry")
    _sync_account_state(uow, account, new_balance)
    return new_balance, allocations


async def _restore_buckets(
    uow: UnitOfWork,
    account: PointsAccount,
    amount: int,
    targets: list[tuple[PointsBucket, int]],
) -> int:
    """Restore ``amount`` to the given buckets (debit/expiration reversal).

    Any balance in debt is paid down first; only the excess returns to the
    original buckets (which may have been emptied or expired meanwhile).
    Amounts that cannot be attributed to the original buckets (debt-covered
    consumption) fall back to the perpetual bucket. Returns the new balance.
    """

    balance = await _get_balance(uow, account.id)
    new_balance = balance.balance + amount
    remaining = amount
    if balance.balance < 0:
        pay_down = min(-balance.balance, amount)
        remaining -= pay_down
    for bucket, capacity in targets:
        if remaining <= 0:
            break
        give = min(capacity, remaining)
        result = await uow.session.execute(
            update(PointsBucket)
            .where(
                PointsBucket.id == bucket.id,
                PointsBucket.version == bucket.version,
            )
            .values(amount=PointsBucket.amount + give, version=PointsBucket.version + 1)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 0:
            raise _conflict("points.bucket_conflict", "bucket changed concurrently; retry")
        bucket.amount += give
        bucket.version += 1
        remaining -= give
    if remaining > 0:
        fallback = await _bucket_target(uow, account, bucket_type="perpetual")
        await _add_to_bucket(uow, account, fallback, remaining)
    statement = (
        update(PointsBalance)
        .where(
            PointsBalance.account_id == account.id,
            PointsBalance.version == balance.version,
        )
        .values(balance=new_balance, version=PointsBalance.version + 1)
        .execution_options(synchronize_session=False)
    )
    result = await uow.session.execute(statement)
    if result.rowcount == 0:
        raise _conflict("points.balance_conflict", "balance changed concurrently; retry")
    _sync_account_state(uow, account, new_balance)
    return new_balance


async def _add_allocations(
    uow: UnitOfWork,
    entry_id: Any,
    allocations: list[tuple[PointsBucket, int]],
) -> None:
    for bucket, amount in allocations:
        uow.session.add(
            PointsDebitAllocation(entry_id=entry_id, bucket_id=bucket.id, amount=amount)
        )


async def _restore_into(
    uow: UnitOfWork,
    account: PointsAccount,
    targets: list[tuple[PointsBucket, int]],
    running_balance: int,
    amount: int,
) -> None:
    """Replay-time restore with the same debt-paydown semantics as runtime."""

    remaining = amount
    if running_balance < 0:
        pay_down = min(-running_balance, amount)
        remaining -= pay_down
    for bucket, capacity in targets:
        if remaining <= 0:
            break
        give = min(capacity, remaining)
        await _add_to_bucket(uow, account, bucket, give)
        remaining -= give
    if remaining > 0:
        fallback = await _bucket_target(uow, account, bucket_type="perpetual")
        await _add_to_bucket(uow, account, fallback, remaining)


async def _entry_allocations(uow: UnitOfWork, entry_id: Any) -> list[tuple[PointsBucket, int]]:
    rows = (
        (
            await uow.session.execute(
                select(PointsDebitAllocation).where(PointsDebitAllocation.entry_id == entry_id)
            )
        )
        .scalars()
        .all()
    )
    targets: list[tuple[PointsBucket, int]] = []
    for row in rows:
        bucket: PointsBucket | None = await uow.session.get(PointsBucket, row.bucket_id)
        if bucket is not None:
            targets.append((bucket, row.amount))
    return targets


async def _emit(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    key: str,
    account: PointsAccount,
    program: PointsProgram,
    **values: Any,
) -> None:
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=key,
            occurred_at=ctx.clock.utc_now(),
            producer="points",
            aggregate_type="points",
            aggregate_id=str(account.id),
            trace_id=ctx.trace_id,
            payload=POINTS_EVENT_SCHEMAS[key]
            .model_validate(
                {
                    "account_id": str(account.id),
                    "program_key": program.program_key,
                    "subject_type": account.subject_type,
                    "subject_id": account.subject_id,
                    **values,
                }
            )
            .model_dump(mode="json"),
        ),
    )


def _to_balance(account: PointsAccount, balance: PointsBalance, program_key: str) -> BalanceDTO:
    return BalanceDTO(
        account_id=str(account.id),
        program_key=program_key,
        subject_type=account.subject_type,
        subject_id=account.subject_id,
        state=account.state,
        balance=balance.balance,
        version=balance.version,
    )


def _to_entry(row: PointsLedgerEntry, program_key: str) -> LedgerEntryDTO:
    return LedgerEntryDTO(
        id=str(row.id),
        account_id=str(row.account_id),
        program_key=program_key,
        amount=row.amount,
        entry_type=row.entry_type,
        behavior_key=row.behavior_key,
        behavior_version=row.behavior_version,
        source_type=row.source_type,
        source_id=row.source_id,
        actor_type=row.actor_type,
        actor_id=row.actor_id,
        metadata=dict(row.entry_metadata.values),
        reversal_of=str(row.reversal_of) if row.reversal_of is not None else None,
        created_at=_ensure_utc(row.created_at),
    )


def _credit_routing(
    spec: PointBehaviorSpec, occurred_at: Any, expires_at: Any = None
) -> tuple[str, str | None, Any | None]:
    """Route a credit to (bucket_type, expiration_identity, expires_at).

    An explicit ``expires_at`` (e.g. membership subscription end) takes
    precedence over the behavior's ``expiration_days``. Without either the
    credit is perpetual.
    """

    if expires_at is not None:
        return "expiring", spec.key, expires_at
    if spec.expiration_days is None:
        return "perpetual", None, None
    expires_at = occurred_at + timedelta(days=spec.expiration_days)
    return "expiring", spec.key, expires_at


class OpenPointsAccount:
    """Open (or return) an account with a zero balance and perpetual bucket."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, *, program_key: str, subject_type: str, subject_id: str
    ) -> BalanceDTO:
        ctx = self._ctx
        async with ctx.uow_factory() as uow:
            program = await _require_program(uow, program_key)
            account = await _ensure_account(ctx, uow, program, subject_type, subject_id)
            balance = await _get_balance(uow, account.id)
            await uow.commit()
            return _to_balance(account, balance, program_key)


class CreditPoints:
    """Idempotent credit under a registered behavior, routed to a bucket."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, behavior_key: str, input_: CreditDebitInput
    ) -> LedgerEntryDTO:
        ctx = self._ctx
        spec = _require_behavior(ctx, behavior_key)
        if spec.direction != "credit":
            raise _validation(
                "points.behavior_direction",
                f"behavior {behavior_key} is {spec.direction}, not credit",
            )
        if input_.source_type not in spec.allowed_source_types:
            raise _validation(
                "points.source_type_not_allowed",
                f"source type {input_.source_type!r} not allowed by {behavior_key}",
            )
        async with ctx.uow_factory() as uow:
            program = await _require_program(uow, spec.program_key)
            existing = await _find_idempotent(uow, program.id, input_.idempotency_key)
            if existing is not None:
                if existing.entry_type != "credit":
                    raise _conflict(
                        "points.idempotency_mismatch",
                        "idempotency key already used by a non-credit entry",
                    )
                return _to_entry(existing, program.program_key)
            account = await _ensure_account(
                ctx, uow, program, input_.subject_type, input_.subject_id
            )
            if account.state == "frozen":
                raise _conflict("points.account_frozen", "points account is frozen")
            await _validate_limits(ctx, uow, spec=spec, account=account, amount=input_.amount)
            occurred_at = ctx.clock.utc_now()
            bucket_type, identity, expires_at = _credit_routing(
                spec, occurred_at, input_.expires_at
            )
            bucket = await _bucket_target(
                uow,
                account,
                bucket_type=bucket_type,
                expiration_identity=identity,
                expires_at=expires_at,
            )
            new_balance = await _apply_balance(
                uow, account, amount=input_.amount, allow_negative=True
            )
            # a credit in debt first pays down the debt; only the excess enters buckets
            before = max(0, new_balance - input_.amount)
            after = max(0, new_balance)
            bucket_delta = after - before
            if bucket_delta > 0:
                await _add_to_bucket(uow, account, bucket, bucket_delta)
            entry = PointsLedgerEntry(
                program_id=program.id,
                account_id=account.id,
                amount=input_.amount,
                entry_type="credit",
                created_at=occurred_at,
                behavior_key=spec.key,
                behavior_version=spec.version,
                source_type=input_.source_type,
                source_id=input_.source_id,
                idempotency_key=input_.idempotency_key,
                actor_type=input_.actor_type,
                actor_id=input_.actor_id or ctx.actor_id,
                entry_metadata=LedgerMetadata(
                    values={
                        "bucket_type": bucket_type,
                        **(
                            {
                                "expiration_identity": identity,
                                "expires_at": expires_at.isoformat() if expires_at else None,
                            }
                            if identity is not None
                            else {}
                        ),
                        **(input_.metadata or {}),
                    }
                ),
            )
            uow.session.add(entry)
            try:
                await uow.session.flush()
            except IntegrityError as exc:
                raise _conflict(
                    "points.duplicate_credit", "a credit with this idempotency key exists"
                ) from exc
            await _emit(
                ctx,
                uow,
                key="points.credited.v1",
                account=account,
                program=program,
                entry_id=str(entry.id),
                amount=entry.amount,
                balance=new_balance,
                behavior_key=spec.key,
                source_type=input_.source_type,
                source_id=input_.source_id,
            )
            await uow.commit()
            return _to_entry(entry, program.program_key)


class DebitPoints:
    """Conditional debit that can never overdraw; consumes buckets FIFO."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, behavior_key: str, input_: CreditDebitInput
    ) -> LedgerEntryDTO:
        ctx = self._ctx
        spec = _require_behavior(ctx, behavior_key)
        if spec.direction != "debit":
            raise _validation(
                "points.behavior_direction",
                f"behavior {behavior_key} is {spec.direction}, not debit",
            )
        async with ctx.uow_factory() as uow:
            program = await _require_program(uow, spec.program_key)
            existing = await _find_idempotent(uow, program.id, input_.idempotency_key)
            if existing is not None:
                if existing.entry_type != "debit":
                    raise _conflict(
                        "points.idempotency_mismatch",
                        "idempotency key already used by a non-debit entry",
                    )
                return _to_entry(existing, program.program_key)
            account = await _ensure_account(
                ctx, uow, program, input_.subject_type, input_.subject_id
            )
            if account.state in ("frozen", "debt"):
                raise _conflict(
                    "points.account_not_debitable", f"points account is {account.state}"
                )
            await _validate_limits(ctx, uow, spec=spec, account=account, amount=input_.amount)
            new_balance, allocations = await _consume_buckets(
                uow, account, input_.amount, allow_negative=False
            )
            entry = PointsLedgerEntry(
                program_id=program.id,
                account_id=account.id,
                amount=-input_.amount,
                entry_type="debit",
                created_at=ctx.clock.utc_now(),
                behavior_key=spec.key,
                behavior_version=spec.version,
                source_type=input_.source_type,
                source_id=input_.source_id,
                idempotency_key=input_.idempotency_key,
                actor_type=input_.actor_type,
                actor_id=input_.actor_id or ctx.actor_id,
                entry_metadata=LedgerMetadata(values=input_.metadata),
            )
            uow.session.add(entry)
            try:
                await uow.session.flush()
            except IntegrityError as exc:
                raise _conflict(
                    "points.duplicate_debit", "a debit with this idempotency key exists"
                ) from exc
            await _add_allocations(uow, entry.id, allocations)
            await _emit(
                ctx,
                uow,
                key="points.debited.v1",
                account=account,
                program=program,
                entry_id=str(entry.id),
                amount=entry.amount,
                balance=new_balance,
                behavior_key=spec.key,
                source_type=input_.source_type,
                source_id=input_.source_id,
            )
            await uow.commit()
            return _to_entry(entry, program.program_key)


async def _find_idempotent(
    uow: UnitOfWork, program_id: Any, idempotency_key: str
) -> PointsLedgerEntry | None:
    row: PointsLedgerEntry | None = (
        (
            await uow.session.execute(
                select(PointsLedgerEntry).where(
                    PointsLedgerEntry.program_id == program_id,
                    PointsLedgerEntry.idempotency_key == idempotency_key,
                )
            )
        )
        .scalars()
        .first()
    )
    return row


class ReverseLedgerEntry:
    """Reverse an entry once; the reversal fact always persists.

    Reversing a debit/expiration restores the exact buckets it consumed;
    reversing a credit/adjustment consumes from buckets FIFO and may push
    the account into debt.
    """

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, entry_id: Any, input_: ReverseInput
    ) -> LedgerEntryDTO:
        ctx = self._ctx
        async with ctx.uow_factory() as uow:
            # Lock the original entry so two concurrent reversals serialize:
            # the second reads the first's reversal after it commits.
            entry: PointsLedgerEntry | None = await uow.session.get(
                PointsLedgerEntry, entry_id, with_for_update=True
            )
            if entry is None:
                raise _not_found("points.entry_not_found", f"entry {entry_id}")
            program: PointsProgram | None = await uow.session.get(PointsProgram, entry.program_id)
            if program is None or not program.allow_admin_reversal:
                raise _conflict("points.reversal_not_allowed", "program forbids reversal")
            if entry.entry_type == "reversal":
                raise _conflict("points.reversal_of_reversal", "cannot reverse a reversal")
            existing = await _find_idempotent(uow, entry.program_id, input_.idempotency_key)
            if existing is not None:
                if existing.entry_type != "reversal":
                    raise _conflict(
                        "points.idempotency_mismatch",
                        "idempotency key already used by a non-reversal entry",
                    )
                return _to_entry(existing, program.program_key)
            already = (
                await uow.session.execute(
                    select(func.count(PointsLedgerEntry.id)).where(
                        PointsLedgerEntry.reversal_of == entry.id
                    )
                )
            ).scalar_one()
            if already:
                raise _conflict("points.already_reversed", "entry is already reversed")
            account: PointsAccount | None = await uow.session.get(PointsAccount, entry.account_id)
            if account is None:
                raise _not_found("points.account_not_found", f"account {entry.account_id}")
            if entry.amount > 0:
                # reversing a credit/adjustment: spend back from buckets
                new_balance, allocations = await _consume_buckets(
                    uow, account, entry.amount, allow_negative=True
                )
                targets = allocations
            else:
                # reversing a debit/expiration: restore the exact buckets
                targets = await _entry_allocations(uow, entry.id)
                new_balance = await _restore_buckets(uow, account, -entry.amount, targets=targets)
            reversal = PointsLedgerEntry(
                program_id=entry.program_id,
                account_id=entry.account_id,
                amount=-entry.amount,
                entry_type="reversal",
                created_at=ctx.clock.utc_now(),
                behavior_key=entry.behavior_key,
                behavior_version=entry.behavior_version,
                source_type=entry.source_type,
                source_id=entry.source_id,
                idempotency_key=input_.idempotency_key,
                actor_type="user",
                actor_id=ctx.actor_id,
                entry_metadata=LedgerMetadata(values={"reason": input_.reason}),
                reversal_of=entry.id,
            )
            uow.session.add(reversal)
            try:
                await uow.session.flush()
            except IntegrityError as exc:
                raise _conflict(
                    "points.duplicate_reversal", "a reversal with this idempotency key exists"
                ) from exc
            if entry.amount > 0:
                await _add_allocations(uow, reversal.id, targets)
            await _emit(
                ctx,
                uow,
                key="points.entry_reversed.v1",
                account=account,
                program=program,
                entry_id=str(entry.id),
                reversal_id=str(reversal.id),
                amount=-entry.amount,
                balance=new_balance,
            )
            await uow.commit()
            return _to_entry(reversal, program.program_key)


class AdjustPoints:
    """Admin-only adjustment with reason, permission and audit.

    Positive adjustments enter the perpetual bucket; negative adjustments
    consume buckets FIFO and may push the account into debt.
    """

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, input_: AdjustInput
    ) -> LedgerEntryDTO:
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_ADJUST)
        if input_.amount == 0:
            raise _validation("points.zero_amount", "adjustment amount must be nonzero")
        async with ctx.uow_factory() as uow:
            program_key = input_.program_key or DEFAULT_PROGRAM_KEY
            program = await _require_program(uow, program_key)
            account = await _ensure_account(
                ctx, uow, program, input_.subject_type, input_.subject_id
            )
            existing = await _find_idempotent(uow, program.id, input_.idempotency_key)
            if existing is not None:
                if existing.entry_type != "adjustment":
                    raise _conflict(
                        "points.idempotency_mismatch",
                        "idempotency key already used by a non-adjustment entry",
                    )
                return _to_entry(existing, program.program_key)
            allocations: list[tuple[PointsBucket, int]] = []
            if input_.amount > 0:
                new_balance = await _apply_balance(
                    uow, account, amount=input_.amount, allow_negative=True
                )
                before = max(0, new_balance - input_.amount)
                after = max(0, new_balance)
                if after > before:
                    bucket = await _bucket_target(uow, account, bucket_type="perpetual")
                    await _add_to_bucket(uow, account, bucket, after - before)
            else:
                new_balance, allocations = await _consume_buckets(
                    uow, account, -input_.amount, allow_negative=True
                )
            entry = PointsLedgerEntry(
                program_id=program.id,
                account_id=account.id,
                amount=input_.amount,
                entry_type="adjustment",
                created_at=ctx.clock.utc_now(),
                idempotency_key=input_.idempotency_key,
                actor_type="user",
                actor_id=ctx.actor_id,
                entry_metadata=LedgerMetadata(
                    values={"reason": input_.reason, **(input_.metadata or {})}
                ),
            )
            uow.session.add(entry)
            try:
                await uow.session.flush()
            except IntegrityError as exc:
                raise _conflict(
                    "points.duplicate_adjustment", "an adjustment with this key exists"
                ) from exc
            if allocations:
                await _add_allocations(uow, entry.id, allocations)
            key = "points.debited.v1" if input_.amount < 0 else "points.credited.v1"
            await _emit(
                ctx,
                uow,
                key=key,
                account=account,
                program=program,
                entry_id=str(entry.id),
                amount=entry.amount,
                balance=new_balance,
            )
            await _append_audit(
                ctx,
                uow,
                action="points.adjusted",
                target_type="points_account",
                target_id=str(account.id),
                details={
                    "program_key": program.program_key,
                    "amount": input_.amount,
                    "reason": input_.reason,
                    "entry_id": str(entry.id),
                },
            )
            await uow.commit()
            return _to_entry(entry, program.program_key)


class ExpireBuckets:
    """Idempotent expiration sweep: due buckets produce expiration entries.

    Each due bucket becomes one ``expiration`` ledger entry with the
    remaining amount, zeroes the bucket and records an allocation. A bucket
    whose amount is already zero is skipped, so re-runs and crashes are
    safe. No row locks are used: single-instance scheduling is provided by
    the caller (cron loop in the single worker); a concurrent sweep or
    debit racing this sweep is intercepted by the version conditional
    updates and the unique expiration idempotency key.
    """

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self) -> list[LedgerEntryDTO]:
        ctx = self._ctx
        entries: list[LedgerEntryDTO] = []
        async with ctx.uow_factory() as uow:
            due = (
                (
                    await uow.session.execute(
                        select(PointsBucket)
                        .where(
                            PointsBucket.bucket_type == "expiring",
                            PointsBucket.expires_at.is_not(None),
                            PointsBucket.expires_at <= ctx.clock.utc_now(),
                            PointsBucket.amount > 0,
                        )
                        .order_by(PointsBucket.expires_at.asc())
                    )
                )
                .scalars()
                .all()
            )
            for bucket in due:
                account: PointsAccount | None = await uow.session.get(
                    PointsAccount, bucket.account_id
                )
                program: PointsProgram | None = (
                    await uow.session.get(PointsProgram, account.program_id)
                    if account is not None
                    else None
                )
                if account is None or program is None:
                    continue
                entry = PointsLedgerEntry(
                    program_id=program.id,
                    account_id=account.id,
                    amount=-bucket.amount,
                    entry_type="expiration",
                    created_at=ctx.clock.utc_now(),
                    behavior_key=bucket.expiration_identity,
                    source_type="system",
                    source_id="bucket:" + str(bucket.id),
                    idempotency_key=f"expiration:{bucket.id}:{bucket.version}",
                    actor_type="system",
                    actor_id=None,
                    entry_metadata=LedgerMetadata(values={}),
                )
                uow.session.add(entry)
                try:
                    await uow.session.flush()
                except IntegrityError as exc:
                    await uow.rollback()
                    raise _conflict(
                        "points.expiration_conflict",
                        f"expiration raced for bucket {bucket.id}",
                    ) from exc
                await _add_allocations(uow, entry.id, [(bucket, bucket.amount)])
                balance = await _get_balance(uow, account.id)
                new_balance = balance.balance - bucket.amount
                statement = (
                    update(PointsBalance)
                    .where(
                        PointsBalance.account_id == account.id,
                        PointsBalance.version == balance.version,
                    )
                    .values(balance=new_balance, version=PointsBalance.version + 1)
                    .execution_options(synchronize_session=False)
                )
                result = await uow.session.execute(statement)
                if result.rowcount == 0:
                    raise _conflict(
                        "points.balance_conflict", "balance changed concurrently; retry"
                    )
                _sync_account_state(uow, account, new_balance)
                result = await uow.session.execute(
                    update(PointsBucket)
                    .where(
                        PointsBucket.id == bucket.id,
                        PointsBucket.version == bucket.version,
                    )
                    .values(amount=0, version=PointsBucket.version + 1)
                    .execution_options(synchronize_session=False)
                )
                if result.rowcount == 0:
                    raise _conflict("points.bucket_conflict", "bucket changed concurrently; retry")
                bucket.amount = 0
                bucket.version += 1
                await _emit(
                    ctx,
                    uow,
                    key="points.bucket_expired.v1",
                    account=account,
                    program=program,
                    entry_id=str(entry.id),
                    bucket_id=str(bucket.id),
                    expiration_identity=bucket.expiration_identity or "",
                    amount=-entry.amount,
                    balance=new_balance,
                )
                entries.append(_to_entry(entry, program.program_key))
            await uow.commit()
        return entries


class FreezePointsAccount:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, *, program_key: str, subject_type: str, subject_id: str, frozen: bool
    ) -> BalanceDTO:
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_FREEZE)
        async with ctx.uow_factory() as uow:
            program = await _require_program(uow, program_key)
            account = await _get_account(uow, program.id, subject_type, subject_id)
            balance = await _get_balance(uow, account.id)
            if frozen:
                target = "frozen"
            elif account.state == "frozen":
                target = "active" if balance.balance >= 0 else "debt"
            else:
                target = account.state
            if account.state != target:
                account.state = target
                account.version += 1
                await _emit(
                    ctx,
                    uow,
                    key="points.account_frozen.v1",
                    account=account,
                    program=program,
                    state=target,
                )
            await uow.commit()
            return _to_balance(account, balance, program_key)


class RebuildBalance:
    """Ops command: recompute balance and buckets from the ledger; dry-run first."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, account_id: Any, *, dry_run: bool = True
    ) -> dict[str, Any]:
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_REBUILD)
        async with ctx.uow_factory() as uow:
            account: PointsAccount | None = await uow.session.get(PointsAccount, account_id)
            if account is None:
                raise _not_found("points.account_not_found", f"account {account_id}")
            balance = await _get_balance(uow, account.id)
            ledger_sum = (
                await uow.session.execute(
                    select(func.coalesce(func.sum(PointsLedgerEntry.amount), 0)).where(
                        PointsLedgerEntry.account_id == account.id
                    )
                )
            ).scalar_one()
            buckets = (
                (
                    await uow.session.execute(
                        select(PointsBucket).where(PointsBucket.account_id == account.id)
                    )
                )
                .scalars()
                .all()
            )
            bucket_sum = sum(b.amount for b in buckets)
            if not dry_run:
                if ledger_sum != balance.balance:
                    balance.balance = ledger_sum
                    balance.version += 1
                if ledger_sum < 0:
                    account.state = "debt"
                elif account.state == "debt":
                    account.state = "active"
                if bucket_sum != max(0, ledger_sum):
                    await self._rebuild_buckets(uow, account, buckets)
                    bucket_sum = sum(b.amount for b in buckets)
            await uow.commit()
            match = ledger_sum == balance.balance and bucket_sum == max(0, ledger_sum)
            return {
                "account_id": str(account.id),
                "ledger_sum": ledger_sum,
                "current_balance": balance.balance,
                "bucket_sum": bucket_sum,
                "match": match,
                "dry_run": dry_run,
            }

    async def _rebuild_buckets(
        self,
        uow: UnitOfWork,
        account: PointsAccount,
        buckets: list[PointsBucket],
    ) -> None:
        """Zero buckets and replay the ledger deterministically.

        Credits add only the excess over any running debt; debits,
        expirations and credit-reversals subtract their recorded
        allocations; debit-reversals restore with debt-paydown first. The
        replay reproduces the runtime FIFO/debt semantics exactly because
        every consumption is recorded in points_debit_allocations.
        """

        for bucket in buckets:
            bucket.amount = 0
            bucket.version += 1
        await uow.session.flush()
        entries = (
            (
                await uow.session.execute(
                    select(PointsLedgerEntry)
                    .where(PointsLedgerEntry.account_id == account.id)
                    .order_by(PointsLedgerEntry.created_at.asc(), PointsLedgerEntry.id.asc())
                )
            )
            .scalars()
            .all()
        )
        running = 0
        for entry in entries:
            if entry.entry_type in ("credit", "adjustment") and entry.amount > 0:
                before = max(0, running)
                running += entry.amount
                delta = max(0, running) - before
                if delta > 0:
                    if entry.entry_type == "adjustment":
                        bucket = await _bucket_target(uow, account, bucket_type="perpetual")
                    else:
                        bucket_type = entry.entry_metadata.values.get("bucket_type", "perpetual")
                        identity: str | None = entry.entry_metadata.values.get(
                            "expiration_identity"
                        )
                        expires_at_raw: Any = entry.entry_metadata.values.get("expires_at")
                        expires_at: Any = None
                        if expires_at_raw is not None:
                            from datetime import datetime as dt

                            expires_at = dt.fromisoformat(expires_at_raw)
                        bucket = await _bucket_target(
                            uow,
                            account,
                            bucket_type=bucket_type,
                            expiration_identity=identity,
                            expires_at=expires_at,
                        )
                    await _add_to_bucket(uow, account, bucket, delta)
            elif entry.entry_type == "reversal":
                if entry.amount < 0:
                    # reversed a credit: its allocations were consumed
                    for bucket, amount in await _entry_allocations(uow, entry.id):
                        if bucket.amount < amount:
                            raise _conflict(
                                "points.rebuild_inconsistent",
                                f"ledger replays bucket {bucket.id} below zero",
                            )
                        await _add_to_bucket(uow, account, bucket, -amount)
                else:
                    # reversed a debit/expiration: restore original allocations
                    original: PointsLedgerEntry | None = (
                        await uow.session.get(PointsLedgerEntry, entry.reversal_of)
                        if entry.reversal_of is not None
                        else None
                    )
                    if original is not None:
                        targets = await _entry_allocations(uow, original.id)
                        await _restore_into(uow, account, targets, running, entry.amount)
                running += entry.amount
            else:
                # debit / expiration / negative adjustment: consume recorded
                # allocations (no overdraw possible at runtime)
                for bucket, amount in await _entry_allocations(uow, entry.id):
                    if bucket.amount < amount:
                        raise _conflict(
                            "points.rebuild_inconsistent",
                            f"ledger replays bucket {bucket.id} below zero",
                        )
                    await _add_to_bucket(uow, account, bucket, -amount)
                running += entry.amount


async def _validate_limits(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    spec: PointBehaviorSpec,
    account: PointsAccount,
    amount: int,
) -> None:
    if spec.direction == "credit" and spec.fixed_amount is not None:
        if amount != spec.fixed_amount:
            raise _validation(
                "points.amount_mismatch",
                f"behavior {spec.key} requires exactly {spec.fixed_amount}",
            )
    if not (spec.min_amount <= amount <= spec.max_amount):
        raise _validation(
            "points.amount_out_of_range",
            f"amount {amount} outside {spec.min_amount}..{spec.max_amount}",
        )
    if spec.cooldown_seconds is not None:
        cutoff = ctx.clock.utc_now() - timedelta(seconds=spec.cooldown_seconds)
        recent = (
            await uow.session.execute(
                select(func.count(PointsLedgerEntry.id)).where(
                    PointsLedgerEntry.account_id == account.id,
                    PointsLedgerEntry.behavior_key == spec.key,
                    PointsLedgerEntry.entry_type == spec.direction,
                    PointsLedgerEntry.created_at >= cutoff,
                )
            )
        ).scalar_one()
        if recent:
            raise _conflict(
                "points.cooldown",
                f"behavior {spec.key} is cooling down for this subject",
            )
    if spec.daily_limit is not None:
        tz = ZoneInfo(spec.business_timezone)
        now = ctx.clock.utc_now()
        local = now.astimezone(tz)
        day_start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
        day_end = day_start + timedelta(days=1)
        today = (
            await uow.session.execute(
                select(func.count(PointsLedgerEntry.id)).where(
                    PointsLedgerEntry.account_id == account.id,
                    PointsLedgerEntry.behavior_key == spec.key,
                    PointsLedgerEntry.entry_type == spec.direction,
                    PointsLedgerEntry.created_at >= day_start,
                    PointsLedgerEntry.created_at < day_end,
                )
            )
        ).scalar_one()
        if today >= spec.daily_limit:
            raise _conflict(
                "points.daily_limit",
                f"behavior {spec.key} hit its daily limit for this subject",
            )

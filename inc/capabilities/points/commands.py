"""Points commands.

Contract source: context/spec/capabilities/points.md §5.

The ledger is the source of truth; balance is updated atomically with the
entry. Debits use a conditional balance update so concurrent debits can
never overdraw; credits are idempotent by (program, idempotency_key).
Reversals always persist the accounting fact, even when they push the
balance negative (debt state blocks further ordinary debits).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from inc.capabilities.points.behaviors import PointBehaviorRegistry, PointBehaviorSpec
from inc.capabilities.points.events import POINTS_EVENT_SCHEMAS
from inc.capabilities.points.models import (
    LedgerMetadata,
    PointsAccount,
    PointsBalance,
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


async def _get_balance(uow: UnitOfWork, account_id: Any) -> PointsBalance:
    balance: PointsBalance | None = (
        (
            await uow.session.execute(
                select(PointsBalance).where(PointsBalance.account_id == account_id)
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
    )
    result = await uow.session.execute(statement)
    if result.rowcount == 0:
        raise _conflict("points.balance_conflict", "balance changed concurrently; retry")
    if new_balance < 0:
        if account.state != "debt":
            account.state = "debt"
            account.version += 1
            uow.session.add(account)
    elif account.state == "debt":
        account.state = "active"
        account.version += 1
        uow.session.add(account)
    return new_balance


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
        reversal_of=str(row.reversal_of) if row.reversal_of is not None else None,
        created_at=_ensure_utc(row.created_at),
    )


class OpenPointsAccount:
    """Open (or return) an account with a zero balance."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, *, program_key: str, subject_type: str, subject_id: str
    ) -> BalanceDTO:
        ctx = self._ctx
        async with ctx.uow_factory() as uow:
            program = await _require_program(uow, program_key)
            existing: PointsAccount | None = (
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
            if existing is not None:
                balance = await _get_balance(uow, existing.id)
                return _to_balance(existing, balance, program_key)
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
                raise _conflict(
                    "points.account_exists", "account already exists for this subject"
                ) from exc
            balance = PointsBalance(account_id=account.id, balance=0, version=1)
            uow.session.add(balance)
            await _emit(ctx, uow, key="points.account_opened.v1", account=account, program=program)
            await uow.commit()
            return _to_balance(account, balance, program_key)


class CreditPoints:
    """Idempotent credit under a registered behavior."""

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
            account = await _get_account(uow, program.id, input_.subject_type, input_.subject_id)
            if account.state == "frozen":
                raise _conflict("points.account_frozen", "points account is frozen")
            await _validate_limits(ctx, uow, spec=spec, account=account, amount=input_.amount)
            new_balance = await _apply_balance(
                uow, account, amount=input_.amount, allow_negative=True
            )
            entry = PointsLedgerEntry(
                program_id=program.id,
                account_id=account.id,
                amount=input_.amount,
                entry_type="credit",
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
    """Conditional debit that can never overdraw."""

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
            account = await _get_account(uow, program.id, input_.subject_type, input_.subject_id)
            if account.state in ("frozen", "debt"):
                raise _conflict(
                    "points.account_not_debitable", f"points account is {account.state}"
                )
            await _validate_limits(ctx, uow, spec=spec, account=account, amount=input_.amount)
            new_balance = await _apply_balance(
                uow, account, amount=-input_.amount, allow_negative=False
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
    """Reverse an entry once; the reversal fact always persists."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, entry_id: Any, input_: ReverseInput
    ) -> LedgerEntryDTO:
        ctx = self._ctx
        async with ctx.uow_factory() as uow:
            entry: PointsLedgerEntry | None = await uow.session.get(PointsLedgerEntry, entry_id)
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
            new_balance = await _apply_balance(
                uow, account, amount=-entry.amount, allow_negative=True
            )
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
    """Admin-only adjustment with reason, permission and audit."""

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
            accounts = (
                (
                    await uow.session.execute(
                        select(PointsAccount).where(
                            PointsAccount.subject_type == input_.subject_type,
                            PointsAccount.subject_id == input_.subject_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not accounts:
                raise _not_found("points.account_not_opened", "points account is not opened")
            account = accounts[0]
            program: PointsProgram | None = await uow.session.get(PointsProgram, account.program_id)
            if program is None:
                raise _not_found("points.program_not_found", "program not found")
            existing = await _find_idempotent(uow, program.id, input_.idempotency_key)
            if existing is not None:
                return _to_entry(existing, program.program_key)
            new_balance = await _apply_balance(
                uow, account, amount=input_.amount, allow_negative=True
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
            await uow.commit()
            return _to_entry(entry, program.program_key)


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
    """Ops command: recompute balance from the ledger; dry-run first."""

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
            if not dry_run and ledger_sum != balance.balance:
                balance.balance = ledger_sum
                balance.version += 1
                if ledger_sum < 0:
                    account.state = "debt"
            await uow.commit()
            return {
                "account_id": str(account.id),
                "ledger_sum": ledger_sum,
                "current_balance": balance.balance,
                "match": ledger_sum == balance.balance,
                "dry_run": dry_run,
            }

"""Points queries.

Contract source: context/spec/capabilities/points.md §6.

Queries never create accounts; a missing account returns an explicit
``not_opened`` state without writing.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from inc.capabilities.points.behaviors import PointBehaviorRegistry
from inc.capabilities.points.models import (
    PointsAccount,
    PointsBalance,
    PointsBucket,
    PointsDebitAllocation,
    PointsLedgerEntry,
)
from inc.capabilities.points.schemas import (
    BalanceDTO,
    BehaviorCatalogDTO,
    BucketDTO,
    DebitAllocationDTO,
    LedgerEntryDTO,
)
from inc.kernel.db import Page, UoWFactory, fetch_page


def _ensure_utc(value: Any) -> Any:
    from datetime import UTC

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class PointsQueries:
    """Read-only points surface."""

    def __init__(self, *, uow_factory: UoWFactory, behaviors: PointBehaviorRegistry) -> None:
        self._uow_factory = uow_factory
        self._behaviors = behaviors

    async def get_balance(  # type: ignore[return]
        self, *, program_key: str, subject_type: str, subject_id: str
    ) -> BalanceDTO:
        async with self._uow_factory() as uow:
            from inc.capabilities.points.models import PointsProgram

            program = (
                (
                    await uow.session.execute(
                        select(PointsProgram).where(PointsProgram.program_key == program_key)
                    )
                )
                .scalars()
                .first()
            )
            if program is None:
                raise KernelError(
                    code="points.program_inactive",
                    category=ErrorCategory.VALIDATION,
                    message=f"program {program_key!r} is not active",
                )
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
            if account is None:
                raise KernelError(
                    code="points.account_not_opened",
                    category=ErrorCategory.NOT_FOUND,
                    message="points account is not opened",
                )
            balance: PointsBalance | None = (
                (
                    await uow.session.execute(
                        select(PointsBalance).where(PointsBalance.account_id == account.id)
                    )
                )
                .scalars()
                .first()
            )
            if balance is None:
                raise KernelError(
                    code="points.balance_missing",
                    category=ErrorCategory.INTERNAL,
                    message="balance row missing",
                )
            return BalanceDTO(
                account_id=str(account.id),
                program_key=program_key,
                subject_type=account.subject_type,
                subject_id=account.subject_id,
                state=account.state,
                balance=balance.balance,
                version=balance.version,
            )

    async def list_buckets(  # type: ignore[return]
        self, *, program_key: str, subject_type: str, subject_id: str
    ) -> list[BucketDTO]:
        async with self._uow_factory() as uow:
            from inc.capabilities.points.models import PointsProgram

            program = (
                (
                    await uow.session.execute(
                        select(PointsProgram).where(PointsProgram.program_key == program_key)
                    )
                )
                .scalars()
                .first()
            )
            if program is None:
                raise KernelError(
                    code="points.program_inactive",
                    category=ErrorCategory.VALIDATION,
                    message=f"program {program_key!r} is not active",
                )
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
            if account is None:
                return []
            rows = (
                (
                    await uow.session.execute(
                        select(PointsBucket)
                        .where(PointsBucket.account_id == account.id)
                        .order_by(
                            PointsBucket.expires_at.asc().nulls_last(),
                            PointsBucket.created_at.asc(),
                        )
                    )
                )
                .scalars()
                .all()
            )
            return [
                BucketDTO(
                    id=str(row.id),
                    account_id=str(row.account_id),
                    bucket_type=row.bucket_type,
                    expiration_identity=row.expiration_identity,
                    expires_at=_ensure_utc(row.expires_at) if row.expires_at else None,
                    amount=row.amount,
                    version=row.version,
                )
                for row in rows
            ]

    async def list_ledger(  # type: ignore[return]
        self,
        *,
        program_key: str,
        subject_type: str,
        subject_id: str,
        page: int,
        size: int,
    ) -> Page[LedgerEntryDTO]:
        async with self._uow_factory() as uow:
            from inc.capabilities.points.models import PointsProgram

            program = (
                (
                    await uow.session.execute(
                        select(PointsProgram).where(PointsProgram.program_key == program_key)
                    )
                )
                .scalars()
                .first()
            )
            if program is None:
                raise KernelError(
                    code="points.program_inactive",
                    category=ErrorCategory.VALIDATION,
                    message=f"program {program_key!r} is not active",
                )
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
            if account is None:
                return Page(items=[], total=0, page=page, size=size)
            statement = (
                select(PointsLedgerEntry)
                .where(PointsLedgerEntry.account_id == account.id)
                .order_by(PointsLedgerEntry.created_at.desc(), PointsLedgerEntry.id.desc())
            )
            result: Page[PointsLedgerEntry] = await fetch_page(
                uow.session, statement, page=page, size=size
            )
            entries = [_to_entry(row, program_key) for row in result.items]
            await self._attach_allocations(uow, entries)
            return Page(
                items=entries,
                total=result.total,
                page=result.page,
                size=result.size,
            )

    async def _attach_allocations(self, uow: Any, entries: list[LedgerEntryDTO]) -> None:
        if not entries:
            return
        import uuid

        ids = [uuid.UUID(entry.id) for entry in entries]
        rows = (
            (
                await uow.session.execute(
                    select(PointsDebitAllocation).where(PointsDebitAllocation.entry_id.in_(ids))
                )
            )
            .scalars()
            .all()
        )
        grouped: dict[str, list[DebitAllocationDTO]] = {}
        for row in rows:
            grouped.setdefault(str(row.entry_id), []).append(
                DebitAllocationDTO(bucket_id=str(row.bucket_id), amount=row.amount)
            )
        for entry in entries:
            entry.allocations = grouped.get(entry.id, [])

    async def get_entry(self, entry_id: Any) -> LedgerEntryDTO | None:  # type: ignore[return]
        async with self._uow_factory() as uow:
            row: PointsLedgerEntry | None = await uow.session.get(PointsLedgerEntry, entry_id)
            if row is None:
                return None
            from inc.capabilities.points.models import PointsProgram

            program: PointsProgram | None = await uow.session.get(PointsProgram, row.program_id)
            entry = _to_entry(row, program.program_key if program is not None else "")
            await self._attach_allocations(uow, [entry])
            return entry

    async def find_credit_by_source(  # type: ignore[return]
        self, *, behavior_key: str, source_id: str
    ) -> LedgerEntryDTO | None:
        """Return the most recent credit entry for a behavior and source id.

        Used by cross-capability consumers (features) to resolve the credit
        that should be reversed; never writes.
        """
        async with self._uow_factory() as uow:
            row: PointsLedgerEntry | None = (
                (
                    await uow.session.execute(
                        select(PointsLedgerEntry)
                        .where(
                            PointsLedgerEntry.source_id == source_id,
                            PointsLedgerEntry.behavior_key == behavior_key,
                            PointsLedgerEntry.entry_type == "credit",
                        )
                        .order_by(PointsLedgerEntry.created_at.desc(), PointsLedgerEntry.id.desc())
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                return None
            from inc.capabilities.points.models import PointsProgram

            program: PointsProgram | None = await uow.session.get(PointsProgram, row.program_id)
            return _to_entry(row, program.program_key if program is not None else "")

    async def behavior_catalog(self) -> list[BehaviorCatalogDTO]:
        return [
            BehaviorCatalogDTO(
                key=spec.key,
                version=spec.version,
                program_key=spec.program_key,
                direction=spec.direction,
                fixed_amount=spec.fixed_amount,
                min_amount=spec.min_amount,
                max_amount=spec.max_amount,
                cooldown_seconds=spec.cooldown_seconds,
                daily_limit=spec.daily_limit,
                business_timezone=spec.business_timezone,
                expiration_days=spec.expiration_days,
            )
            for spec in self._behaviors.specs()
        ]


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


from inc.kernel.errors import ErrorCategory, KernelError  # noqa: E402

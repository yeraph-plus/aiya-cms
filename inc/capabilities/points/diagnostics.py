"""Points diagnostics: read-only consistency probes.

Contract source: context/spec/capabilities/points.md §9.

Compares ledger sums against balance snapshots and bucket sums, checks
negative balances outside debt state, overdue non-zero buckets and behavior
definition drift. Never repairs.
"""

from __future__ import annotations

from sqlalchemy import func, select

from inc.capabilities.points.behaviors import PointBehaviorRegistry
from inc.capabilities.points.models import (
    PointsAccount,
    PointsBalance,
    PointsBehaviorDefinition,
    PointsBucket,
    PointsLedgerEntry,
)
from inc.kernel.db import UoWFactory
from inc.kernel.observability import DiagnosticResult, DiagnosticStatus
from inc.kernel.time import Clock


class PointsDiagnostics:
    key = "points"

    def __init__(
        self,
        *,
        uow_factory: UoWFactory,
        behaviors: PointBehaviorRegistry,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._behaviors = behaviors
        self._clock = clock

    async def run(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        async with self._uow_factory() as uow:
            balances = (await uow.session.execute(select(PointsBalance))).scalars().all()
            mismatch = 0
            bucket_mismatch = 0
            negative_outside_debt = 0
            for balance in balances:
                account: PointsAccount | None = await uow.session.get(
                    PointsAccount, balance.account_id
                )
                ledger_sum = (
                    await uow.session.execute(
                        select(func.coalesce(func.sum(PointsLedgerEntry.amount), 0)).where(
                            PointsLedgerEntry.account_id == balance.account_id
                        )
                    )
                ).scalar_one()
                bucket_sum = (
                    await uow.session.execute(
                        select(func.coalesce(func.sum(PointsBucket.amount), 0)).where(
                            PointsBucket.account_id == balance.account_id
                        )
                    )
                ).scalar_one()
                if ledger_sum != balance.balance:
                    mismatch += 1
                if bucket_sum != max(0, balance.balance):
                    bucket_mismatch += 1
                if balance.balance < 0 and (account is None or account.state != "debt"):
                    negative_outside_debt += 1
            results.append(
                DiagnosticResult(
                    code="points.balance_mismatch",
                    status=DiagnosticStatus.OK if mismatch == 0 else DiagnosticStatus.DEGRADED,
                    summary=f"{mismatch}/{len(balances)} balances differ from ledger sums",
                )
            )
            results.append(
                DiagnosticResult(
                    code="points.bucket_mismatch",
                    status=(
                        DiagnosticStatus.OK if bucket_mismatch == 0 else DiagnosticStatus.DEGRADED
                    ),
                    summary=f"{bucket_mismatch}/{len(balances)} bucket sums differ from balances",
                )
            )
            results.append(
                DiagnosticResult(
                    code="points.negative_outside_debt",
                    status=(
                        DiagnosticStatus.OK
                        if negative_outside_debt == 0
                        else DiagnosticStatus.DEGRADED
                    ),
                    summary=f"{negative_outside_debt} negative balances outside debt state",
                )
            )

            overdue = (
                await uow.session.execute(
                    select(func.count(PointsBucket.id)).where(
                        PointsBucket.bucket_type == "expiring",
                        PointsBucket.expires_at.is_not(None),
                        PointsBucket.expires_at <= self._clock.utc_now(),
                        PointsBucket.amount > 0,
                    )
                )
            ).scalar_one()
            results.append(
                DiagnosticResult(
                    code="points.buckets_overdue",
                    status=DiagnosticStatus.OK if overdue == 0 else DiagnosticStatus.DEGRADED,
                    summary=f"{overdue} overdue buckets still hold points",
                )
            )

            definitions = (
                (await uow.session.execute(select(PointsBehaviorDefinition))).scalars().all()
            )
            registered = {s.key for s in self._behaviors.specs()}
            declared = {d.behavior_key for d in definitions}
            drift = sorted(declared - registered) + sorted(registered - declared)
            results.append(
                DiagnosticResult(
                    code="points.behavior_drift",
                    status=DiagnosticStatus.OK if not drift else DiagnosticStatus.DEGRADED,
                    summary=f"behavior definition drift: {drift}",
                )
            )
        return results

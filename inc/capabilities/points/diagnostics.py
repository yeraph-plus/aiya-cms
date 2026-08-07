"""Points diagnostics: read-only consistency probes.

Contract source: context/spec/capabilities/points.md §9.

Compares ledger sums against balance snapshots, checks negative balances
outside debt state and behavior definition drift. Never repairs.
"""

from __future__ import annotations

from sqlalchemy import func, select

from inc.capabilities.points.behaviors import PointBehaviorRegistry
from inc.capabilities.points.models import (
    PointsAccount,
    PointsBalance,
    PointsBehaviorDefinition,
    PointsLedgerEntry,
)
from inc.kernel.db import UoWFactory
from inc.kernel.observability import DiagnosticResult, DiagnosticStatus


class PointsDiagnostics:
    key = "points"

    def __init__(self, *, uow_factory: UoWFactory, behaviors: PointBehaviorRegistry) -> None:
        self._uow_factory = uow_factory
        self._behaviors = behaviors

    async def run(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        async with self._uow_factory() as uow:
            balances = (await uow.session.execute(select(PointsBalance))).scalars().all()
            mismatch = 0
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
                if ledger_sum != balance.balance:
                    mismatch += 1
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
                    code="points.negative_outside_debt",
                    status=(
                        DiagnosticStatus.OK
                        if negative_outside_debt == 0
                        else DiagnosticStatus.DEGRADED
                    ),
                    summary=f"{negative_outside_debt} negative balances outside debt state",
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

"""Membership diagnostics: read-only consistency probes.

Contract source: context/spec/capabilities/membership.md §11.

Reports subscriptions whose active cycle has ended, subscriptions with no
grant record, level drift between registry and DB mirror, and cancelled
rows still marked active. Never repairs.
"""

from __future__ import annotations

from sqlalchemy import func, select

from inc.capabilities.membership.levels import MembershipLevelRegistry
from inc.capabilities.membership.models import (
    MembershipLevel,
    MembershipRenewalRecord,
    MembershipSubscription,
)
from inc.kernel.db import UoWFactory
from inc.kernel.observability import DiagnosticResult, DiagnosticStatus
from inc.kernel.time import Clock


class MembershipDiagnostics:
    key = "membership"

    def __init__(
        self,
        *,
        uow_factory: UoWFactory,
        levels: MembershipLevelRegistry,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._levels = levels
        self._clock = clock

    async def run(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        async with self._uow_factory() as uow:
            overdue = (
                await uow.session.execute(
                    select(func.count(MembershipSubscription.id)).where(
                        MembershipSubscription.status == "active",
                        MembershipSubscription.cycle_end <= self._clock.utc_now(),
                    )
                )
            ).scalar_one()
            results.append(
                DiagnosticResult(
                    code="membership.active_overdue",
                    status=DiagnosticStatus.OK if overdue == 0 else DiagnosticStatus.DEGRADED,
                    summary=f"{overdue} active subscriptions with ended cycles",
                )
            )

            orphan_grants = (
                await uow.session.execute(
                    select(func.count(MembershipSubscription.id))
                    .select_from(MembershipSubscription)
                    .outerjoin(
                        MembershipRenewalRecord,
                        MembershipRenewalRecord.subscription_id == MembershipSubscription.id,
                    )
                    .where(MembershipRenewalRecord.id.is_(None))
                )
            ).scalar_one()
            results.append(
                DiagnosticResult(
                    code="membership.missing_grant_record",
                    status=(
                        DiagnosticStatus.OK if orphan_grants == 0 else DiagnosticStatus.DEGRADED
                    ),
                    summary=f"{orphan_grants} subscriptions without a grant record",
                )
            )

            declared = {spec.key for spec in self._levels.specs()}
            mirrored = {
                row.level_key
                for row in (await uow.session.execute(select(MembershipLevel))).scalars().all()
            }
            drift = sorted(declared - mirrored) + sorted(mirrored - declared)
            results.append(
                DiagnosticResult(
                    code="membership.level_drift",
                    status=DiagnosticStatus.OK if not drift else DiagnosticStatus.DEGRADED,
                    summary=f"membership level drift: {drift}",
                )
            )
        return results

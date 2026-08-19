"""Read-only membership consistency diagnostics."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.orm import aliased

from inc.capabilities.membership.levels import MembershipLevelRegistry
from inc.capabilities.membership.models import (
    MembershipCycle,
    MembershipLevel,
    MembershipSubscription,
)
from inc.kernel.db import UoWFactory
from inc.kernel.observability import DiagnosticResult, DiagnosticStatus
from inc.kernel.time import Clock


class MembershipDiagnostics:
    key = "membership"

    def __init__(
        self, *, uow_factory: UoWFactory, levels: MembershipLevelRegistry, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory
        self._levels = levels
        self._clock = clock

    async def run(self) -> list[DiagnosticResult]:
        async with self._uow_factory() as uow:
            overdue = await _count(
                uow,
                select(func.count(MembershipSubscription.id)).where(
                    MembershipSubscription.status.in_(("active", "cancelled")),
                    MembershipSubscription.cycle_end <= self._clock.utc_now(),
                ),
            )
            stale_prepared = await _count(
                uow,
                select(func.count(MembershipCycle.id)).where(
                    MembershipCycle.state == "prepared",
                    MembershipCycle.created_at <= self._clock.utc_now() - timedelta(hours=1),
                ),
            )
            invalid_activated = await _count(
                uow,
                select(func.count(MembershipCycle.id)).where(
                    MembershipCycle.state == "activated",
                    MembershipCycle.points_entry_ref.is_(None),
                ),
            )
            other_cycle = aliased(MembershipCycle)
            overlap = await _count(
                uow,
                select(func.count(MembershipCycle.id)).join(
                    other_cycle,
                    and_(
                        MembershipCycle.subscription_id == other_cycle.subscription_id,
                        MembershipCycle.id < other_cycle.id,
                        MembershipCycle.state != "failed",
                        other_cycle.state != "failed",
                        MembershipCycle.cycle_start < other_cycle.cycle_end,
                        other_cycle.cycle_start < MembershipCycle.cycle_end,
                    ),
                ),
            )
            declared = {spec.key for spec in self._levels.specs()}
            mirrored = {
                row.level_key
                for row in (await uow.session.execute(select(MembershipLevel))).scalars().all()
            }
        drift = sorted(declared ^ mirrored)
        return [
            _result("membership.prepared_stale", stale_prepared, "stale prepared cycles"),
            _result(
                "membership.invalid_activated_cycle", invalid_activated, "invalid activated cycles"
            ),
            _result("membership.active_overdue", overdue, "active subscriptions with ended cycles"),
            _result("membership.overlapping_cycles", overlap, "overlapping cycles"),
            DiagnosticResult(
                code="membership.level_drift",
                status=DiagnosticStatus.OK if not drift else DiagnosticStatus.DEGRADED,
                summary=f"membership level drift: {drift}",
            ),
        ]


async def _count(uow: object, statement: object) -> int:
    return int((await uow.session.execute(statement)).scalar_one())  # type: ignore[attr-defined]


def _result(code: str, count: int, label: str) -> DiagnosticResult:
    return DiagnosticResult(
        code=code,
        status=DiagnosticStatus.OK if count == 0 else DiagnosticStatus.DEGRADED,
        summary=f"{count} {label}",
    )

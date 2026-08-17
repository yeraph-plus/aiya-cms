"""Administrator commands and queries owned by membership."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from inc.capabilities.membership.levels import MembershipLevelRegistry, MembershipLevelSpec
from inc.capabilities.membership.models import (
    LevelMetadata,
    MembershipLevel,
    MembershipSubscription,
)
from inc.capabilities.membership.schemas import (
    CreateLevelInput,
    LevelDTO,
    LevelStatusInput,
    MembershipSummaryDTO,
    UpdateLevelInput,
)
from inc.kernel.db import UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock


@dataclass(frozen=True, slots=True)
class MembershipAdminService:
    """Keep level CRUD and summary semantics out of the HTTP adapter."""

    uow_factory: UoWFactory
    clock: Clock
    outbox: OutboxWriter
    levels: MembershipLevelRegistry

    async def hydrate_persisted_levels(self) -> None:
        """Restore administrator-managed level projections before workers run."""

        async with self.uow_factory() as uow:
            rows = (await uow.session.execute(select(MembershipLevel))).scalars().all()
        for row in rows:
            try:
                spec = self.levels.require(row.level_key)
            except KernelError as exc:
                if exc.code != "membership.unknown_level":
                    raise
                self.levels.register_runtime(
                    MembershipLevelSpec(
                        key=row.level_key,
                        display_name=row.display_name,
                        tier_rank=row.tier_rank,
                        status=row.status,
                        cycle_days=row.cycle_days,
                        grant_points=row.grant_points,
                        renewal_allowed=row.renewal_allowed,
                        version=row.version,
                    )
                )
                continue
            for name in (
                "display_name",
                "tier_rank",
                "status",
                "cycle_days",
                "grant_points",
                "renewal_allowed",
            ):
                setattr(spec, name, getattr(row, name))
            spec.version = row.version

    async def create_level(
        self, body: CreateLevelInput, *, actor_id: str, trace_id: str | None
    ) -> LevelDTO:
        if any(item.key == body.level_key for item in self.levels.specs()):
            raise _error(
                "membership.level_exists", ErrorCategory.CONFLICT, "membership level already exists"
            )
        spec = MembershipLevelSpec(
            key=body.level_key,
            display_name=body.display_name,
            tier_rank=body.tier_rank,
            cycle_days=body.cycle_days,
            grant_points=body.grant_points,
            renewal_allowed=body.renewal_allowed,
        )
        async with self.uow_factory() as uow:
            row = MembershipLevel(
                level_key=spec.key,
                display_name=spec.display_name,
                tier_rank=spec.tier_rank,
                status=spec.status,
                cycle_days=spec.cycle_days,
                grant_points=spec.grant_points,
                renewal_allowed=spec.renewal_allowed,
                data=LevelMetadata(),
            )
            uow.session.add(row)
            try:
                await uow.session.flush()
            except IntegrityError as exc:
                raise _error(
                    "membership.level_exists",
                    ErrorCategory.CONFLICT,
                    "membership level already exists",
                ) from exc
            await self._audit(
                uow,
                actor_id,
                trace_id,
                "membership.level.created",
                str(row.id),
                {"level_key": row.level_key},
            )
            await uow.commit()
        self.levels.register_runtime(spec)
        return _level_dto(spec)

    async def update_level(
        self, level_key: str, body: UpdateLevelInput, *, actor_id: str, trace_id: str | None
    ) -> LevelDTO:
        values = body.model_dump(exclude_unset=True, exclude={"expected_version"})
        async with self.uow_factory() as uow:
            row = (
                (
                    await uow.session.execute(
                        select(MembershipLevel).where(MembershipLevel.level_key == level_key)
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                raise _error(
                    "membership.level_not_found",
                    ErrorCategory.NOT_FOUND,
                    "membership level not found",
                )
            if row.version != body.expected_version:
                raise _error(
                    "membership.level_version_conflict",
                    ErrorCategory.CONFLICT,
                    "membership level was changed by another administrator",
                )
            for key, value in values.items():
                setattr(row, key, value)
            row.version += 1
            await self._audit(
                uow,
                actor_id,
                trace_id,
                "membership.level.updated",
                str(row.id),
                {"level_key": level_key, "changed": sorted(values)},
            )
            await uow.commit()
        return _level_dto(self.levels.update_runtime(level_key, **values))

    async def set_level_status(
        self,
        level_key: str,
        status: Literal["active", "archived"],
        body: LevelStatusInput,
        *,
        actor_id: str,
        trace_id: str | None,
    ) -> LevelDTO:
        async with self.uow_factory() as uow:
            row = (
                (
                    await uow.session.execute(
                        select(MembershipLevel).where(MembershipLevel.level_key == level_key)
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                raise _error(
                    "membership.level_not_found",
                    ErrorCategory.NOT_FOUND,
                    "membership level not found",
                )
            if row.version != body.expected_version:
                raise _error(
                    "membership.level_version_conflict",
                    ErrorCategory.CONFLICT,
                    "membership level was changed by another administrator",
                )
            row.status = status
            row.version += 1
            await self._audit(
                uow,
                actor_id,
                trace_id,
                f"membership.level.{status}",
                str(row.id),
                {"level_key": level_key, "reason": body.reason},
            )
            await uow.commit()
        return _level_dto(self.levels.update_runtime(level_key, status=status))

    async def summary(self) -> MembershipSummaryDTO:
        async with self.uow_factory() as uow:
            persisted = (
                await uow.session.execute(select(MembershipLevel.level_key, MembershipLevel.status))
            ).all()
            statuses = {key: status for key, status in persisted}
            for spec in self.levels.specs():
                statuses.setdefault(spec.key, spec.status)
            counts = {
                status: int(
                    (
                        await uow.session.execute(
                            select(func.count())
                            .select_from(MembershipSubscription)
                            .where(MembershipSubscription.status == status)
                        )
                    ).scalar_one()
                )
                for status in ("active", "cancelled", "expired")
            }
            total = int(
                (
                    await uow.session.execute(
                        select(func.count()).select_from(MembershipSubscription)
                    )
                ).scalar_one()
            )
        return MembershipSummaryDTO(
            level_count=len(statuses),
            active_level_count=sum(status == "active" for status in statuses.values()),
            subscription_count=total,
            active_subscription_count=counts["active"],
            cancelled_subscription_count=counts["cancelled"],
            expired_subscription_count=counts["expired"],
        )

    async def _audit(
        self,
        uow: Any,
        actor_id: str,
        trace_id: str | None,
        action: str,
        target_id: str,
        details: dict[str, Any],
    ) -> None:
        await self.outbox.append(
            uow,
            EventEnvelope(
                event_id=uuid.uuid7(),
                event_key="audit.entry.recorded.v1",
                occurred_at=self.clock.utc_now(),
                producer="membership",
                aggregate_type="membership",
                aggregate_id=target_id,
                trace_id=trace_id,
                payload={
                    "action": action,
                    "outcome": "success",
                    "occurred_at": self.clock.utc_now().isoformat(),
                    "actor_type": "user",
                    "actor_id": actor_id,
                    "target_type": "membership_level",
                    "target_id": target_id,
                    "trace_id": trace_id,
                    "details": details,
                },
            ),
        )


def _level_dto(spec: MembershipLevelSpec) -> LevelDTO:
    return LevelDTO(
        level_key=spec.key,
        display_name=spec.display_name,
        tier_rank=spec.tier_rank,
        status=spec.status,
        cycle_days=spec.cycle_days,
        grant_points=spec.grant_points,
        renewal_allowed=spec.renewal_allowed,
        version=spec.version,
    )


def _error(code: str, category: ErrorCategory, message: str) -> KernelError:
    return KernelError(code=code, category=category, message=message)

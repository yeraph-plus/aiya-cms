"""Read-only membership queries."""

from __future__ import annotations

import uuid
from datetime import UTC
from typing import Any

from sqlalchemy import select

from inc.capabilities.membership.levels import MembershipLevelRegistry, MembershipLevelSpec
from inc.capabilities.membership.models import (
    MembershipCycle,
    MembershipLevel,
    MembershipSubscription,
)
from inc.capabilities.membership.schemas import LevelDTO, MembershipCycleDTO, SubscriptionDTO
from inc.kernel.db import Page, UoWFactory, fetch_page
from inc.kernel.errors import ErrorCategory, KernelError


class MembershipQueries:
    def __init__(self, *, uow_factory: UoWFactory, levels: MembershipLevelRegistry) -> None:
        self._uow_factory = uow_factory
        self._levels = levels

    async def list_levels(self) -> list[LevelDTO]:
        async with self._uow_factory() as uow:
            rows = (
                (
                    await uow.session.execute(
                        select(MembershipLevel).where(MembershipLevel.status == "active")
                    )
                )
                .scalars()
                .all()
            )
        known = {spec.key for spec in self._levels.specs()}
        for row in rows:
            if row.level_key not in known:
                self._levels.register_runtime(
                    MembershipLevelSpec(
                        key=row.level_key,
                        display_name=row.display_name,
                        tier_rank=row.tier_rank,
                        cycle_days=row.cycle_days,
                        cycle_points_amount=row.grant_points,
                        renewal_allowed=row.renewal_allowed,
                        status=row.status,
                        version=row.version,
                    )
                )
        return [
            _to_level(spec)
            for spec in sorted(self._levels.specs(), key=lambda item: item.tier_rank)
            if spec.status == "active"
        ]

    async def get_subscription(
        self, *, subject_type: str, subject_id: str
    ) -> SubscriptionDTO | None:
        async with self._uow_factory() as uow:
            row = (
                (
                    await uow.session.execute(
                        select(MembershipSubscription).where(
                            MembershipSubscription.subject_type == subject_type,
                            MembershipSubscription.subject_id == subject_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            return _to_subscription(row) if row is not None else None
        raise AssertionError("unreachable: get subscription completed")

    async def list_subscriptions(
        self,
        *,
        page: int,
        size: int,
        subject_type: str | None = None,
        subject_id: str | None = None,
        level_key: str | None = None,
        status: str | None = None,
    ) -> Page[SubscriptionDTO]:
        async with self._uow_factory() as uow:
            statement = select(MembershipSubscription)
            if subject_type is not None:
                statement = statement.where(MembershipSubscription.subject_type == subject_type)
            if subject_id is not None:
                statement = statement.where(MembershipSubscription.subject_id == subject_id)
            if level_key is not None:
                statement = statement.where(MembershipSubscription.level_key == level_key)
            if status is not None:
                statement = statement.where(MembershipSubscription.status == status)
            result: Page[MembershipSubscription] = await fetch_page(
                uow.session,
                statement.order_by(
                    MembershipSubscription.created_at.desc(), MembershipSubscription.id.desc()
                ),
                page=page,
                size=size,
            )
            return Page(
                items=[_to_subscription(row) for row in result.items],
                total=result.total,
                page=result.page,
                size=result.size,
            )
        raise AssertionError("unreachable: list subscriptions completed")

    async def get_membership_cycle(self, cycle_id: str) -> MembershipCycleDTO:
        try:
            identifier = uuid.UUID(cycle_id)
        except ValueError as exc:
            raise _cycle_not_found(cycle_id) from exc
        async with self._uow_factory() as uow:
            row = await uow.session.get(MembershipCycle, identifier)
            if row is None:
                raise _cycle_not_found(cycle_id)
            subscription = await uow.session.get(MembershipSubscription, row.subscription_id)
            if subscription is None:
                raise KernelError(
                    code="membership.cycle_subscription_missing",
                    category=ErrorCategory.INTERNAL,
                    message=f"cycle {cycle_id} has no subscription",
                )
            return _to_cycle(row, subscription)
        raise AssertionError("unreachable: get membership cycle completed")

    async def list_membership_cycles(
        self,
        *,
        page: int,
        size: int,
        subscription_id: str | None = None,
        state: str | None = None,
        source_type: str | None = None,
        source_ref: str | None = None,
    ) -> Page[MembershipCycleDTO]:
        statement = select(MembershipCycle)
        if subscription_id is not None:
            try:
                identifier = uuid.UUID(subscription_id)
            except ValueError as exc:
                raise _cycle_not_found(subscription_id) from exc
            statement = statement.where(MembershipCycle.subscription_id == identifier)
        if state is not None:
            statement = statement.where(MembershipCycle.state == state)
        if source_type is not None:
            statement = statement.where(MembershipCycle.source_type == source_type)
        if source_ref is not None:
            statement = statement.where(MembershipCycle.source_ref == source_ref)
        async with self._uow_factory() as uow:
            result: Page[MembershipCycle] = await fetch_page(
                uow.session,
                statement.order_by(MembershipCycle.created_at.desc(), MembershipCycle.id.desc()),
                page=page,
                size=size,
            )
            subscription_ids = {row.subscription_id for row in result.items}
            subscriptions = {
                row.id: row
                for row in (
                    (
                        await uow.session.execute(
                            select(MembershipSubscription).where(
                                MembershipSubscription.id.in_(subscription_ids)
                            )
                        )
                    )
                    .scalars()
                    .all()
                    if subscription_ids
                    else []
                )
            }
            return Page(
                items=[_to_cycle(row, subscriptions[row.subscription_id]) for row in result.items],
                total=result.total,
                page=result.page,
                size=result.size,
            )
        raise AssertionError("unreachable: list membership cycles completed")


def _utc(value: Any) -> Any:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _to_level(spec: MembershipLevelSpec) -> LevelDTO:
    return LevelDTO(
        level_key=spec.key,
        display_name=spec.display_name,
        tier_rank=spec.tier_rank,
        status=spec.status,
        cycle_days=spec.cycle_days,
        grant_points=spec.cycle_points_amount,
        renewal_allowed=spec.renewal_allowed,
        version=spec.version,
    )


def _to_subscription(row: MembershipSubscription) -> SubscriptionDTO:
    return SubscriptionDTO(
        id=str(row.id),
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        level_key=row.level_key,
        cycle_start=_utc(row.cycle_start),
        cycle_end=_utc(row.cycle_end),
        status=row.status,
        auto_renew=row.auto_renew,
        granted_points=row.granted_points,
        renewal_count=row.renewal_count,
        cycle_id=str(row.cycle_id) if row.cycle_id else None,
        cycle_points_amount=row.granted_points,
        source_type=row.source_type,
        source_ref=row.source_ref,
        cancelled_at=_utc(row.cancelled_at) if row.cancelled_at else None,
        expired_at=_utc(row.expired_at) if row.expired_at else None,
        terminated_at=_utc(row.terminated_at) if row.terminated_at else None,
        version=row.version,
    )


def _to_cycle(row: MembershipCycle, subscription: MembershipSubscription) -> MembershipCycleDTO:
    return MembershipCycleDTO(
        cycle_id=str(row.id),
        subscription_id=str(row.subscription_id),
        subject_type=subscription.subject_type,
        subject_id=subscription.subject_id,
        level_key=row.level_key,
        cycle_start=_utc(row.cycle_start),
        cycle_end=_utc(row.cycle_end),
        cycle_points_amount=row.cycle_points_amount,
        state=row.state,
        source_type=row.source_type,
        source_ref=row.source_ref,
        points_entry_ref=row.points_entry_ref,
        idempotency_key=row.idempotency_key,
        failure_code=row.failure_code,
        version=row.version,
    )


def _cycle_not_found(cycle_id: str) -> KernelError:
    return KernelError(
        code="membership.cycle_not_found",
        category=ErrorCategory.NOT_FOUND,
        message=f"membership cycle {cycle_id} was not found",
    )

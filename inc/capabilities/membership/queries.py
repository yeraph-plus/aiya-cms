"""Membership queries.

Contract source: context/spec/capabilities/membership.md §6.

Queries never create subscriptions; a missing subscription returns an
explicit ``no_subscription`` state without writing.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from inc.capabilities.membership.levels import MembershipLevelRegistry
from inc.capabilities.membership.models import (
    MembershipRenewalRecord,
    MembershipSubscription,
)
from inc.capabilities.membership.schemas import LevelDTO, RenewalRecordDTO, SubscriptionDTO
from inc.kernel.db import Page, UoWFactory, fetch_page


class MembershipQueries:
    """Read-only membership surface."""

    def __init__(self, *, uow_factory: UoWFactory, levels: MembershipLevelRegistry) -> None:
        self._uow_factory = uow_factory
        self._levels = levels

    async def list_levels(self) -> list[LevelDTO]:
        return [
            LevelDTO(
                level_key=spec.key,
                display_name=spec.display_name,
                tier_rank=spec.tier_rank,
                status="active",
                cycle_days=spec.cycle_days,
                grant_points=spec.grant_points,
                renewal_allowed=spec.renewal_allowed,
            )
            for spec in sorted(self._levels.specs(), key=lambda s: s.tier_rank)
        ]

    async def get_subscription(  # type: ignore[return]
        self, *, subject_type: str, subject_id: str
    ) -> SubscriptionDTO | None:
        async with self._uow_factory() as uow:
            row: MembershipSubscription | None = (
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
            if row is None:
                return None
            return _to_subscription(row)

    async def list_subscriptions(  # type: ignore[return]
        self, *, page: int, size: int
    ) -> Page[SubscriptionDTO]:
        async with self._uow_factory() as uow:
            statement = select(MembershipSubscription).order_by(
                MembershipSubscription.created_at.desc()
            )
            result: Page[MembershipSubscription] = await fetch_page(
                uow.session, statement, page=page, size=size
            )
            return Page(
                items=[_to_subscription(row) for row in result.items],
                total=result.total,
                page=result.page,
                size=result.size,
            )

    async def list_renewal_records(  # type: ignore[return]
        self, *, subscription_id: str, page: int, size: int
    ) -> Page[RenewalRecordDTO]:
        async with self._uow_factory() as uow:
            statement = (
                select(MembershipRenewalRecord)
                .where(MembershipRenewalRecord.subscription_id == uuid.UUID(str(subscription_id)))
                .order_by(MembershipRenewalRecord.created_at.desc())
            )
            result: Page[MembershipRenewalRecord] = await fetch_page(
                uow.session, statement, page=page, size=size
            )
            return Page(
                items=[_to_renewal(row) for row in result.items],
                total=result.total,
                page=result.page,
                size=result.size,
            )


def _to_subscription(row: MembershipSubscription) -> SubscriptionDTO:
    from datetime import UTC

    def _utc(value: Any) -> Any:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value

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
        cancelled_at=_utc(row.cancelled_at) if row.cancelled_at else None,
        expired_at=_utc(row.expired_at) if row.expired_at else None,
    )


def _to_renewal(row: MembershipRenewalRecord) -> RenewalRecordDTO:
    return RenewalRecordDTO(
        id=str(row.id),
        subscription_id=str(row.subscription_id),
        cycle_start=row.cycle_start,
        cycle_end=row.cycle_end,
        granted_points=row.granted_points,
        points_source_id=row.points_source_id,
        outcome=row.outcome,
    )

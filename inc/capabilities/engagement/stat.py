"""Engagement-owned statistics and dashboard provider."""

from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select

from inc.capabilities.engagement.models import (
    ContentEngagementStats,
    ContentLike,
    ContentRating,
    ContentView,
)


async def stat(*, uow_factory: Any, now: Any, window_days: int = 7) -> dict[str, Any]:
    since = now - timedelta(days=window_days)
    async with uow_factory() as uow:
        totals = (
            await uow.session.execute(
                select(
                    func.coalesce(func.sum(ContentEngagementStats.view_count), 0),
                    func.coalesce(func.sum(ContentEngagementStats.like_count), 0),
                    func.coalesce(func.sum(ContentEngagementStats.rating_sum), 0),
                    func.coalesce(func.sum(ContentEngagementStats.rating_count), 0),
                )
            )
        ).one()
        views = await uow.session.scalar(
            select(func.count(ContentView.id)).where(ContentView.viewed_at >= since)
        )
        likes = await uow.session.scalar(
            select(func.count(ContentLike.id)).where(
                ContentLike.liked_at >= since, ContentLike.removed_at.is_(None)
            )
        )
        ratings = await uow.session.scalar(
            select(func.count(ContentRating.id)).where(
                ContentRating.rated_at >= since, ContentRating.removed_at.is_(None)
            )
        )
    rating_count = int(totals[3] or 0)
    rating_average = (
        (Decimal(int(totals[2] or 0)) / Decimal(rating_count)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
        if rating_count
        else None
    )
    return {
        "view_count": int(totals[0] or 0),
        "like_count": int(totals[1] or 0),
        "rating_sum": int(totals[2] or 0),
        "rating_count": rating_count,
        "rating_average": rating_average,
        "window_increment": {
            "views": int(views or 0),
            "likes": int(likes or 0),
            "ratings": int(ratings or 0),
        },
    }


class Provider:
    key = "engagement"

    def __init__(self, *, uow_factory: Any, clock: Any) -> None:
        self._uow_factory, self._clock = uow_factory, clock

    async def summary(self, *, window: str = "7d") -> dict[str, Any]:
        return await stat(
            uow_factory=self._uow_factory,
            now=self._clock.utc_now(),
            window_days={"24h": 1, "7d": 7, "30d": 30}[window],
        )

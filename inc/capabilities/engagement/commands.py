"""Idempotent engagement commands."""

from __future__ import annotations

import hashlib
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select

from inc.capabilities.engagement.models import (
    ContentEngagementStats,
    ContentLike,
    ContentRating,
    ContentView,
)
from inc.capabilities.engagement.ports import ContentEngagementTarget, EngageableContentReader
from inc.capabilities.engagement.schemas import (
    EngagementSummaryDTO,
    LikeContentInput,
    RateContentInput,
    RecordContentViewInput,
    UnlikeContentInput,
    WithdrawRatingInput,
)
from inc.kernel.db import UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.time import Clock


def _error(code: str, category: ErrorCategory, message: str) -> KernelError:
    return KernelError(code=code, category=category, message=message)


def _subject(value: uuid.UUID | str) -> str:
    return str(value)


def _average(total: int, count: int) -> Decimal | None:
    if count <= 0:
        return None
    return (Decimal(total) / Decimal(count)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _refresh_average(stats: ContentEngagementStats) -> None:
    stats.rating_average = _average(int(stats.rating_sum), int(stats.rating_count))


class EngagementCommands:
    def __init__(
        self,
        *,
        uow_factory: UoWFactory,
        clock: Clock,
        content_reader: EngageableContentReader,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._content_reader = content_reader

    async def _target(self, content_id: uuid.UUID) -> ContentEngagementTarget:
        target = await self._content_reader.get(content_id)
        if target is None:
            raise _error(
                "engagement.content_not_found", ErrorCategory.NOT_FOUND, "content not found"
            )
        if target.status != "published":
            raise _error(
                "engagement.content_not_published",
                ErrorCategory.CONFLICT,
                "only published content can be engaged",
            )
        return target

    async def _stats(self, uow: Any, target: ContentEngagementTarget) -> ContentEngagementStats:
        row: ContentEngagementStats | None = (
            (
                await uow.session.execute(
                    select(ContentEngagementStats).where(
                        ContentEngagementStats.content_id == target.content_id
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            row = ContentEngagementStats(
                content_id=target.content_id,
                type_name=target.type_name,
                content_status=target.status,
                published_at=target.published_at,
                projected_at=self._clock.utc_now(),
            )
            uow.session.add(row)
            await uow.session.flush()
        else:
            row.type_name = target.type_name
            row.content_status = target.status
            row.published_at = target.published_at
            _refresh_average(row)
        return row

    async def _summary(
        self,
        uow: Any,
        stats: ContentEngagementStats,
        *,
        subject_id: uuid.UUID | str | None = None,
        subject_type: str = "user",
        counted: bool | None = None,
    ) -> EngagementSummaryDTO:
        viewer_liked: bool | None = None
        viewer_rating: int | None = None
        if subject_id is not None:
            sid = _subject(subject_id)
            like = (
                (
                    await uow.session.execute(
                        select(ContentLike).where(
                            ContentLike.content_id == stats.content_id,
                            ContentLike.subject_type == subject_type,
                            ContentLike.subject_id == sid,
                        )
                    )
                )
                .scalars()
                .first()
            )
            rating = (
                (
                    await uow.session.execute(
                        select(ContentRating).where(
                            ContentRating.content_id == stats.content_id,
                            ContentRating.subject_type == subject_type,
                            ContentRating.subject_id == sid,
                        )
                    )
                )
                .scalars()
                .first()
            )
            viewer_liked = like is not None and like.removed_at is None
            viewer_rating = (
                rating.rating if rating is not None and rating.removed_at is None else None
            )
        return EngagementSummaryDTO(
            content_id=str(stats.content_id),
            view_count=int(stats.view_count),
            like_count=int(stats.like_count),
            rating_sum=int(stats.rating_sum),
            rating_count=int(stats.rating_count),
            rating_average=_average(int(stats.rating_sum), int(stats.rating_count)),
            viewer_liked=viewer_liked,
            viewer_rating=viewer_rating,
            counted=counted,
        )

    async def record_view(self, input_: RecordContentViewInput) -> EngagementSummaryDTO:
        target = await self._target(input_.content_id)
        digest = (
            hashlib.sha256(input_.idempotency_key.encode("utf-8")).hexdigest()
            if input_.idempotency_key
            else None
        )
        async with self._uow_factory() as uow:
            stats = await self._stats(uow, target)
            counted = True
            if digest is not None:
                existing = (
                    (
                        await uow.session.execute(
                            select(ContentView).where(
                                ContentView.content_id == target.content_id,
                                ContentView.idempotency_key_digest == digest,
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if existing is not None:
                    counted = False
            if counted:
                uow.session.add(
                    ContentView(
                        content_id=target.content_id,
                        idempotency_key_digest=digest,
                        viewed_at=self._clock.utc_now(),
                    )
                )
                stats.view_count += 1
            stats.projected_at = self._clock.utc_now()
            await uow.commit()
            return await self._summary(uow, stats, counted=counted)
        raise RuntimeError("engagement view command did not execute")

    async def like_content(self, input_: LikeContentInput) -> EngagementSummaryDTO:
        target = await self._target(input_.content_id)
        sid = _subject(input_.subject_id)
        async with self._uow_factory() as uow:
            stats = await self._stats(uow, target)
            row = (
                (
                    await uow.session.execute(
                        select(ContentLike).where(
                            ContentLike.content_id == target.content_id,
                            ContentLike.subject_type == input_.subject_type,
                            ContentLike.subject_id == sid,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                row = ContentLike(
                    content_id=target.content_id,
                    subject_type=input_.subject_type,
                    subject_id=sid,
                    liked_at=self._clock.utc_now(),
                )
                uow.session.add(row)
                stats.like_count += 1
            elif row.removed_at is not None:
                row.removed_at = None
                row.liked_at = self._clock.utc_now()
                stats.like_count += 1
            stats.projected_at = self._clock.utc_now()
            await uow.commit()
            return await self._summary(uow, stats, subject_id=sid, subject_type=input_.subject_type)
        raise RuntimeError("engagement like command did not execute")

    async def unlike_content(self, input_: UnlikeContentInput) -> EngagementSummaryDTO:
        target = await self._target(input_.content_id)
        sid = _subject(input_.subject_id)
        async with self._uow_factory() as uow:
            stats = await self._stats(uow, target)
            row = (
                (
                    await uow.session.execute(
                        select(ContentLike).where(
                            ContentLike.content_id == target.content_id,
                            ContentLike.subject_type == input_.subject_type,
                            ContentLike.subject_id == sid,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if row is not None and row.removed_at is None:
                row.removed_at = self._clock.utc_now()
                stats.like_count = max(0, int(stats.like_count) - 1)
            stats.projected_at = self._clock.utc_now()
            await uow.commit()
            return await self._summary(uow, stats, subject_id=sid, subject_type=input_.subject_type)
        raise RuntimeError("engagement unlike command did not execute")

    async def rate_content(self, input_: RateContentInput) -> EngagementSummaryDTO:
        target = await self._target(input_.content_id)
        sid = _subject(input_.subject_id)
        async with self._uow_factory() as uow:
            stats = await self._stats(uow, target)
            row = (
                (
                    await uow.session.execute(
                        select(ContentRating).where(
                            ContentRating.content_id == target.content_id,
                            ContentRating.subject_type == input_.subject_type,
                            ContentRating.subject_id == sid,
                        )
                    )
                )
                .scalars()
                .first()
            )
            now = self._clock.utc_now()
            if row is None:
                row = ContentRating(
                    content_id=target.content_id,
                    subject_type=input_.subject_type,
                    subject_id=sid,
                    rating=input_.rating,
                    rated_at=now,
                )
                uow.session.add(row)
                stats.rating_sum += input_.rating
                stats.rating_count += 1
            elif row.removed_at is not None:
                row.rating = input_.rating
                row.removed_at = None
                row.rated_at = now
                stats.rating_sum += input_.rating
                stats.rating_count += 1
            elif row.rating != input_.rating:
                stats.rating_sum += input_.rating - row.rating
                row.rating = input_.rating
                row.rated_at = now
            stats.projected_at = now
            _refresh_average(stats)
            await uow.commit()
            return await self._summary(uow, stats, subject_id=sid, subject_type=input_.subject_type)
        raise RuntimeError("engagement rating command did not execute")

    async def withdraw_rating(self, input_: WithdrawRatingInput) -> EngagementSummaryDTO:
        target = await self._target(input_.content_id)
        sid = _subject(input_.subject_id)
        async with self._uow_factory() as uow:
            stats = await self._stats(uow, target)
            row = (
                (
                    await uow.session.execute(
                        select(ContentRating).where(
                            ContentRating.content_id == target.content_id,
                            ContentRating.subject_type == input_.subject_type,
                            ContentRating.subject_id == sid,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if row is not None and row.removed_at is None:
                row.removed_at = self._clock.utc_now()
                stats.rating_sum = max(0, int(stats.rating_sum) - int(row.rating))
                stats.rating_count = max(0, int(stats.rating_count) - 1)
            stats.projected_at = self._clock.utc_now()
            _refresh_average(stats)
            await uow.commit()
            return await self._summary(uow, stats, subject_id=sid, subject_type=input_.subject_type)
        raise RuntimeError("engagement rating withdrawal command did not execute")

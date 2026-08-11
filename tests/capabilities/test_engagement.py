from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from inc.capabilities.engagement.commands import (
    EngagementCommands,
    LikeContentInput,
    RateContentInput,
    RecordContentViewInput,
    UnlikeContentInput,
    WithdrawRatingInput,
)
from inc.capabilities.engagement.ports import ContentEngagementTarget


@dataclass
class _Reader:
    target: ContentEngagementTarget

    async def get(self, content_id: uuid.UUID) -> ContentEngagementTarget | None:
        return self.target if self.target.content_id == content_id else None


@pytest.mark.asyncio
async def test_views_are_incremented_and_keyed_replay_is_idempotent(uow_factory, clock):
    content_id = uuid.uuid4()
    reader = _Reader(
        ContentEngagementTarget(
            content_id=content_id,
            type_name="post",
            status="published",
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    commands = EngagementCommands(uow_factory=uow_factory, clock=clock, content_reader=reader)

    first = await commands.record_view(
        RecordContentViewInput(content_id=content_id, idempotency_key="view-1")
    )
    replay = await commands.record_view(
        RecordContentViewInput(content_id=content_id, idempotency_key="view-1")
    )
    unkeyed = await commands.record_view(RecordContentViewInput(content_id=content_id))

    assert first.counted is True
    assert replay.counted is False
    assert unkeyed.counted is True
    assert unkeyed.view_count == 2


@pytest.mark.asyncio
async def test_like_and_rating_support_revoke_change_and_half_up_average(uow_factory, clock):
    content_id = uuid.uuid4()
    subject_id = uuid.uuid4()
    reader = _Reader(
        ContentEngagementTarget(
            content_id=content_id,
            type_name="post",
            status="published",
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    commands = EngagementCommands(uow_factory=uow_factory, clock=clock, content_reader=reader)

    liked = await commands.like_content(
        LikeContentInput(content_id=content_id, subject_id=subject_id)
    )
    reliked = await commands.like_content(
        LikeContentInput(content_id=content_id, subject_id=subject_id)
    )
    assert liked.like_count == reliked.like_count == 1
    await commands.unlike_content(UnlikeContentInput(content_id=content_id, subject_id=subject_id))
    restored = await commands.like_content(
        LikeContentInput(content_id=content_id, subject_id=subject_id)
    )
    assert restored.like_count == 1

    first = await commands.rate_content(
        RateContentInput(content_id=content_id, subject_id=subject_id, rating=1)
    )
    same = await commands.rate_content(
        RateContentInput(content_id=content_id, subject_id=subject_id, rating=1)
    )
    changed = await commands.rate_content(
        RateContentInput(content_id=content_id, subject_id=subject_id, rating=2)
    )
    assert first.rating_average == Decimal("1.0")
    assert same.rating_sum == 1 and same.rating_count == 1
    assert changed.rating_sum == 2 and changed.rating_count == 1
    withdrawn = await commands.withdraw_rating(
        WithdrawRatingInput(content_id=content_id, subject_id=subject_id)
    )
    assert withdrawn.rating_count == 0
    assert withdrawn.rating_average is None


@pytest.mark.asyncio
async def test_only_published_content_is_engageable(uow_factory, clock):
    content_id = uuid.uuid4()
    reader = _Reader(
        ContentEngagementTarget(
            content_id=content_id,
            type_name="post",
            status="draft",
            published_at=None,
        )
    )
    commands = EngagementCommands(uow_factory=uow_factory, clock=clock, content_reader=reader)
    with pytest.raises(Exception, match="published"):
        await commands.record_view(RecordContentViewInput(content_id=content_id))

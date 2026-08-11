"""HTTP-neutral engagement DTOs and command inputs."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class EngagementSummaryDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_id: str
    view_count: int = 0
    like_count: int = 0
    rating_sum: int = 0
    rating_count: int = 0
    rating_average: Decimal | None = None
    viewer_liked: bool | None = None
    viewer_rating: int | None = None
    counted: bool | None = None


class RecordContentViewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_id: uuid.UUID
    idempotency_key: str | None = Field(default=None, max_length=200)


class LikeContentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_id: uuid.UUID
    subject_id: uuid.UUID | str
    subject_type: str = "user"


class UnlikeContentInput(LikeContentInput):
    pass


class RateContentInput(LikeContentInput):
    rating: int = Field(ge=1, le=5)


class WithdrawRatingInput(LikeContentInput):
    pass


class FavoriteDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_id: str
    type_name: str
    liked_at: datetime
    summary: EngagementSummaryDTO


class FavoritePageDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[FavoriteDTO]
    total: int
    page: int
    size: int

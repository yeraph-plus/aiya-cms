"""Comment kernel DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .models import CommentStatus

SLOT_COMMENT_STATS = "comment.stats"


class CommentCreate(BaseModel):
    target_type: str = Field(min_length=1, max_length=32)
    target_id: UUID
    parent_id: UUID | None = None
    content: str = Field(min_length=1, max_length=10000)
    data: dict[str, Any] = Field(default_factory=dict)


class CommentUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    data: dict[str, Any] | None = None


class CommentRead(BaseModel):
    id: UUID
    target_type: str
    target_id: UUID
    parent_id: UUID | None
    root_id: UUID | None
    depth: int
    owner_id: UUID
    status: CommentStatus
    content: str
    data: dict[str, Any]
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CommentThread(CommentRead):
    children: list[CommentThread] = Field(default_factory=list)


class CommentThreadQuery(BaseModel):
    q: str | None = Field(default=None, max_length=128)
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)
    sort: Literal["created_at", "updated_at"] = "created_at"
    order: Literal["asc", "desc"] = "asc"


class CommentStats(BaseModel):
    count: int = 0


CommentStatsDTO = CommentStats

ModerateAction = Literal["approve", "reject", "spam"]


class ModerateRequest(BaseModel):
    action: ModerateAction


class CommentModerationQuery(BaseModel):
    status: CommentStatus | None = None
    target_type: str | None = Field(default=None, max_length=32)
    target_id: UUID | None = None
    author_id: UUID | None = None
    q: str | None = Field(default=None, max_length=128)
    created_from: datetime | None = None
    created_to: datetime | None = None
    updated_from: datetime | None = None
    updated_to: datetime | None = None
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)
    sort: Literal["target_type", "status", "depth", "created_at", "updated_at"] = "created_at"
    order: Literal["asc", "desc"] = "desc"

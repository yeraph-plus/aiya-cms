"""HTTP-neutral comments DTOs and command inputs."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SubmitCommentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: str = Field(min_length=1, max_length=64)
    target_id: str = Field(min_length=1, max_length=200)
    author_type: str = Field(min_length=1, max_length=64)
    author_id: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None
    body: str = Field(min_length=1, max_length=5000)


class SubmitCommentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_id: uuid.UUID | None = None
    body: str = Field(min_length=1, max_length=5000)


class RejectCommentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


class DeleteCommentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=1000)


class CommentDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    target_type: str
    target_id: str
    author_type: str
    author_id: str
    parent_id: str | None = None
    body: str | None
    status: str
    moderation_reason: str | None = None
    submitted_at: datetime
    published_at: datetime | None = None
    rejected_at: datetime | None = None
    deleted_at: datetime | None = None
    version: int

"""Community DTOs and command inputs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CommunityAuthorDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    username: str | None = None
    display_name: str | None = None
    avatar_asset_id: str | None = None
    deleted: bool = False


class CreateDiscussionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_key: str = "general"
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)
    post_data: dict[str, Any] = Field(default_factory=dict)
    tag_ids: list[uuid.UUID] = Field(default_factory=list)


class CreateDiscussionInput(CreateDiscussionBody):
    author_type: str = Field(default="identity", min_length=1, max_length=64)
    author_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)


class UpdateDiscussionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    data: dict[str, Any] | None = None


class CreateReplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)


class CreateReplyInput(CreateReplyBody):
    discussion_id: uuid.UUID
    author_type: str = Field(default="identity", min_length=1, max_length=64)
    author_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)


class UpdatePostInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    body: str | None = Field(default=None, min_length=1)
    data: dict[str, Any] | None = None


class ReplaceDiscussionTagsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    tag_ids: list[uuid.UUID] = Field(default_factory=list)


class CreateTagInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern=r"^(primary|secondary)$")
    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    color: str | None = Field(default=None, max_length=32)
    icon_key: str | None = Field(default=None, max_length=64)
    parent_id: uuid.UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateTagInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    color: str | None = Field(default=None, max_length=32)
    icon_key: str | None = Field(default=None, max_length=64)
    parent_id: uuid.UUID | None = None
    metadata: dict[str, Any] | None = None


class ReorderTagsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag_ids: list[uuid.UUID]


class PurgeArchivedDiscussionsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = False


class DiscussionTagDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    name: str
    slug: str
    description: str | None = None
    color: str | None = None
    icon_key: str | None = None
    parent_id: str | None = None
    position: int
    status: str
    published_discussion_count: int = 0
    version: int = 1


class DiscussionDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    template_key: str
    schema_version: str
    title: str
    slug: str
    status: str
    author_type: str
    author_id: str
    author: CommunityAuthorDTO | None = None
    data: dict[str, Any]
    is_locked: bool
    locked_at: datetime | None = None
    locked_by_type: str | None = None
    locked_by_id: str | None = None
    first_post_id: str | None = None
    last_post_id: str | None = None
    reply_count: int
    last_posted_at: datetime | None = None
    version: int
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None
    hidden_at: datetime | None = None
    archived_at: datetime | None = None
    tags: list[DiscussionTagDTO] = Field(default_factory=list)
    search_rank: float | None = None


class PostDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    discussion_id: str
    number: int
    post_type: str
    status: str
    author_type: str
    author_id: str
    author: CommunityAuthorDTO | None = None
    body: str | None = None
    body_format: str = "markdown"
    body_profile: str = "gfm-v1"
    schema_version: str
    data: dict[str, Any] = Field(default_factory=dict)
    version: int
    created_at: datetime
    updated_at: datetime
    edited_at: datetime | None = None
    published_at: datetime | None = None
    hidden_at: datetime | None = None
    deleted_at: datetime | None = None


class CommunityPageDTO[T](BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[T]
    total: int
    page: int
    size: int


class TagDTO(DiscussionTagDTO):
    pass


class CommunityDiagnosticsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    status: str
    summary: str

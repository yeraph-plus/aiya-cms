"""Pydantic DTOs crossing the kernel Content boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator


class ContentDataValues(RootModel[dict[str, str]]):
    """Persisted content data; every value is a string by contract."""

    @model_validator(mode="before")
    @classmethod
    def reject_non_string_values(cls, value: Any) -> Any:
        if isinstance(value, dict) and any(not isinstance(item, str) for item in value.values()):
            raise ValueError("content data values must be strings")
        return value


class ContentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    slug: str = Field(min_length=1, max_length=256, pattern=r"^[a-z0-9][a-z0-9-]*$")
    content: str = ""
    excerpt: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class ContentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    slug: str | None = Field(
        default=None, min_length=1, max_length=256, pattern=r"^[a-z0-9][a-z0-9-]*$"
    )
    content: str | None = None
    excerpt: str | None = None
    comment_count: int | None = Field(default=None, ge=0)
    trashed_at: datetime | None = None
    data: dict[str, Any] | None = None


class ContentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: str
    title: str
    slug: str
    status: str
    owner_id: UUID
    content: str
    excerpt: str
    view_count: int
    like_count: int
    rating_sum: int
    rating_count: int
    comment_count: int
    data: dict[str, str]
    published_at: datetime | None
    trashed_at: datetime | None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ContentTypeRead(BaseModel):
    type_name: str
    default_status: str
    statuses: list[dict[str, Any]]
    transitions: list[dict[str, Any]]
    fields: list[dict[str, Any]]
    taxonomy_groups: list[dict[str, Any]]
    comment_policy: dict[str, Any]
    trash_policy: dict[str, Any]
    query: dict[str, Any]


class ContentListQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)
    terms: str | None = None
    q: str | None = Field(default=None, max_length=128)
    status: str | None = Field(default=None, max_length=32)
    owner_id: UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    updated_from: datetime | None = None
    updated_to: datetime | None = None
    published_from: datetime | None = None
    published_to: datetime | None = None
    sort: Literal[
        "title",
        "slug",
        "status",
        "published_at",
        "created_at",
        "updated_at",
        "view_count",
        "like_count",
        "rating_sum",
        "rating_count",
        "comment_count",
    ] = "created_at"
    order: Literal["asc", "desc"] = "desc"


TransitionAction = str

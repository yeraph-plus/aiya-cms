"""Kernel taxonomy DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

SLOT_TERM_FILTER = "taxonomy.term_filter"
SLOT_CONTENT_TERMS = "taxonomy.content_terms"


class TermCreate(BaseModel):
    group: str = Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    slug: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=128)
    data: dict[str, Any] = Field(default_factory=dict)


class TermUpdate(BaseModel):
    group: str | None = Field(default=None, min_length=1, max_length=32)
    slug: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    data: dict[str, Any] | None = None


class TermRead(BaseModel):
    id: UUID
    content_type: str
    group: str
    slug: str
    name: str
    data: dict[str, Any]
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TermAssign(BaseModel):
    term_ids: list[UUID] = Field(default_factory=list)


class TermListQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)
    q: str | None = Field(default=None, max_length=128)
    group: str | None = Field(default=None, max_length=32, pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    slug: str | None = Field(default=None, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    created_from: datetime | None = None
    created_to: datetime | None = None
    updated_from: datetime | None = None
    updated_to: datetime | None = None
    sort: Literal["group", "name", "slug", "created_at", "updated_at"] = "name"
    order: Literal["asc", "desc"] = "asc"


class ContentTerms(BaseModel):
    terms: list[TermRead] = Field(default_factory=list)


ContentTermsDTO = ContentTerms

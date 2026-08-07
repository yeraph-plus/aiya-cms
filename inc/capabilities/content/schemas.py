"""Content DTOs and command inputs.

Contract source: context/spec/capabilities/content.md.

DTOs carry the validated per-type data payload plus stable base fields.
Events are defined separately (events.py) and carry only summaries.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContentDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type_name: str
    schema_version: str
    title: str
    slug: str
    body: str | None = None
    excerpt: str | None = None
    status: str
    owner_type: str | None = None
    owner_id: str | None = None
    data: dict[str, Any]
    is_pinned: bool = False
    pin_rank: int = 0
    publish_at: datetime | None = None
    published_at: datetime | None = None
    schedule_version: int = 0
    version: int = 1
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ContentPageDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ContentDTO]
    total: int
    page: int
    size: int


class ReferenceDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    target_content_id: str
    kind: str
    position: int
    metadata: dict[str, Any]


class CreateContentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type_name: str
    title: str
    slug: str
    body: str | None = None
    excerpt: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    owner_id: uuid.UUID | None = None
    status: str | None = None


class UpdateContentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int
    title: str | None = None
    slug: str | None = None
    body: str | None = None
    excerpt: str | None = None
    data: dict[str, Any] | None = None


class ScheduleContentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publish_at: datetime


class SetContentPinInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_pinned: bool
    pin_rank: int = 0


class ReplaceReferencesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    targets: list[uuid.UUID] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PurgeResultDTO(BaseModel):
    """Result of the operations purge command (archive-only elsewhere)."""

    model_config = ConfigDict(extra="forbid")

    content_id: str
    type_name: str
    outgoing_references: int
    dry_run: bool

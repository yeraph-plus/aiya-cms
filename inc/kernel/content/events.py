"""Content kernel event payloads."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

CONTENT_EVENT_TYPES: tuple[str, ...] = (
    "content.created",
    "content.updated",
    "content.published",
    "content.trashed",
    "content.restored",
    "content.deleted",
    "content.viewed",
)


class ContentEventPayload(BaseModel):
    content_id: UUID
    type: str
    owner_id: UUID | None = None
    changed_fields: tuple[str, ...] = ()
    action: str | None = None
    purged: bool = False


class ContentViewedPayload(BaseModel):
    content_id: UUID
    type: str
    viewer_id: UUID | None = None

"""Comment kernel domain events."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

COMMENT_EVENT_TYPES: tuple[str, ...] = (
    "comment.created",
    "comment.updated",
    "comment.deleted",
    "comment.moderated",
)


class CommentEventPayload(BaseModel):
    comment_id: UUID
    target_type: str
    target_id: UUID
    owner_id: UUID | None = None
    actor_id: UUID | None = None
    changed_fields: tuple[str, ...] = ()
    count_delta: int = 0
    placeholder: bool = False
    physical: bool = False


class CommentModeratedPayload(BaseModel):
    comment_id: UUID
    target_type: str
    target_id: UUID
    owner_id: UUID | None = None
    action: str
    actor_id: UUID
    count_delta: int = 0

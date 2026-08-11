"""Versioned comments business events."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from inc.kernel.errors import validate_error_code


class CommentEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment_id: str
    target_type: str
    target_id: str
    author_type: str
    author_id: str
    parent_id: str | None = None
    status: str
    reason: str | None = None


COMMENT_EVENT_SCHEMAS: dict[str, type[BaseModel]] = {
    "comments.submitted.v1": CommentEventPayload,
    "comments.approved.v1": CommentEventPayload,
    "comments.rejected.v1": CommentEventPayload,
    "comments.deleted.v1": CommentEventPayload,
}

for _key in COMMENT_EVENT_SCHEMAS:
    validate_error_code(_key)

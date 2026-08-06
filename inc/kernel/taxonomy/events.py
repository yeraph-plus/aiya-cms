"""Taxonomy kernel event payloads."""

from uuid import UUID

from pydantic import BaseModel

TAXONOMY_EVENT_TYPES: tuple[str, ...] = (
    "term.created",
    "term.updated",
    "term.deleted",
    "term.assigned",
)


class TermEventPayload(BaseModel):
    term_id: UUID
    content_type: str
    group: str


class TermAssignedPayload(BaseModel):
    content_id: UUID
    term_ids: tuple[UUID, ...]
    actor_id: UUID

"""Versioned community business event payloads."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from inc.kernel.errors import validate_error_code


class CommunityEventPayload(BaseModel):
    """Safe summary payload; it never carries title, body or HTML."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1"
    discussion_id: str | None = None
    post_id: str | None = None
    tag_id: str | None = None
    status: str | None = None
    version: int | None = None
    is_locked: bool | None = None
    reply_count: int | None = None
    last_post_id: str | None = None
    last_posted_at: str | None = None
    tag_ids: tuple[str, ...] = ()
    kind: str | None = None
    source_version: int | None = None


COMMUNITY_EVENT_SCHEMAS: dict[str, type[BaseModel]] = {
    "community.discussion_created.v1": CommunityEventPayload,
    "community.discussion_updated.v1": CommunityEventPayload,
    "community.discussion_published.v1": CommunityEventPayload,
    "community.discussion_hidden.v1": CommunityEventPayload,
    "community.discussion_archived.v1": CommunityEventPayload,
    "community.discussion_lock_changed.v1": CommunityEventPayload,
    "community.post_created.v1": CommunityEventPayload,
    "community.post_published.v1": CommunityEventPayload,
    "community.post_hidden.v1": CommunityEventPayload,
    "community.post_deleted.v1": CommunityEventPayload,
    "community.tags_replaced.v1": CommunityEventPayload,
    "community.tag_created.v1": CommunityEventPayload,
    "community.tag_updated.v1": CommunityEventPayload,
    "community.tag_archived.v1": CommunityEventPayload,
}

for _key in COMMUNITY_EVENT_SCHEMAS:
    validate_error_code(_key)


def payload_for(key: str, **values: Any) -> dict[str, Any]:
    return COMMUNITY_EVENT_SCHEMAS[key].model_validate(values).model_dump(mode="json")

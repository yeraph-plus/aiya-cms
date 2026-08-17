"""Internal DTO conversion shared by commands and queries."""

from __future__ import annotations

from datetime import UTC
from typing import Any

from inc.capabilities.content.models import Content
from inc.capabilities.content.schemas import ContentDTO


def ensure_utc(value: Any) -> Any:
    """SQLite drops tzinfo; persisted times are always UTC."""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def to_dto(row: Content) -> ContentDTO:
    return ContentDTO(
        id=str(row.id),
        type_name=row.type_name,
        schema_version=row.schema_version,
        title=row.title,
        slug=row.slug,
        body=row.body,
        body_format="markdown",
        body_profile="gfm-v1",
        excerpt=row.excerpt,
        status=row.status,
        owner_type=row.owner_type,
        owner_id=str(row.owner_id) if row.owner_id is not None else None,
        data=dict(row.data.payload),
        is_pinned=row.is_pinned,
        pin_rank=row.pin_rank,
        publish_at=ensure_utc(row.publish_at) if row.publish_at is not None else None,
        published_at=ensure_utc(row.published_at) if row.published_at is not None else None,
        schedule_version=row.schedule_version,
        version=row.version,
        archived_at=ensure_utc(row.archived_at) if row.archived_at is not None else None,
        created_at=ensure_utc(row.created_at),
        updated_at=ensure_utc(row.updated_at),
    )

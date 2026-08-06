"""Content persistence models.

Contract source: context/spec/capabilities/content.md §3.

``owner_id`` is an opaque reference to identity subjects, never a foreign
key. ``data`` is bound to a Pydantic envelope; per-type validation happens
at the command boundary against the registered ContentTypeSpec. The
contents table carries scan leases so scheduled publish claims rows across
workers without a separate table.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin

PIN_RANK_MAX = 999


class ContentDataEnvelope(BaseModel):
    """Stable JSON envelope for type-specific content data."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    payload: dict[str, Any]


class ReferenceMetadata(BaseModel):
    """Schema-bound metadata carried by a content reference."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = None
    rel: str | None = None


@TableOwnership.owned_by("capability:content")
class Content(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "contents"

    type_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    owner_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    data: Mapped[ContentDataEnvelope] = mapped_column(
        JsonBModel(ContentDataEnvelope, "1"), nullable=False
    )
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pin_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    schedule_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("type_name", "slug", name="uq_contents_type_slug"),
        CheckConstraint("pin_rank >= 0 AND pin_rank <= 999", name="ck_contents_pin_rank_range"),
        CheckConstraint(
            "status != 'published' OR published_at IS NOT NULL",
            name="ck_contents_published_requires_time",
        ),
        CheckConstraint(
            "status != 'scheduled' OR publish_at IS NOT NULL",
            name="ck_contents_scheduled_requires_time",
        ),
        CheckConstraint(
            "status NOT IN ('draft', 'pending', 'rejected', 'archived') OR publish_at IS NULL",
            name="ck_contents_schedule_consistent",
        ),
        Index("ix_contents_pin_order", "is_pinned", "pin_rank", "published_at"),
    )


@TableOwnership.owned_by("capability:content")
class ContentReference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "content_references"

    source_content_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("contents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_content_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("contents.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ref_metadata: Mapped[ReferenceMetadata] = mapped_column(
        JsonBModel(ReferenceMetadata, "1"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "source_content_id",
            "target_content_id",
            "kind",
            name="uq_content_references_source_target_kind",
        ),
    )

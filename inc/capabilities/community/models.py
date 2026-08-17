"""Community-owned persistence models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
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


class DiscussionDataEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    payload: dict[str, Any] = Field(default_factory=dict)


class PostDataEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    payload: dict[str, Any] = Field(default_factory=dict)


class TagMetadataEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1"
    values: dict[str, Any] = Field(default_factory=dict)


class IdempotencyResultEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1"
    resource_type: str
    resource_id: str
    request_digest: str


@TableOwnership.owned_by("capability:community")
class CommunityDiscussion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "community_discussions"

    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    author_type: Mapped[str] = mapped_column(String(64), nullable=False)
    author_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    data: Mapped[DiscussionDataEnvelope] = mapped_column(
        JsonBModel(DiscussionDataEnvelope, "1"), nullable=False
    )
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    locked_by_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    first_post_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    last_post_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    reply_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("template_key", "slug", name="uq_community_discussions_template_slug"),
        CheckConstraint(
            "status IN ('draft', 'pending', 'published', 'hidden', 'archived')",
            name="ck_community_discussions_status",
        ),
        CheckConstraint("reply_count >= 0", name="ck_community_discussions_reply_count"),
        CheckConstraint("version >= 1", name="ck_community_discussions_version"),
        CheckConstraint(
            "status != 'published' OR (published_at IS NOT NULL AND first_post_id IS NOT NULL "
            "AND last_post_id IS NOT NULL AND last_posted_at IS NOT NULL)",
            name="ck_community_discussions_published_summary",
        ),
        Index(
            "ix_community_discussions_latest",
            "status",
            "last_posted_at",
            "id",
        ),
        Index(
            "ix_community_discussions_top",
            "status",
            "reply_count",
            "last_posted_at",
            "id",
        ),
        Index("ix_community_discussions_newest", "status", "created_at", "id"),
    )


@TableOwnership.owned_by("capability:community")
class CommunityPost(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "community_posts"

    discussion_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("community_discussions.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    post_type: Mapped[str] = mapped_column(String(16), nullable=False, default="comment")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    author_type: Mapped[str] = mapped_column(String(64), nullable=False)
    author_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    body_profile: Mapped[str] = mapped_column(String(32), nullable=False, default="gfm-v1")
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    data: Mapped[PostDataEnvelope] = mapped_column(
        JsonBModel(PostDataEnvelope, "1"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("discussion_id", "number", name="uq_community_posts_discussion_number"),
        CheckConstraint("number >= 1", name="ck_community_posts_number"),
        CheckConstraint("post_type = 'comment'", name="ck_community_posts_type"),
        CheckConstraint(
            "status IN ('pending', 'published', 'hidden', 'deleted')",
            name="ck_community_posts_status",
        ),
        CheckConstraint("version >= 1", name="ck_community_posts_version"),
        Index("ix_community_posts_public_stream", "discussion_id", "status", "number", "id"),
    )


@TableOwnership.owned_by("capability:community")
class CommunityTag(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "community_tags"

    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("community_tags.id", ondelete="RESTRICT"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    icon_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    metadata_: Mapped[TagMetadataEnvelope] = mapped_column(
        "metadata", JsonBModel(TagMetadataEnvelope, "1"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("kind IN ('primary', 'secondary')", name="ck_community_tags_kind"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_community_tags_status"),
        CheckConstraint("position >= 0", name="ck_community_tags_position"),
        CheckConstraint("version >= 1", name="ck_community_tags_version"),
        Index("ix_community_tags_parent_position", "kind", "parent_id", "position", "name", "id"),
    )


@TableOwnership.owned_by("capability:community")
class CommunityDiscussionTag(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "community_discussion_tags"

    discussion_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("community_discussions.id", ondelete="CASCADE"), nullable=False
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("community_tags.id", ondelete="RESTRICT"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("discussion_id", "tag_id", name="uq_community_discussion_tags_pair"),
        Index("ix_community_discussion_tags_discussion", "discussion_id", "position", "tag_id"),
        Index("ix_community_discussion_tags_tag", "tag_id", "discussion_id"),
    )


@TableOwnership.owned_by("capability:community")
class CommunitySearchDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "community_search_documents"

    discussion_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("community_discussions.id", ondelete="CASCADE"), nullable=False
    )
    post_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("community_posts.id", ondelete="CASCADE"), nullable=True
    )
    document_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    search_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("document_kind IN ('title', 'post')", name="ck_community_search_kind"),
        CheckConstraint("source_version >= 1", name="ck_community_search_source_version"),
        UniqueConstraint(
            "discussion_id", "document_kind", "post_id", name="uq_community_search_source"
        ),
        Index("ix_community_search_discussion_kind", "discussion_id", "document_kind"),
        Index(
            "ix_community_search_documents_trgm",
            "normalized_text",
            postgresql_using="gin",
            postgresql_ops={"normalized_text": "gin_trgm_ops"},
        ),
    )


Index(
    "uq_community_search_title_document",
    CommunitySearchDocument.discussion_id,
    unique=True,
    postgresql_where=CommunitySearchDocument.document_kind == "title",
    sqlite_where=CommunitySearchDocument.document_kind == "title",
)
Index(
    "uq_community_search_post_document",
    CommunitySearchDocument.post_id,
    unique=True,
    postgresql_where=CommunitySearchDocument.document_kind == "post",
    sqlite_where=CommunitySearchDocument.document_kind == "post",
)


@TableOwnership.owned_by("capability:community")
class CommunityIdempotencyRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "community_idempotency_records"

    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    result: Mapped[IdempotencyResultEnvelope] = mapped_column(
        JsonBModel(IdempotencyResultEnvelope, "1"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "scope",
            "idempotency_key_digest",
            name="uq_community_idempotency_scope_key",
        ),
        Index("ix_community_idempotency_created", "created_at"),
    )


# Short names keep capability-level callers independent from the persistence
# naming convention while the table owner remains explicit.
Discussion = CommunityDiscussion
Post = CommunityPost
Tag = CommunityTag
DiscussionTag = CommunityDiscussionTag
SearchDocument = CommunitySearchDocument

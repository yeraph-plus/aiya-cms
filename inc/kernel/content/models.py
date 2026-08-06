"""Kernel Content ORM models and their JSONB boundary."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TimestampMixin, new_uuid7

from .schemas import ContentDataValues


def _empty_data() -> ContentDataValues:
    return ContentDataValues.model_validate({})


class Content(Base, TimestampMixin):
    """One type-scoped content row; status remains a declaration-driven string."""

    __tablename__ = "contents"
    __table_args__ = (
        UniqueConstraint("type", "slug", name="uq_contents_type_slug"),
        Index("ix_contents_type_status", "type", "status", "published_at"),
        Index("ix_contents_type_updated", "type", "updated_at", "id"),
        Index("ix_contents_type_comment_count", "type", "comment_count", "id"),
        Index("ix_contents_data", "data", postgresql_using="gin"),
        {"extend_existing": True},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", server_default="draft"
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    view_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    like_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    rating_sum: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    rating_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    comment_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    data: Mapped[ContentDataValues] = mapped_column(
        JsonBModel(ContentDataValues), nullable=False, default=_empty_data
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

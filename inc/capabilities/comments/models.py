"""Comments-owned persistence models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin


@TableOwnership.owned_by("capability:comments")
class Comment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "comments"

    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(200), nullable=False)
    author_type: Mapped[str] = mapped_column(String(64), nullable=False)
    author_id: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("comments.id"), nullable=True, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    moderation_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'published', 'rejected', 'deleted')",
            name="ck_comments_status",
        ),
        CheckConstraint("version >= 1", name="ck_comments_version"),
        Index("ix_comments_target_status", "target_type", "target_id", "status"),
        Index("ix_comments_author", "author_type", "author_id"),
        Index("ix_comments_admin_order", "submitted_at", "id"),
    )

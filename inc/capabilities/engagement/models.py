"""Engagement projection and fact tables.

No table has a foreign key to ``contents``: the capability boundary uses the
opaque content id and a composition-provided reader port.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin


@TableOwnership.owned_by("capability:engagement")
class ContentEngagementStats(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "engagement_content_stats"

    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True)
    type_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content_status: Mapped[str] = mapped_column(String(16), nullable=False, default="published")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    view_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    like_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rating_sum: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rating_average: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    projection_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    projected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("view_count >= 0", name="ck_engagement_stats_view_count"),
        CheckConstraint("like_count >= 0", name="ck_engagement_stats_like_count"),
        CheckConstraint("rating_sum >= 0", name="ck_engagement_stats_rating_sum"),
        CheckConstraint("rating_count >= 0", name="ck_engagement_stats_rating_count"),
        Index("ix_engagement_stats_sort", "content_status", "published_at", "content_id"),
    )


@TableOwnership.owned_by("capability:engagement")
class ContentView(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "engagement_content_views"

    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    idempotency_key_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "content_id", "idempotency_key_digest", name="uq_engagement_view_idempotency"
        ),
    )


@TableOwnership.owned_by("capability:engagement")
class ContentLike(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "engagement_content_likes"

    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    liked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "content_id", "subject_type", "subject_id", name="uq_engagement_like_subject"
        ),
        Index("ix_engagement_like_active", "content_id", "removed_at"),
    )


@TableOwnership.owned_by("capability:engagement")
class ContentRating(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "engagement_content_ratings"

    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    rated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "content_id", "subject_type", "subject_id", name="uq_engagement_rating_subject"
        ),
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_engagement_rating_range"),
    )

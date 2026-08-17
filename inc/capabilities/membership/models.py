"""Membership persistence models.

Contract source: context/spec/capabilities/membership.md §2/§3.

Levels are code/ops declarations mirrored into the DB (like points
behaviors); subscriptions hold the current cycle, status and the granted
points snapshot for display/reconciliation. Subject refs are opaque; the
granted points live in points buckets, never here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin

SUBSCRIPTION_STATES = ("active", "expired", "cancelled")


class LevelMetadata(BaseModel):
    """Schema-bound metadata envelope for level declarations."""

    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] = {}


@TableOwnership.owned_by("capability:membership")
class MembershipLevel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "membership_levels"

    level_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    tier_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    cycle_days: Mapped[int] = mapped_column(Integer, nullable=False)
    grant_points: Mapped[int] = mapped_column(Integer, nullable=False)
    renewal_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    data: Mapped[LevelMetadata] = mapped_column(JsonBModel(LevelMetadata, "1"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


@TableOwnership.owned_by("capability:membership")
class MembershipSubscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "membership_subscriptions"

    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    level_key: Mapped[str] = mapped_column(String(100), nullable=False)
    cycle_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cycle_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    granted_points: Mapped[int] = mapped_column(Integer, nullable=False)
    renewal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("subject_type", "subject_id", name="uq_membership_subscription_subject"),
    )


@TableOwnership.owned_by("capability:membership")
class MembershipRenewalRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "membership_renewal_records"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("membership_subscriptions.id"), nullable=False, index=True
    )
    cycle_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cycle_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    granted_points: Mapped[int] = mapped_column(Integer, nullable=False)
    points_source_id: Mapped[str] = mapped_column(String(200), nullable=False)
    points_entry_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="granted")

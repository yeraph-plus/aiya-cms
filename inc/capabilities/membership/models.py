"""Membership persistence models.

Contract source: context/spec/capabilities/membership.md §2/§4.

Membership owns the subscription and cycle facts only.  The points entry
reference is an opaque value returned by the user-center workflow; it is not
a relationship to another capability's tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin

SUBSCRIPTION_STATES = (
    "pending_activation",
    "active",
    "expired",
    "cancelled",
    "terminated",
    "failed",
)
CYCLE_STATES = ("prepared", "activated", "failed")


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

    @property
    def cycle_points_amount(self) -> int:
        """Expose the contract name while retaining the existing admin column."""

        return self.grant_points


@TableOwnership.owned_by("capability:membership")
class MembershipSubscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "membership_subscriptions"

    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    level_key: Mapped[str] = mapped_column(String(100), nullable=False)
    cycle_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cycle_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending_activation")
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Kept for the existing administrator response shape; this is the current
    # cycle's immutable amount snapshot, not a ledger or balance.
    granted_points: Mapped[int] = mapped_column(Integer, nullable=False)
    renewal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cycle_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("subject_type", "subject_id", name="uq_membership_subscription_subject"),
    )


@TableOwnership.owned_by("capability:membership")
class MembershipCycle(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable membership-cycle snapshot and activation fact."""

    __tablename__ = "membership_cycles"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("membership_subscriptions.id"), nullable=False, index=True
    )
    level_key: Mapped[str] = mapped_column(String(100), nullable=False)
    cycle_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cycle_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cycle_points_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="prepared", index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    points_entry_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    attach_idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(200), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint(
            "subscription_id",
            "idempotency_key",
            name="uq_membership_cycle_subscription_idempotency",
        ),
    )

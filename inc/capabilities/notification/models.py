"""Notification persistence models.

Contract source: context/spec/capabilities/notification.md §3.

Recipient snapshots are masked/tokenized personal data: the digest allows
stability checks and the masked form supports audit, while delivery always
re-resolves the live address through the RecipientResolver Port.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin

DELIVERY_STATES = (
    "pending",
    "sending",
    "delivered",
    "unknown",
    "failed",
    "dead",
    "cancelled",
)


class IntentVariables(BaseModel):
    """Schema-bound variables envelope (validated per NotificationSpec)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    values: dict[str, Any] = {}


class RecipientSnapshot(BaseModel):
    """Masked recipient reference; never the raw address."""

    model_config = ConfigDict(extra="forbid")

    channel: str
    recipient_type: str
    recipient_id: str
    address_digest: str
    masked_address: str


@TableOwnership.owned_by("capability:notification")
class NotificationTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notification_templates"

    template_key: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(String(5000), nullable=False)
    variables_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

    __table_args__ = (
        UniqueConstraint(
            "template_key",
            "version",
            "channel",
            "locale",
            name="uq_notification_templates_key_version_channel_locale",
        ),
    )


@TableOwnership.owned_by("capability:notification")
class NotificationIntent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notification_intents"

    spec_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    recipient_type: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    variables: Mapped[IntentVariables] = mapped_column(
        JsonBModel(IntentVariables, "1"), nullable=False
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "spec_key", "idempotency_key", name="uq_notification_intents_spec_idempotency"
        ),
    )


@TableOwnership.owned_by("capability:notification")
class NotificationDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notification_deliveries"

    intent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("notification_intents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient: Mapped[RecipientSnapshot] = mapped_column(
        JsonBModel(RecipientSnapshot, "1"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    provider_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_notification_deliveries_due", "status", "next_retry_at"),)


@TableOwnership.owned_by("capability:notification")
class NotificationDeliveryAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One provider invocation within a logical delivery attempt."""

    __tablename__ = "notification_delivery_attempts"

    delivery_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("notification_deliveries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    delivery_attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "delivery_id",
            "delivery_attempt",
            "provider_sequence",
            name="uq_notification_delivery_attempts_sequence",
        ),
    )

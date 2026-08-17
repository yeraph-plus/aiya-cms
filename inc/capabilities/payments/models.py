"""Payments persistence models.

Contract source: context/spec/capabilities/payments.md §3.

Order references are public, unguessable; provider ids are never local
primary keys. Subject is an opaque reference with no cross-capability FK.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin

ORDER_STATES = (
    "created",
    "pending",
    "captured",
    "partially_refunded",
    "refunded",
    "cancelled",
    "failed",
)
ATTEMPT_STATES = ("pending", "succeeded", "failed", "unknown")


class OfferSnapshot(BaseModel):
    """Immutable purchase snapshot provided by the feature."""

    model_config = ConfigDict(extra="forbid")

    offer_key: str
    offer_version: str
    description: str


class RequestDigestData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] = {}


@TableOwnership.owned_by("capability:payments")
class PaymentOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payment_orders"

    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    order_reference: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    offer: Mapped[OfferSnapshot] = mapped_column(JsonBModel(OfferSnapshot, "1"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="created", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    captured_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refunded_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        CheckConstraint("currency = 'CNY'", name="ck_payment_orders_currency_cny"),
        UniqueConstraint(
            "provider_key", "idempotency_key", name="uq_payment_orders_provider_idempotency"
        ),
    )


@TableOwnership.owned_by("capability:payments")
class PaymentAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payment_attempts"

    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("payment_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    request_digest: Mapped[RequestDigestData] = mapped_column(
        JsonBModel(RequestDigestData, "1"), nullable=False
    )
    error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)


@TableOwnership.owned_by("capability:payments")
class PaymentWebhookReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payment_webhook_receipts"

    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processing_state: Mapped[str] = mapped_column(String(16), nullable=False, default="verified")
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("payment_orders.id"), nullable=True, index=True
    )

    __table_args__ = (
        UniqueConstraint("provider_key", "event_id", name="uq_payment_webhook_provider_event"),
    )


@TableOwnership.owned_by("capability:payments")
class PaymentRefund(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payment_refunds"

    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("payment_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    refund_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("currency = 'CNY'", name="ck_payment_refunds_currency_cny"),
        UniqueConstraint(
            "order_id", "idempotency_key", name="uq_payment_refunds_order_idempotency"
        ),
    )

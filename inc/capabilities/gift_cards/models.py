"""Gift card persistence models.

All references to subjects and providers are opaque.  No identity, points or
membership table is imported here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    column,
)
from sqlalchemy.orm import Mapped, mapped_column

from inc.capabilities.gift_cards.schemas import FulfillmentPayload
from inc.kernel.db import Base, JsonBModel, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin

CARD_STATES = ("issued", "reserved", "redeemed", "revoked", "expired")
BATCH_STATES = ("active", "closed", "revoked")
REDEMPTION_STATES = ("reserved", "committed", "cancelled", "expired")


@TableOwnership.owned_by("capability:gift_cards")
class GiftCardBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "gift_card_batches"

    batch_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    platform_key: Mapped[str] = mapped_column(String(64), nullable=False)
    product_key: Mapped[str] = mapped_column(String(100), nullable=False)
    fulfillment_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    fulfillment_key: Mapped[str] = mapped_column(String(200), nullable=False)
    fulfillment_payload: Mapped[FulfillmentPayload] = mapped_column(
        JsonBModel(FulfillmentPayload, "1"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_gift_card_batches_quantity_positive"),
        CheckConstraint("generated_count >= 0", name="ck_gift_card_batches_generated_nonnegative"),
        CheckConstraint(
            "status IN ('active', 'closed', 'revoked')", name="ck_gift_card_batches_status"
        ),
    )


@TableOwnership.owned_by("capability:gift_cards")
class GiftCard(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "gift_cards"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("gift_card_batches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    platform_key: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_digest: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="issued", index=True)
    redemption_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    reserved_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint(
            "status IN ('issued', 'reserved', 'redeemed', 'revoked', 'expired')",
            name="ck_gift_cards_status",
        ),
        CheckConstraint("version >= 1", name="ck_gift_cards_version"),
    )


@TableOwnership.owned_by("capability:gift_cards")
class GiftCardExternalClaim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "gift_card_external_claims"

    platform_key: Mapped[str] = mapped_column(String(64), nullable=False)
    external_order_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    product_key: Mapped[str] = mapped_column(String(100), nullable=False)
    fulfillment_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    fulfillment_key: Mapped[str] = mapped_column(String(200), nullable=False)
    fulfillment_payload: Mapped[FulfillmentPayload] = mapped_column(
        JsonBModel(FulfillmentPayload, "1"), nullable=False
    )
    provider_fact_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_status: Mapped[str] = mapped_column(String(32), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    redemption_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)

    __table_args__ = (
        UniqueConstraint(
            "platform_key", "external_order_digest", name="uq_gift_card_external_order"
        ),
    )


@TableOwnership.owned_by("capability:gift_cards")
class GiftCardRedemption(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "gift_card_redemptions"

    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[str] = mapped_column(String(200), nullable=False)
    platform_key: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False)
    fulfillment_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    fulfillment_key: Mapped[str] = mapped_column(String(200), nullable=False)
    fulfillment_payload: Mapped[FulfillmentPayload] = mapped_column(
        JsonBModel(FulfillmentPayload, "1"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="reserved", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    reserved_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "platform_key", "idempotency_key", name="uq_gift_card_redemption_idempotency"
        ),
        Index(
            "uq_gift_card_redemption_active_source",
            "source_kind",
            "source_id",
            unique=True,
            postgresql_where=column("status").in_(("reserved", "committed")),
            sqlite_where=column("status").in_(("reserved", "committed")),
        ),
        CheckConstraint(
            "source_kind IN ('internal', 'external')", name="ck_gift_card_redemption_source"
        ),
        CheckConstraint(
            "status IN ('reserved', 'committed', 'cancelled', 'expired')",
            name="ck_gift_card_redemption_status",
        ),
    )

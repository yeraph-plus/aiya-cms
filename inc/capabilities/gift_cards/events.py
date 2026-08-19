"""Gift card event payload schemas (all sensitive values are digests/opaque ids)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from inc.kernel.errors import validate_error_code


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform_key: str
    product_key: str


class BatchCreatedPayload(_Base):
    batch_id: str
    batch_key: str
    quantity: int
    expires_at: datetime | None = None


class BatchClosedPayload(_Base):
    batch_id: str
    reason: str


class ProviderPurchaseRecordedPayload(_Base):
    claim_id: str
    provider_fact_digest: str
    external_order_digest: str
    quantity: int


class RedemptionPayload(_Base):
    redemption_id: str
    source_kind: str
    source_id: str
    subject_type: str
    subject_id: str
    status: str


class CardRevokedPayload(_Base):
    card_id: str
    batch_id: str
    reason: str


GIFT_CARD_EVENT_SCHEMAS: dict[str, type[BaseModel]] = {
    "gift_cards.batch_created.v1": BatchCreatedPayload,
    "gift_cards.batch_closed.v1": BatchClosedPayload,
    "gift_cards.provider_purchase_recorded.v1": ProviderPurchaseRecordedPayload,
    "gift_cards.redemption_reserved.v1": RedemptionPayload,
    "gift_cards.redemption_committed.v1": RedemptionPayload,
    "gift_cards.redemption_cancelled.v1": RedemptionPayload,
    "gift_cards.card_revoked.v1": CardRevokedPayload,
}

for _key in GIFT_CARD_EVENT_SCHEMAS:
    validate_error_code(_key)

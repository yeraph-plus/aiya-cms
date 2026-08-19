"""Boundary DTOs for the gift cards capability."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FulfillmentPayload(BaseModel):
    """Versioned, immutable entitlement snapshot.

    The values are intentionally opaque to this capability.  A later feature
    may interpret them as membership or points instructions.
    """

    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] = Field(default_factory=dict)


class GenerateGiftCardBatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: int = Field(gt=0, le=10_000)
    product_key: str = Field(min_length=1, max_length=100)
    fulfillment_schema_version: str = Field(min_length=1, max_length=32)
    fulfillment_key: str = Field(min_length=1, max_length=200)
    fulfillment_payload: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    idempotency_key: str = Field(min_length=1, max_length=200)
    platform_key: str = Field(default="card_platform", min_length=1, max_length=64)
    batch_key: str | None = Field(default=None, min_length=1, max_length=100)


class CloseGiftCardBatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str
    reason: str = Field(min_length=1, max_length=500)


class RevokeGiftCardInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_id: str
    reason: str = Field(min_length=1, max_length=500)
    expected_version: int = Field(default=1, ge=1)


class ReserveGiftCardRedemptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: str = Field(min_length=1, max_length=500)
    subject_type: str = Field(min_length=1, max_length=64)
    subject_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=200)
    platform_key: str | None = Field(default=None, min_length=1, max_length=64)


class VerifyGiftCardInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: str = Field(min_length=1, max_length=500)
    platform_key: str = Field(default="card_platform", min_length=1, max_length=64)


class CommitGiftCardRedemptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    redemption_id: str
    idempotency_key: str = Field(min_length=1, max_length=200)


class CancelGiftCardRedemptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    redemption_id: str
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ProviderPurchaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform_key: str = Field(min_length=1, max_length=64)
    external_order_id: str = Field(min_length=1, max_length=500)
    provider_fact_id: str = Field(min_length=1, max_length=200)
    paid: bool
    product_key: str = Field(min_length=1, max_length=100)
    fulfillment_schema_version: str = Field(min_length=1, max_length=32)
    fulfillment_key: str = Field(min_length=1, max_length=200)
    fulfillment_payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime
    expires_at: datetime | None = None
    idempotency_key: str = Field(min_length=1, max_length=200)
    batch_id: str | None = None
    quantity: int = Field(default=1, gt=0, le=10_000)


class GiftCardBatchDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    batch_key: str
    platform_key: str
    product_key: str
    fulfillment_schema_version: str
    fulfillment_key: str
    quantity: int
    generated_count: int
    available_count: int
    redeemed_count: int
    revoked_count: int
    expires_at: datetime | None
    status: str
    idempotency_key: str
    created_by: str | None
    created_at: datetime
    closed_at: datetime | None


class GiftCardBatchResultDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch: GiftCardBatchDTO
    # Present only on the original generation response.  It is never stored
    # and an idempotent replay intentionally returns ``None``.
    secrets: list[str] | None = None


class GiftCardDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    batch_id: str
    platform_key: str
    status: str
    redemption_id: str | None
    reserved_until: datetime | None
    redeemed_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    version: int


class RedemptionDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_kind: Literal["internal", "external"]
    source_id: str
    platform_key: str
    subject_type: str
    subject_id: str
    fulfillment_schema_version: str
    fulfillment_key: str
    fulfillment_payload: dict[str, Any]
    status: str
    idempotency_key: str
    reserved_until: datetime | None
    committed_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime


class GiftCardVerifyDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    platform_key: str | None = None
    product_key: str | None = None
    fulfillment_schema_version: str | None = None
    fulfillment_key: str | None = None
    expires_at: datetime | None = None
    reason: str | None = None

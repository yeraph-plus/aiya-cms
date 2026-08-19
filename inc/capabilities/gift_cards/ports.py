"""Provider boundary for external gift-card platforms."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from inc.kernel.errors import ErrorCategory, KernelError


@dataclass(frozen=True, slots=True)
class GiftCardSettingsSnapshot:
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GiftCardAvailability:
    available: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class GiftCardPurchaseRequest:
    platform_key: str
    external_order_id: str
    product_key: str
    quantity: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ProviderPurchaseFact:
    platform_key: str
    external_order_id: str
    provider_fact_id: str
    paid: bool
    product_key: str
    fulfillment_schema_version: str
    fulfillment_key: str
    fulfillment_payload: dict[str, Any]
    occurred_at: datetime
    expires_at: datetime | None = None
    idempotency_key: str = ""
    quantity: int = 1


@dataclass(frozen=True, slots=True)
class PurchaseSession:
    provider_key: str
    reference: str
    url: str | None = None


@dataclass(frozen=True, slots=True)
class GiftCardWebhookRequest:
    method: str
    raw_body: bytes
    headers: dict[str, str]
    query_params: dict[str, str]


class GiftCardPlatformPort(Protocol):
    key: str

    async def check_availability(
        self, snapshot: GiftCardSettingsSnapshot
    ) -> GiftCardAvailability: ...

    async def start_purchase(
        self, request: GiftCardPurchaseRequest, snapshot: GiftCardSettingsSnapshot
    ) -> PurchaseSession | None: ...

    async def lookup_purchase(
        self, secret: str, context: dict[str, Any], snapshot: GiftCardSettingsSnapshot
    ) -> ProviderPurchaseFact: ...

    async def verify_webhook(
        self, request: GiftCardWebhookRequest, snapshot: GiftCardSettingsSnapshot
    ) -> ProviderPurchaseFact: ...

    async def acknowledge_webhook(
        self, fact: ProviderPurchaseFact, snapshot: GiftCardSettingsSnapshot
    ) -> None: ...


class GiftCardProviderError(KernelError):
    """Provider failures are dependency errors and safe to expose."""

    def __init__(self, message: str = "gift card provider unavailable") -> None:
        super().__init__(
            code="gift_cards.provider_unavailable",
            category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
            message=message,
        )

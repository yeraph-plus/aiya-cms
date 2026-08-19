"""Gift-card issuance and redemption fact capability.

The public surface intentionally excludes ORM models.  A future feature may
consume the redemption DTO/commands to fulfil membership or points, but this
capability never imports those siblings.
"""

from __future__ import annotations

from inc.capabilities.gift_cards.commands import (
    CancelGiftCardRedemption,
    CloseGiftCardBatch,
    CommandContext,
    CommitGiftCardRedemption,
    GenerateGiftCardBatch,
    RecordProviderPurchase,
    RecordProviderWebhook,
    ReserveGiftCardRedemption,
    RevokeGiftCard,
    digest_secret,
)
from inc.capabilities.gift_cards.diagnostics import GiftCardDiagnostics
from inc.capabilities.gift_cards.ports import (
    GiftCardAvailability,
    GiftCardPlatformPort,
    GiftCardProviderError,
    GiftCardPurchaseRequest,
    GiftCardSettingsSnapshot,
    GiftCardWebhookRequest,
    ProviderPurchaseFact,
    PurchaseSession,
)
from inc.capabilities.gift_cards.queries import GiftCardQueries
from inc.capabilities.gift_cards.schemas import (
    CancelGiftCardRedemptionInput,
    CommitGiftCardRedemptionInput,
    RedemptionDTO,
    ReserveGiftCardRedemptionInput,
)

__all__ = [
    "CancelGiftCardRedemption",
    "CancelGiftCardRedemptionInput",
    "CloseGiftCardBatch",
    "CommitGiftCardRedemption",
    "CommitGiftCardRedemptionInput",
    "CommandContext",
    "GenerateGiftCardBatch",
    "GiftCardAvailability",
    "GiftCardDiagnostics",
    "GiftCardPlatformPort",
    "GiftCardProviderError",
    "GiftCardPurchaseRequest",
    "GiftCardQueries",
    "GiftCardSettingsSnapshot",
    "GiftCardWebhookRequest",
    "ProviderPurchaseFact",
    "PurchaseSession",
    "RecordProviderPurchase",
    "RecordProviderWebhook",
    "RedemptionDTO",
    "ReserveGiftCardRedemption",
    "ReserveGiftCardRedemptionInput",
    "RevokeGiftCard",
    "digest_secret",
]

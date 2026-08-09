"""Point purchase HTTP DTOs.

Contract source: context/spec/features.md §4.4, http-openapi.md §3.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class OfferDTO(BaseModel):
    """One trusted server-side offer (clients pick offer_key only)."""

    model_config = ConfigDict(extra="forbid")

    offer_key: str
    version: str
    description: str
    amount: int
    currency: str
    points_amount: int


class OfferListDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[OfferDTO]


class PurchaseOrderDTO(BaseModel):
    """Purchase workflow checkout view returned at start (and on replay)."""

    model_config = ConfigDict(extra="forbid")

    order_reference: str
    checkout_url: str
    state: str


class WebhookReceiptDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    received: bool
    duplicate: bool = False

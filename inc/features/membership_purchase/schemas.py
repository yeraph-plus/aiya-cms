"""Membership purchase HTTP DTOs.

Contract source: context/spec/features.md (membership purchase),
http-openapi.md §3.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class MembershipOfferDTO(BaseModel):
    """One trusted server-side offer (clients pick offer_key only)."""

    model_config = ConfigDict(extra="forbid")

    offer_key: str
    version: str
    description: str
    amount: int
    currency: str
    level_key: str


class MembershipOfferListDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MembershipOfferDTO]


class MembershipPurchaseOrderDTO(BaseModel):
    """Purchase workflow checkout view returned at start (and on replay)."""

    model_config = ConfigDict(extra="forbid")

    order_reference: str
    checkout_url: str
    state: str

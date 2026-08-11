"""Point purchase feature: captured payment -> points credit.

Contract source: context/spec/features.md §4.4.

The purchase workflow creates a payment order, starts the provider
attempt, waits on a durable capture signal and credits points with the
order reference as the idempotency domain. A refund signal drives the
reversal workflow. Credits never change the payment fact: a failed credit
retries and the order stays captured.

Prices are server-side trusted: clients only select an ``offer_key``;
amount/currency/points are resolved from the registered offer catalog
(never accepted from the client).
"""

from __future__ import annotations

from dataclasses import dataclass

from inc.capabilities.points import PointBehaviorSpec
from inc.kernel.boot import FeatureSpec

spec = FeatureSpec(name="point_purchase", version="1", requires=("payments", "points"))


@dataclass(frozen=True, slots=True)
class PointOffer:
    """Trusted server-side purchase price, versioned and immutable."""

    offer_key: str
    version: str
    description: str
    amount: int  # minor units, e.g. cents
    currency: str
    points_amount: int


POINT_OFFERS: dict[str, PointOffer] = {
    "points_pack_100": PointOffer(
        offer_key="points_pack_100",
        version="1",
        description="100 points",
        amount=1000,
        currency="CNY",
        points_amount=100,
    ),
}


def require_offer(offer_key: str) -> PointOffer:
    try:
        return POINT_OFFERS[offer_key]
    except KeyError as exc:
        raise KeyError(f"unknown point purchase offer {offer_key!r}") from exc


behavior_specs = (
    PointBehaviorSpec(
        key="purchase.completed.credit",
        version="1",
        program_key="credit",
        direction="credit",
        min_amount=1,
        max_amount=1_000_000,
        allowed_source_types=("payment",),
        expiration_days=365,
    ),
)

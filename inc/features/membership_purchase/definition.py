"""Membership purchase feature: payment order -> capture -> subscribe.

Contract source: context/spec/features.md (membership purchase integration),
context/spec/capabilities/membership.md §10.

The purchase workflow creates a payment order, starts the provider attempt,
waits on a durable capture signal and then calls SubscribeLevel, which
grants the cycle quota through the PointsLedger Port into points' expiring
buckets. Payments never touches membership or points; membership never
touches payments: this feature assembles the three.

Prices are server-side trusted: clients only select an ``offer_key``;
amount/currency/level are resolved from the registered offer catalog.
"""

from __future__ import annotations

from dataclasses import dataclass

from inc.capabilities.membership import MembershipLevelSpec
from inc.capabilities.points import PointBehaviorSpec
from inc.kernel.boot import FeatureSpec

spec = FeatureSpec(
    name="membership_purchase",
    version="1",
    requires=("payments", "membership", "points"),
)

GRANT_BEHAVIOR = "membership.grant"


@dataclass(frozen=True, slots=True)
class MembershipOffer:
    """Trusted server-side price for one membership level, versioned."""

    offer_key: str
    version: str
    description: str
    amount: int  # minor units, e.g. cents
    currency: str
    level_key: str


MEMBERSHIP_OFFERS: dict[str, MembershipOffer] = {
    "membership_basic_30": MembershipOffer(
        offer_key="membership_basic_30",
        version="1",
        description="Basic membership, 30 days",
        amount=3000,
        currency="CNY",
        level_key="basic",
    ),
}

level_specs = (
    MembershipLevelSpec(
        key="basic",
        display_name="Basic",
        tier_rank=1,
        cycle_days=30,
        grant_points=100,
    ),
)

behavior_specs = (
    PointBehaviorSpec(
        key=GRANT_BEHAVIOR,
        version="1",
        program_key="default",
        direction="credit",
        min_amount=1,
        max_amount=1_000_000,
        allowed_source_types=("membership",),
    ),
)


def require_offer(offer_key: str) -> MembershipOffer:
    try:
        return MEMBERSHIP_OFFERS[offer_key]
    except KeyError as exc:
        raise KeyError(f"unknown membership offer {offer_key!r}") from exc

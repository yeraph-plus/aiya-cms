"""Gift cards capability declaration.

The capability owns card issuance and redemption facts only.  Membership and
points fulfilment is deliberately left to a future feature workflow.
"""

from __future__ import annotations

from inc.kernel.boot import CapabilitySpec

spec = CapabilitySpec(
    name="gift_cards",
    schema_version="1",
    access_keys=(
        "gift_cards.batch_generate",
        "gift_cards.manage",
        "gift_cards.verify",
        "gift_cards.redeem",
        "gift_cards.reconcile",
    ),
)

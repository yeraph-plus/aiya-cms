"""Membership subscription -> points grant behavior.

This feature intentionally contains no payment workflow.  It only declares
the stable behavior used by the membership capability's PointsLedger port,
which lets the release administration surface grant a subscription quota safely.
"""

from __future__ import annotations

from inc.capabilities.points import PointBehaviorSpec
from inc.kernel.boot import FeatureSpec

spec = FeatureSpec(
    name="membership_grants",
    version="1",
    requires=("membership", "points"),
)

behavior_specs = (
    PointBehaviorSpec(
        key="membership.grant",
        version="1",
        program_key="credit",
        direction="credit",
        min_amount=1,
        max_amount=1_000_000,
        allowed_source_types=("membership",),
    ),
)

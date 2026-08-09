"""Check-in feature: daily reward behavior declaration.

Contract source: context/spec/features.md §4.3.

Explicit user action only; the reward idempotency domain is
subject + program + local business date (timezone from the behavior
spec). Reading the homepage or logging in never triggers it.
"""

from __future__ import annotations

from inc.capabilities.points import PointBehaviorSpec
from inc.kernel.boot import FeatureSpec

spec = FeatureSpec(name="check_in", version="1", requires=("points",))

behavior_specs = (
    PointBehaviorSpec(
        key="daily_check_in.reward",
        version="1",
        program_key="default",
        direction="credit",
        fixed_amount=10,
        daily_limit=1,
        business_timezone="Asia/Shanghai",
        expiration_days=30,
    ),
)

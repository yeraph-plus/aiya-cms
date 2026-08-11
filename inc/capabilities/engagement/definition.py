"""Engagement capability declaration."""

from inc.kernel.boot import CapabilitySpec

spec = CapabilitySpec(
    name="engagement",
    schema_version="1",
    access_keys=(
        "engagement.read",
        "engagement.view",
        "engagement.like",
        "engagement.rate",
        "engagement.manage",
        "engagement.rebuild",
    ),
    requires=("content",),
)

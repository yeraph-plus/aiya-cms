"""Membership capability: levels, subscription cycles, renewal and expiry.

Contract source: context/spec/capabilities/membership.md.

Membership grants points quota through the PointsLedger Port into points'
expiring buckets (expires_at = subscription end); it never computes
remaining balances or settlement itself. It imports no sibling capability:
subjects are opaque references and points are reached only through the
Ports bound by the composition root.
"""

from __future__ import annotations

from inc.kernel.boot import CapabilitySpec

spec = CapabilitySpec(
    name="membership",
    schema_version="1",
    access_keys=(
        "membership.manage",
        "membership.read",
        "membership.levels.read",
        "membership.levels.manage",
    ),
)

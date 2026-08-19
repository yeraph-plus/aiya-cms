"""Membership capability: levels, subscription cycles, renewal and expiry.

Contract source: context/spec/capabilities/membership.md.

Membership owns level, subscription and cycle facts. The user-center feature
coordinates points grants and returns only an opaque entry reference.
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
        "membership.subscriptions.read",
        "membership.subscriptions.manage",
    ),
)

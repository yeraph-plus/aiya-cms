"""Points capability: programs, accounts, immutable ledger and behaviors.

Contract source: context/spec/capabilities/points.md.

Points knows nothing about posts, check-ins or payment SDKs; those
semantics arrive through behavior codes, source references and feature
workflows.
"""

from __future__ import annotations

from inc.kernel.boot import CapabilitySpec

spec = CapabilitySpec(
    name="points",
    schema_version="1",
    access_keys=(
        "points.read",
        "points.adjust",
        "points.freeze",
        "points.rebuild",
    ),
)

"""Taxonomy capability: flat multi-dimensional labels.

Contract source: context/spec/capabilities/taxonomy.md.

Mark any target type without importing it; dimensions are declared by
features, terms and assignments are maintained here.
"""

from __future__ import annotations

from inc.kernel.boot import CapabilitySpec

spec = CapabilitySpec(
    name="taxonomy",
    schema_version="1",
    access_keys=(
        "taxonomy.read",
        "taxonomy.manage",
    ),
)

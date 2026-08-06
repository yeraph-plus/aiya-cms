"""Content capability: generic content entity, types, transitions,
scheduling, pinning and references.

Contract source: context/spec/capabilities/content.md.

Content type declarations belong to features; this capability validates
and executes them. It imports neither taxonomy nor assets: dimensions are
managed by the taxonomy capability, and asset ids are opaque references.
"""

from __future__ import annotations

from inc.kernel.boot import CapabilitySpec

spec = CapabilitySpec(
    name="content",
    schema_version="1",
    access_keys=(
        "content.read",
        "content.write",
        "content.schedule",
        "content.publish",
        "content.archive",
        "content.pin",
        "content.purge",
        "content.manage",
    ),
)

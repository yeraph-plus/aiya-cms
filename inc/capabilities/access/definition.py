"""Access capability: roles, permission keys, authorization decisions.

Contract source: context/spec/capabilities/access.md.

Access interprets permission keys registered by capabilities/features; it
never authenticates, signs tokens or owns user tables. Subjects are opaque
references validated through the SubjectExists Port.
"""

from __future__ import annotations

from inc.kernel.boot import CapabilitySpec

spec = CapabilitySpec(
    name="access",
    schema_version="1",
    access_keys=(
        "access.roles.read",
        "access.roles.manage",
        "access.roles.assign",
        "access.bootstrap",
        "access.dashboard.read",
    ),
)

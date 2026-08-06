"""Assets capability: external object storage references.

Contract source: context/spec/capabilities/assets.md.

Manages stable references and SDK interactions; never stores binaries,
signed URLs or provider credentials.
"""

from __future__ import annotations

from inc.kernel.boot import CapabilitySpec

spec = CapabilitySpec(
    name="assets",
    schema_version="1",
    access_keys=(
        "assets.read",
        "assets.upload",
        "assets.manage",
        "assets.delete",
    ),
)

"""Archive capability declaration."""

from __future__ import annotations

from inc.kernel.boot import CapabilitySpec

spec = CapabilitySpec(
    name="archive",
    schema_version="1",
    access_keys=(
        "archive.items.read",
        "archive.items.manage",
        "archive.items.verify",
        "archive.grants.read",
        "archive.grants.issue",
        "archive.grants.activate",
        "archive.grants.revoke",
        "archive.delivery.resolve",
        "archive.download",
    ),
)

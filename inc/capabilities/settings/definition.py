"""Settings capability: structured, registered configuration groups.

Contract source: context/spec/capabilities/settings.md.

No secrets, no arbitrary key/value CRUD, no database scripts; reads of
missing rows return validated code defaults without writing.
"""

from __future__ import annotations

from inc.kernel.boot import CapabilitySpec

spec = CapabilitySpec(
    name="settings",
    schema_version="1",
    access_keys=(
        "settings.read",
        "settings.update",
        "settings.seo.update",
    ),
)

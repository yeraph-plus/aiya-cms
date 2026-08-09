"""Identity capability: user subjects, login identifiers, credentials.

Contract source: context/spec/capabilities/identity.md.

identity owns user lifecycle and local credentials. It imports neither
access, OIDC, assets nor notification: role checks and protocol flows are
composed by features/api, and email side effects belong to notification
workflows.
"""

from __future__ import annotations

from inc.kernel.boot import CapabilitySpec

spec = CapabilitySpec(
    name="identity",
    schema_version="1",
    access_keys=(
        "identity.users.read",
        "identity.users.update",
        "identity.users.ban",
        "identity.users.unban",
        "identity.users.delete",
    ),
)

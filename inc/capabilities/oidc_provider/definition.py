"""OIDC Provider capability: protocol endpoints, clients, token lifecycle.

Contract source: context/spec/capabilities/oidc-provider.md.

OIDC defines and consumes its own Ports (SubjectAuthenticator,
SubjectClaimsReader, AuthorizationDecisionReader, SecurityEventSubscriber);
the composition root binds them with identity/access adapters. OIDC never
imports sibling capabilities or their tables.
"""

from __future__ import annotations

from inc.kernel.boot import CapabilitySpec

spec = CapabilitySpec(
    name="oidc_provider",
    schema_version="1",
    access_keys=(
        "oidc_provider.clients.read",
        "oidc_provider.clients.manage",
        "oidc_provider.grants.revoke",
    ),
)

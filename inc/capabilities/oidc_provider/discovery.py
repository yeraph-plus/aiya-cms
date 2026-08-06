"""OIDC Discovery document.

Contract source: context/spec/capabilities/oidc-provider.md §3.

All URLs derive from the canonical issuer; claims describe exactly what
this deployment supports.
"""

from __future__ import annotations

from typing import Any

from inc.capabilities.oidc_provider.services import (
    SUPPORTED_CLAIMS,
    SUPPORTED_GRANT_TYPES,
    SUPPORTED_RESPONSE_TYPES,
    SUPPORTED_SCOPES,
)


class DiscoveryService:
    def __init__(self, *, issuer: str) -> None:
        self._issuer = issuer.rstrip("/")

    def configuration(self) -> dict[str, Any]:
        return {
            "issuer": self._issuer,
            "authorization_endpoint": f"{self._issuer}/oidc/authorize",
            "token_endpoint": f"{self._issuer}/oidc/token",
            "userinfo_endpoint": f"{self._issuer}/oidc/userinfo",
            "jwks_uri": f"{self._issuer}/oidc/jwks",
            "revocation_endpoint": f"{self._issuer}/oidc/revoke",
            "end_session_endpoint": f"{self._issuer}/oidc/logout",
            "response_types_supported": list(SUPPORTED_RESPONSE_TYPES),
            "grant_types_supported": list(SUPPORTED_GRANT_TYPES),
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "token_endpoint_auth_methods_supported": ["none", "client_secret_basic"],
            "token_endpoint_auth_signing_alg_values_supported": ["RS256"],
            "scopes_supported": list(SUPPORTED_SCOPES),
            "claims_supported": list(SUPPORTED_CLAIMS),
            "code_challenge_methods_supported": ["S256"],
            "revocation_endpoint_auth_methods_supported": ["none", "client_secret_basic"],
            "introspection_endpoint_auth_methods_supported": ["none", "client_secret_basic"],
        }

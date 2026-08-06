"""OIDC Provider capability: protocol endpoints, clients, token lifecycle.

Contract source: context/spec/capabilities/oidc-provider.md.

Public surface for the composition root: key services, the protocol
services/context, security-event consumption, diagnostics and the session
revoker bound to the SecurityEventSubscriber Port.
"""

from __future__ import annotations

from inc.capabilities.oidc_provider.handlers import OidcDiagnostics, SecurityEventRevoker
from inc.capabilities.oidc_provider.keys import InMemorySigningKeyStore, KeyService
from inc.capabilities.oidc_provider.services import (
    AuthorizationService,
    LogoutService,
    RevocationService,
    ServiceContext,
    TokenService,
    UserInfoService,
)
from inc.capabilities.oidc_provider.sessions import OidcSessionRevoker

__all__ = [
    "AuthorizationService",
    "InMemorySigningKeyStore",
    "KeyService",
    "LogoutService",
    "OidcDiagnostics",
    "OidcSessionRevoker",
    "RevocationService",
    "SecurityEventRevoker",
    "ServiceContext",
    "TokenService",
    "UserInfoService",
]

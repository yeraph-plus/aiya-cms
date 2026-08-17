"""OIDC Provider capability: protocol endpoints, clients, token lifecycle.

Contract source: context/spec/capabilities/oidc-provider.md.

Public surface for the composition root: key services, the protocol
services/context, security-event consumption, diagnostics and the session
revoker bound to the SecurityEventSubscriber Port.
"""

from __future__ import annotations

from inc.capabilities.oidc_provider.clients import (
    ClientCommandContext,
    ClientQueries,
    DisableClient,
    EnableClient,
    RegisterClient,
    RotateClientSecret,
    UpdateClient,
)
from inc.capabilities.oidc_provider.handlers import OidcDiagnostics, SecurityEventRevoker
from inc.capabilities.oidc_provider.keys import KeyService, load_public_key, verify_jwt
from inc.capabilities.oidc_provider.services import (
    AuthorizationService,
    GrantConsentService,
    LogoutService,
    RevocationService,
    ServiceContext,
    TokenService,
    UserInfoService,
)
from inc.capabilities.oidc_provider.sessions import OidcSessionRevoker

__all__ = [
    "AuthorizationService",
    "ClientQueries",
    "ClientCommandContext",
    "DisableClient",
    "EnableClient",
    "GrantConsentService",
    "KeyService",
    "load_public_key",
    "LogoutService",
    "OidcDiagnostics",
    "OidcSessionRevoker",
    "RegisterClient",
    "RevocationService",
    "SecurityEventRevoker",
    "ServiceContext",
    "TokenService",
    "RotateClientSecret",
    "UpdateClient",
    "UserInfoService",
    "verify_jwt",
]

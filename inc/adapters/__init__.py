"""Adapter library (``inc/adapters``).

Adapters implement capability Ports (``NotificationProvider``,
``PaymentProvider``, ``ObjectStorageProvider``, plus the identity/auth
adapters in ``registry.py``); they own SDK clients, credentials, timeouts
and error normalization. Grouped by capability so the composition root can
pick implementations explicitly per manifest. Usable from ``inc/api`` and
``inc/features``; capability code must never import this package.
Placeholders for planned integrations declare their target Port and stay
side-effect free until implemented.
"""

from inc.adapters.registry import (
    AccessAuthorizationReader,
    ContentBatchExists,
    IdentityClaimsReader,
    IdentityCommunityAuthor,
    IdentityCredentialAuthenticator,
    ProviderCatalog,
    ProviderRegistration,
    ProviderResolver,
    TaxonomyContentExists,
    resolve_adapters,
    resolve_provider_catalogs,
)

__all__ = [
    "AccessAuthorizationReader",
    "ContentBatchExists",
    "IdentityCommunityAuthor",
    "IdentityClaimsReader",
    "IdentityCredentialAuthenticator",
    "ProviderCatalog",
    "ProviderRegistration",
    "ProviderResolver",
    "resolve_provider_catalogs",
    "TaxonomyContentExists",
    "resolve_adapters",
]

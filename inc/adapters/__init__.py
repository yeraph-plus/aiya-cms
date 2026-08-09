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
    IdentityCredentialAuthenticator,
    InMemoryObjectStorage,
    TaxonomyContentExists,
    resolve_adapters,
)

__all__ = [
    "AccessAuthorizationReader",
    "ContentBatchExists",
    "IdentityClaimsReader",
    "IdentityCredentialAuthenticator",
    "InMemoryObjectStorage",
    "TaxonomyContentExists",
    "resolve_adapters",
]

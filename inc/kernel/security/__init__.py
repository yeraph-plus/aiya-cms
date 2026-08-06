"""Business-agnostic cryptography, signing and key loading primitives.

Contract source: context/spec/kernel/foundation.md §5.

Kernel security does not define login, OIDC tokens, scopes, clients or user
credential state; those belong to capabilities. It only provides upgradeable
primitives and Ports.
"""

from __future__ import annotations

from inc.kernel.security.hashing import Argon2PasswordHasher, PasswordHasher
from inc.kernel.security.redaction import MASK, is_secret_key, redact
from inc.kernel.security.signing import HmacSigner, KeyLoader, KeyRef, Signer
from inc.kernel.security.tokens import constant_time_compare, random_bytes, random_token

__all__ = [
    "Argon2PasswordHasher",
    "HmacSigner",
    "KeyLoader",
    "KeyRef",
    "MASK",
    "PasswordHasher",
    "Signer",
    "constant_time_compare",
    "is_secret_key",
    "random_bytes",
    "random_token",
    "redact",
]

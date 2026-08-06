"""Random token and constant-time comparison primitives.

Contract source: context/spec/kernel/foundation.md §3/§5.

Random opaque values (protocol nonces, refresh tokens) come from the
CSPRNG; UUIDs are never treated as secrets.
"""

from __future__ import annotations

import hmac
import secrets


def constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison for secrets."""

    return hmac.compare_digest(a, b)


def random_bytes(nbytes: int = 32) -> bytes:
    return secrets.token_bytes(nbytes)


def random_token(nbytes: int = 32) -> str:
    """URL-safe random token (CSPRNG)."""

    return secrets.token_urlsafe(nbytes)

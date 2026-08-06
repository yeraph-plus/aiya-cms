"""Signing and key loading primitives.

Contract source: context/spec/kernel/foundation.md §5.

Kernel provides the business-agnostic Signer/KeyLoader contracts and an
HMAC adapter. Asymmetric signing keys, key rotation windows and kid
handling belong to the oidc_provider capability.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class KeyRef:
    """Stable reference to a cryptographic key."""

    key_id: str
    algorithm: str


class Signer(Protocol):
    """Signs and verifies byte messages."""

    def sign(self, data: bytes) -> bytes: ...

    def verify(self, data: bytes, signature: bytes) -> bool: ...


class KeyLoader(Protocol):
    """Resolves a KeyRef to a Signer."""

    def load(self, key_ref: KeyRef) -> Signer: ...


class HmacSigner:
    """HMAC-SHA256 signer over a raw key."""

    algorithm = "hmac-sha256"

    def __init__(self, key: bytes) -> None:
        if not key:
            raise ValueError("HMAC key must not be empty")
        self._key = key

    def sign(self, data: bytes) -> bytes:
        return hmac.new(self._key, data, hashlib.sha256).digest()

    def verify(self, data: bytes, signature: bytes) -> bool:
        expected = self.sign(data)
        return hmac.compare_digest(expected, signature)

"""Password hashing Port and approved adapter.

Contract source: context/spec/kernel/foundation.md §5.

The encoded hash carries its algorithm version; verifying a legacy hash and
deciding to rehash is a Command decision owned by the identity capability.
"""

from __future__ import annotations

from typing import Protocol

import pwdlib


class PasswordHasher(Protocol):
    """Hashes and verifies passwords with an upgradeable algorithm."""

    def hash(self, password: str) -> str: ...

    def verify(self, password: str, encoded: str) -> bool: ...

    def needs_rehash(self, encoded: str) -> bool: ...


class Argon2PasswordHasher:
    """Argon2 adapter over pwdlib's recommended parameters."""

    def __init__(self) -> None:
        self._hasher = pwdlib.PasswordHash.recommended()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password: str, encoded: str) -> bool:
        try:
            return self._hasher.verify(password, encoded)
        except (AttributeError, TypeError, ValueError, pwdlib.exceptions.PwdlibError) as _exc:
            del _exc
            # Unrecognized, malformed or corrupted stored hash must degrade to
            # a failed login, never crash the auth flow.
            return False

    def needs_rehash(self, encoded: str) -> bool:
        """True when the encoded hash uses another algorithm or parameters."""

        try:
            if not self._hasher.current_hasher.identify(encoded):
                return True
            return self._hasher.current_hasher.check_needs_rehash(encoded)
        except (AttributeError, TypeError, ValueError, pwdlib.exceptions.PwdlibError) as _exc:
            del _exc
            # A malformed/corrupted hash cannot be verified; rehashing (or a
            # subsequent failed login) is the safe direction.
            return True

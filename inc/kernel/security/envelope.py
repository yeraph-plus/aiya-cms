"""Small authenticated envelope for sensitive, short-lived values.

The kernel owns only the cryptographic primitive.  Capabilities decide which
business fields are sensitive and when their encrypted values may be scrubbed.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from inc.kernel.security.redaction import is_secret_key

_PREFIX = "enc:v1:"


@dataclass(frozen=True, slots=True)
class SensitiveValueProtector:
    """Encrypt and decrypt short-lived secret-bearing mapping values."""

    _fernet: Fernet

    @classmethod
    def from_secret(cls, secret: str) -> SensitiveValueProtector:
        if not secret or not secret.strip():
            raise ValueError("sensitive value protection requires a non-empty secret")
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        return cls(Fernet(base64.urlsafe_b64encode(digest)))

    def protect_mapping(self, values: dict[str, Any]) -> dict[str, Any]:
        return self._map(values, reveal=False)

    def reveal_mapping(self, values: dict[str, Any]) -> dict[str, Any]:
        return self._map(values, reveal=True)

    def scrub_mapping(self, values: dict[str, Any]) -> dict[str, Any]:
        """Remove secret-bearing fields once delivery reaches a terminal state."""

        return {key: value for key, value in values.items() if not is_secret_key(str(key))}

    def _map(self, values: dict[str, Any], *, reveal: bool) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values.items():
            if isinstance(value, dict):
                result[key] = self._map(value, reveal=reveal)
                continue
            if is_secret_key(str(key)) and isinstance(value, str):
                result[key] = self._reveal(value) if reveal else self._protect(value)
            else:
                result[key] = value
        return result

    def _protect(self, value: str) -> str:
        if value.startswith(_PREFIX):
            return value
        return _PREFIX + self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def _reveal(self, value: str) -> str:
        if not value.startswith(_PREFIX):
            raise ValueError("sensitive value is not protected")
        try:
            return self._fernet.decrypt(value.removeprefix(_PREFIX).encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
            raise ValueError("sensitive value could not be decrypted") from exc


__all__ = ["SensitiveValueProtector"]

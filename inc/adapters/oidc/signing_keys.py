"""Filesystem-backed OIDC private signing keys.

Private PEM material lives outside PostgreSQL on a deployment-owned volume.
Files are written atomically with owner-only permissions; the database keeps
only the public JWK and lifecycle metadata owned by the OIDC capability.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _b64u(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class FileSigningKeyStore:
    """A KeyRef adapter over an owner-only directory."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self._directory = Path(directory)

    def _path(self, kid: str) -> Path:
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        if not kid or any(char not in allowed for char in kid):
            raise ValueError("OIDC signing key id is not filesystem-safe")
        return self._directory / f"{kid}.pem"

    def _ensure_directory(self) -> None:
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            self._directory.chmod(0o700)
        except OSError:
            if os.name != "nt":
                raise

    async def generate(self, kid: str) -> tuple[Any, dict[str, Any]]:
        self._ensure_directory()
        target = self._path(kid)
        if target.exists():
            raise FileExistsError(f"OIDC signing key already exists: {kid}")
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        temporary = target.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(pem)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            target.chmod(0o600)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

        numbers = private.public_key().public_numbers()
        return private, {
            "kty": "RSA",
            "kid": kid,
            "alg": "RS256",
            "use": "sig",
            "n": _b64u(numbers.n),
            "e": _b64u(numbers.e),
        }

    async def load_private(self, kid: str) -> Any | None:
        path = self._path(kid)
        if not path.exists():
            return None
        return serialization.load_pem_private_key(path.read_bytes(), password=None)

    async def drop_private(self, kid: str) -> None:
        self._path(kid).unlink(missing_ok=True)

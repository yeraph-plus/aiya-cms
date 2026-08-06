"""Argon2id password hashing primitives."""

from pwdlib import PasswordHash

_PASSWORD_HASHER = PasswordHash.recommended()


def hash_password(plain: str) -> str:
    """Return an Argon2id hash; plaintext is never retained by this module."""

    if not plain:
        raise ValueError("password must not be empty")
    return _PASSWORD_HASHER.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password, treating malformed hashes as a normal mismatch."""

    if not plain or not hashed:
        return False
    try:
        return _PASSWORD_HASHER.verify(plain, hashed)
    except Exception:
        return False

"""Security primitive tests (foundation.md §5)."""

from __future__ import annotations

from pydantic import SecretStr

from inc.kernel.security import (
    Argon2PasswordHasher,
    HmacSigner,
    KeyRef,
    constant_time_compare,
    random_bytes,
    random_token,
    redact,
)


def test_argon2_roundtrip_and_rehash() -> None:
    hasher = Argon2PasswordHasher()
    encoded = hasher.hash("correct horse battery staple")
    assert hasher.verify("correct horse battery staple", encoded)
    assert not hasher.verify("wrong", encoded)
    assert not hasher.needs_rehash(encoded)
    assert hasher.needs_rehash("$1$legacy$hash")  # different algorithm family


def test_argon2_malformed_hash_degrades_to_failed_login() -> None:
    """A malformed/legacy stored hash must not crash the auth flow."""
    hasher = Argon2PasswordHasher()
    assert hasher.verify("pw", "$1$legacy$hash") is False
    assert hasher.verify("pw", "$argon2id$v=19$m=65536,t=3,p=4$broken") is False
    assert hasher.verify("pw", None) is False  # type: ignore[arg-type]
    assert hasher.needs_rehash("$1$legacy$hash") is True
    assert hasher.needs_rehash("$argon2id$v=19$m=65536,t=3,p=4$broken") is True
    assert hasher.needs_rehash(None) is True  # type: ignore[arg-type]


def test_argon2_hashes_are_salted() -> None:
    hasher = Argon2PasswordHasher()
    assert hasher.hash("same") != hasher.hash("same")


def test_constant_time_compare() -> None:
    assert constant_time_compare("abc", "abc")
    assert not constant_time_compare("abc", "abd")
    assert not constant_time_compare("", "abc")


def test_random_token_is_urlsafe_and_unique() -> None:
    tokens = {random_token() for _ in range(100)}
    assert len(tokens) == 100
    assert all("+" not in t and "/" not in t for t in tokens)
    assert len(random_bytes(8)) == 8


def test_hmac_signer_roundtrip() -> None:
    signer = HmacSigner(b"key-material")
    data = b"payload"
    signature = signer.sign(data)
    assert signer.verify(data, signature)
    assert not signer.verify(b"tampered", signature)
    assert not signer.verify(data, b"forged")


def test_hmac_signer_rejects_empty_key() -> None:
    try:
        HmacSigner(b"")
    except ValueError:
        return
    raise AssertionError("empty key must be rejected")


def test_key_ref_is_business_free() -> None:
    ref = KeyRef(key_id="k1", algorithm="hmac-sha256")
    assert ref.key_id == "k1"
    assert ref.algorithm == "hmac-sha256"


def test_redact_nested_and_secret_values() -> None:
    payload = {
        "user_id": "u1",
        "password": "hunter2",
        "client_secret": "s3cret",
        "nested": {"api_key": "ak-123", "safe": "kept", "authorization": "Bearer x"},
        "list": ["a", "b"],
        "deep": {"token": "t"},
    }
    masked = redact(payload)
    assert masked["password"] == "[REDACTED]"
    assert masked["client_secret"] == "[REDACTED]"
    assert masked["nested"]["api_key"] == "[REDACTED]"
    assert masked["nested"]["authorization"] == "[REDACTED]"
    assert masked["nested"]["safe"] == "kept"
    assert masked["deep"]["token"] == "[REDACTED]"
    assert masked["list"] == ["a", "b"]
    assert masked["user_id"] == "u1"


def test_redact_masks_broader_credential_keys() -> None:
    payload = {
        "aws_access_key_id": "AKIA...",
        "access_key": "acc-1",
        "consumer_key": "cons-1",
        "passphrase": "phrase",
        "passcode": "1234",
        "pwd": "pw",
        "safe_key": "not-secret",
    }
    masked = redact(payload)
    assert masked["aws_access_key_id"] == "[REDACTED]"
    assert masked["access_key"] == "[REDACTED]"
    assert masked["consumer_key"] == "[REDACTED]"
    assert masked["passphrase"] == "[REDACTED]"
    assert masked["passcode"] == "[REDACTED]"
    assert masked["pwd"] == "[REDACTED]"
    assert masked["safe_key"] == "not-secret"


def test_redact_handles_pydantic_secret() -> None:
    assert redact({"value": SecretStr("hunter2")})["value"] == "[REDACTED]"

"""Production OIDC private-key adapter contracts."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from inc.adapters.oidc.signing_keys import FileSigningKeyStore


async def test_file_signing_key_store_persists_and_drops_private_key(tmp_path: Path) -> None:
    store = FileSigningKeyStore(tmp_path)

    generated, public_jwk = await store.generate("key-2026_08")
    loaded = await store.load_private("key-2026_08")

    assert loaded is not None
    assert loaded.private_numbers() == generated.private_numbers()
    assert public_jwk["kid"] == "key-2026_08"
    assert public_jwk["kty"] == "RSA"
    key_path = tmp_path / "key-2026_08.pem"
    assert key_path.read_bytes().startswith(b"-----BEGIN PRIVATE KEY-----")
    if os.name != "nt":
        assert key_path.stat().st_mode & 0o777 == 0o600

    await store.drop_private("key-2026_08")
    assert await store.load_private("key-2026_08") is None


@pytest.mark.parametrize("kid", ("", "../escape", "nested/key", "space key"))
async def test_file_signing_key_store_rejects_unsafe_key_ids(tmp_path: Path, kid: str) -> None:
    store = FileSigningKeyStore(tmp_path)

    with pytest.raises(ValueError, match="filesystem-safe"):
        await store.generate(kid)

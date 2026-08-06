"""Security primitive contract tests (see context/spec/kernel.md)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from pydantic import SecretStr

from inc.kernel.config import Settings
from inc.kernel.errors import AppError, clear_registry, register_error_codes
from inc.kernel.security import (
    AUTH_002,
    AUTH_003,
    AUTH_CODES,
    Principal,
    TokenService,
    hash_password,
    hash_refresh,
    verify_password,
)


@pytest.fixture(autouse=True)
def register_auth_codes() -> None:
    clear_registry()
    register_error_codes(*AUTH_CODES)
    yield


def _settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        jwt_secret=SecretStr("test-secret-that-is-long-enough-for-tests"),
        **overrides,
    )


def test_argon2_password_hash_roundtrip_and_mismatch() -> None:
    plain = "correct horse battery staple"
    hashed = hash_password(plain)

    assert hashed.startswith("$argon2")
    assert plain not in hashed
    assert verify_password(plain, hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password(plain, "not-a-hash")


def test_access_token_contains_claims_and_roundtrips() -> None:
    principal = Principal(
        id=uuid4(),
        username="alice",
        roles=frozenset({"admin", "editor"}),
        capabilities=frozenset({"content:create"}),
    )
    service = TokenService(_settings())

    token = service.issue_access(principal)
    claims = service.verify_access(token)

    assert claims.sub == principal.id
    assert claims.roles == principal.roles
    assert claims.capabilities == principal.capabilities
    assert claims.type == "access"
    decoded = jwt.decode(token, options={"verify_signature": False})
    assert set(decoded) >= {"sub", "roles", "capabilities", "iat", "exp", "type"}


def test_access_token_expired_tampered_and_wrong_type_are_invalid() -> None:
    settings = _settings()
    service = TokenService(settings)
    base = {
        "sub": str(uuid4()),
        "roles": [],
        "capabilities": [],
        "iat": datetime.now(UTC) - timedelta(minutes=2),
        "exp": datetime.now(UTC) - timedelta(minutes=1),
        "type": "access",
    }
    expired = jwt.encode(base, settings.jwt_secret.get_secret_value(), algorithm="HS256")
    with pytest.raises(AppError) as expired_error:
        service.verify_access(expired)
    assert expired_error.value.code == AUTH_002

    with pytest.raises(AppError) as tampered_error:
        service.verify_access(expired + "tampered")
    assert tampered_error.value.code == AUTH_003

    base["exp"] = datetime.now(UTC) + timedelta(minutes=1)
    base["type"] = "refresh"
    wrong_type = jwt.encode(base, settings.jwt_secret.get_secret_value(), algorithm="HS256")
    with pytest.raises(AppError) as type_error:
        service.verify_access(wrong_type)
    assert type_error.value.code == AUTH_003


def test_refresh_is_opaque_and_only_hash_is_persisted() -> None:
    service = TokenService(_settings())
    raw, digest = service.issue_refresh(uuid4())

    assert raw
    assert digest == hash_refresh(raw)
    assert digest != raw
    assert len(digest) == 64


def test_anonymous_principal_has_no_authority() -> None:
    anonymous = Principal.anonymous()
    assert anonymous.is_anonymous
    assert anonymous.roles == frozenset()
    assert anonymous.capabilities == frozenset()

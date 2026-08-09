"""Signing key lifecycle and JWT cryptography.

Contract source: context/spec/capabilities/oidc-provider.md §10.

Only one active signing key exists at a time; retired keys remain in JWKS
until all signed tokens' maximum lifetime plus clock skew has passed. The
private key never enters the database — a SigningKeyStore Port (dev
in-memory store, later file/KMS loaders) holds it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

import jwt as pyjwt
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from inc.capabilities.oidc_provider.models import OidcSigningKey, PublicJwk
from inc.capabilities.oidc_provider.schemas import OidcError
from inc.kernel.db import UoWFactory
from inc.kernel.time import Clock

ALGORITHM_ALLOWLIST = ("RS256",)
MAX_TOKEN_LIFETIME_SECONDS = 3600 * 24
CLOCK_SKEW_SECONDS = 60
KEY_RETENTION_SECONDS = MAX_TOKEN_LIFETIME_SECONDS + CLOCK_SKEW_SECONDS


@dataclass(frozen=True, slots=True)
class ActiveSigningKey:
    kid: str
    private_key: Any
    algorithm: str = "RS256"


class SigningKeyStore(Protocol):
    """Holds private key material outside the database."""

    async def generate(self, kid: str) -> tuple[Any, dict[str, Any]]:
        """Generate a key pair; returns (private, public_jwk_dict)."""

        ...

    async def load_private(self, kid: str) -> Any | None: ...

    async def drop_private(self, kid: str) -> None: ...


class InMemorySigningKeyStore:
    """Dev/test adapter: ephemeral RSA-2048 keys in process memory."""

    def __init__(self) -> None:
        self._keys: dict[str, Any] = {}

    async def generate(self, kid: str) -> tuple[Any, dict[str, Any]]:
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = private.public_key()
        numbers = public.public_numbers()
        public_jwk = {
            "kty": "RSA",
            "kid": kid,
            "alg": "RS256",
            "use": "sig",
            "n": _b64u(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
            "e": _b64u(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
        }
        self._keys[kid] = private
        return private, public_jwk

    async def load_private(self, kid: str) -> Any | None:
        return self._keys.get(kid)

    async def drop_private(self, kid: str) -> None:
        self._keys.pop(kid, None)


def _b64u(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class KeyService:
    """Active key selection, rotation and JWKS publication."""

    def __init__(
        self,
        *,
        uow_factory: UoWFactory,
        store: SigningKeyStore,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._store = store
        self._clock = clock

    async def ensure_active_key(self) -> ActiveSigningKey:  # type: ignore[return]
        async with self._uow_factory() as uow:
            row = (
                (
                    await uow.session.execute(
                        select(OidcSigningKey)
                        .where(OidcSigningKey.status == "active")
                        .with_for_update()
                    )
                )
                .scalars()
                .first()
            )
            if row is not None:
                private = await self._store.load_private(row.kid)
                if private is not None:
                    return ActiveSigningKey(
                        kid=row.kid, private_key=private, algorithm=row.algorithm
                    )
                # Private material lost: retire and generate a replacement.
                row.status = "retired"
                row.retire_at = self._clock.utc_now()
                # Retention is anchored to retirement, not creation: the
                # replacement must keep verifying tokens signed by this key
                # for the full retention window after it stops signing.
                row.delete_at = row.retire_at + timedelta(seconds=KEY_RETENTION_SECONDS)
                await uow.commit()
            return await self._rotate(uow, initial=True)

    async def rotate(self) -> ActiveSigningKey:  # type: ignore[return]
        async with self._uow_factory() as uow:
            return await self._rotate(uow, initial=False)

    async def _rotate(self, uow: Any, *, initial: bool) -> ActiveSigningKey:
        now = self._clock.utc_now()
        kid = _new_kid(now)
        private, public_jwk = await self._store.generate(kid)
        uow.session.add(
            OidcSigningKey(
                kid=kid,
                algorithm="RS256",
                public_jwk=PublicJwk.model_validate(public_jwk),
                status="active",
                not_before_at=now,
                retire_at=None,
                # Active keys are retained indefinitely; delete_at is anchored
                # to retirement so an active key can never be cleaned up while
                # tokens it signed are still within their maximum lifetime.
                delete_at=None,
            )
        )
        if not initial:
            active = (
                (
                    await uow.session.execute(
                        select(OidcSigningKey)
                        .where(OidcSigningKey.status == "active")
                        .with_for_update()
                    )
                )
                .scalars()
                .first()
            )
            if active is not None:
                active.status = "retired"
                active.retire_at = now
                active.delete_at = now + timedelta(seconds=KEY_RETENTION_SECONDS)
        await uow.commit()
        return ActiveSigningKey(kid=kid, private_key=private, algorithm="RS256")

    async def public_jwks(self) -> dict[str, Any]:
        """JWKS containing active and retained (verify-only) keys."""

        async with self._uow_factory() as uow:
            rows = (
                (
                    await uow.session.execute(
                        select(OidcSigningKey).where(
                            (OidcSigningKey.delete_at.is_(None))
                            | (OidcSigningKey.delete_at > self._clock.utc_now())
                        )
                    )
                )
                .scalars()
                .all()
            )
        return {
            "keys": [
                {
                    "kty": row.public_jwk.kty,
                    "kid": row.public_jwk.kid,
                    "alg": row.public_jwk.alg,
                    "use": row.public_jwk.use,
                    "n": row.public_jwk.n,
                    "e": row.public_jwk.e,
                }
                for row in rows
            ]
        }

    async def cleanup_expired_keys(self) -> int:  # type: ignore[return]
        """Remove keys past their delete window (retention housekeeping)."""

        async with self._uow_factory() as uow:
            rows = (
                (
                    await uow.session.execute(
                        select(OidcSigningKey).where(
                            OidcSigningKey.delete_at <= self._clock.utc_now()
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                await self._store.drop_private(row.kid)
                await uow.session.delete(row)
            await uow.commit()
            return len(rows)


def _new_kid(now: Any) -> str:
    import secrets

    return f"sig-{now.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"


def sign_jwt(key: ActiveSigningKey, claims: dict[str, Any]) -> str:
    """Sign with the algorithm allowlist; only RS256 is accepted."""

    return pyjwt.encode(
        claims,
        key.private_key,
        algorithm=key.algorithm,
        headers={"kid": key.kid},
    )


def verify_jwt(
    token: str,
    *,
    public_keys: dict[str, Any],
    audience: str,
    issuer: str,
) -> dict[str, Any]:
    """Verify signature, issuer, audience and algorithm allowlist."""

    try:
        header = pyjwt.get_unverified_header(token)
    except pyjwt.PyJWTError as exc:
        raise OidcError("invalid_token", "malformed token") from exc
    algorithm = header.get("alg")
    if algorithm not in ALGORITHM_ALLOWLIST:
        raise OidcError("invalid_token", f"unacceptable signing algorithm {algorithm!r}")
    kid = header.get("kid")
    if not isinstance(kid, str) or kid not in public_keys:
        raise OidcError("invalid_token", "unknown signing key")
    public_key = public_keys[kid]
    try:
        return pyjwt.decode(
            token,
            public_key,
            algorithms=list(ALGORITHM_ALLOWLIST),
            audience=audience,
            issuer=issuer,
            leeway=CLOCK_SKEW_SECONDS,
        )
    except pyjwt.PyJWTError as exc:
        raise OidcError("invalid_token", "token verification failed") from exc


def load_public_key(public_jwk: dict[str, Any]) -> Any:
    """Deserialize a public JWK dict into a cryptography key."""

    import base64

    def _b64u_decode(value: str) -> int:
        padding = "=" * (-len(value) % 4)
        return int.from_bytes(base64.urlsafe_b64decode(value + padding), "big")

    n = _b64u_decode(public_jwk["n"])
    e = _b64u_decode(public_jwk["e"])
    return rsa.RSAPublicNumbers(e, n).public_key()

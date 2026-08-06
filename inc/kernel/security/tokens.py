"""JWT access-token and opaque refresh-token primitives."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import jwt
from pydantic import BaseModel, ConfigDict, ValidationError

from inc.kernel.config import Settings, get_settings
from inc.kernel.errors import AppError

from .errors import AUTH_002, AUTH_003
from .principal import Principal

_ALGORITHM = "HS256"


class PrincipalClaims(BaseModel):
    """Validated access-token claims."""

    model_config = ConfigDict(frozen=True)

    sub: UUID
    roles: frozenset[str]
    capabilities: frozenset[str]
    iat: datetime
    exp: datetime
    type: Literal["access"]

    def to_principal(self, username: str) -> Principal:
        return Principal(
            id=self.sub,
            username=username,
            roles=self.roles,
            capabilities=self.capabilities,
        )


def hash_refresh(raw: str) -> str:
    """Hash an opaque refresh token for storage and lookup."""

    if not raw:
        raise ValueError("refresh token must not be empty")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class TokenService:
    """Issue and validate signed access tokens without persistence concerns."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._clock = clock or (lambda: datetime.now(UTC))

    def issue_access(self, principal: Principal) -> str:
        now = self._utc_now()
        expires = now + timedelta(seconds=self._settings.jwt_access_ttl_seconds)
        payload = {
            "sub": str(principal.id),
            "roles": sorted(principal.roles),
            "capabilities": sorted(principal.capabilities),
            "iat": now,
            "exp": expires,
            "type": "access",
            "jti": str(uuid4()),
        }
        return jwt.encode(payload, self._secret, algorithm=_ALGORITHM)

    def verify_access(self, token: str) -> PrincipalClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[_ALGORITHM],
                options={
                    "require": ["sub", "roles", "capabilities", "iat", "exp", "type"],
                    "verify_iat": True,
                },
            )
        except jwt.ExpiredSignatureError as exc:
            raise AppError(AUTH_002, cause=exc) from exc
        except jwt.InvalidTokenError as exc:
            raise AppError(AUTH_003, cause=exc) from exc

        try:
            claims = self._claims_payload(payload)
            if claims.get("type") != "access":
                raise ValueError("not an access token")
            return PrincipalClaims.model_validate(claims)
        except (TypeError, ValueError, ValidationError) as exc:
            raise AppError(AUTH_003, cause=exc) from exc

    def issue_refresh(self, user_id: UUID) -> tuple[str, str]:
        if not isinstance(user_id, UUID):
            raise TypeError("user_id must be a UUID")
        raw = secrets.token_urlsafe(48)
        return raw, hash_refresh(raw)

    @staticmethod
    def hash_refresh(raw: str) -> str:
        return hash_refresh(raw)

    @property
    def _secret(self) -> str:
        return self._settings.jwt_secret.get_secret_value()

    @property
    def access_ttl_seconds(self) -> int:
        return self._settings.jwt_access_ttl_seconds

    @property
    def refresh_ttl_seconds(self) -> int:
        return self._settings.jwt_refresh_ttl_seconds

    def _utc_now(self) -> datetime:
        now = self._clock()
        return now if now.tzinfo is not None else now.replace(tzinfo=UTC)

    @staticmethod
    def _claims_payload(payload: dict[str, Any]) -> dict[str, Any]:
        claims = dict(payload)
        for key in ("roles", "capabilities"):
            value = claims.get(key)
            if not isinstance(value, (list, tuple, set, frozenset)):
                raise ValueError(f"{key} must be a sequence")
            if not all(isinstance(item, str) for item in value):
                raise ValueError(f"{key} must contain strings")
            claims[key] = frozenset(cast(Any, value))
        return claims

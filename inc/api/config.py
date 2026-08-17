"""API-level settings for the composition root.

Contract source: context/spec/composition.md §2.3, http-openapi.md §9.

These are deployment/profile concerns (issuer, audiences, cookie
security, CORS); kernel settings stay technical (database, workers).
"""

from __future__ import annotations

import ipaddress
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

DEFAULT_ISSUER = "http://127.0.0.1:8000"


class ApiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: Literal["dev", "test", "production"] = "dev"
    issuer: str = DEFAULT_ISSUER
    api_audience: str = "aiya-admin"
    secure_cookies: bool = False
    cors_origins: tuple[str, ...] = ()
    trusted_proxy_cidrs: tuple[str, ...] = ()
    oidc_signing_key_dir: str | None = None
    worker_sleep_seconds: float = 1.0
    admin_session_secret: str = "dev-admin-session-secret-change-me"
    admin_session_idle_seconds: int = 8 * 3600
    admin_session_absolute_seconds: int = 14 * 86400

    @field_validator("issuer")
    @classmethod
    def _validate_issuer(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("issuer must be an http(s) URL with a host")
        if parsed.query or parsed.fragment:
            raise ValueError("issuer must not contain a query or fragment")
        return normalized

    @field_validator("cors_origins")
    @classmethod
    def _validate_cors_origins(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            origin = value.strip().rstrip("/")
            if origin == "*":
                normalized.append(origin)
                continue
            parsed = urlparse(origin)
            if (
                parsed.scheme.lower() not in {"http", "https"}
                or not parsed.hostname
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(f"invalid CORS origin: {value}")
            normalized.append(origin)
        return tuple(dict.fromkeys(normalized))

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def _validate_trusted_proxy_cidrs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            try:
                network = ipaddress.ip_network(value.strip(), strict=False)
            except ValueError as exc:
                raise ValueError(f"invalid trusted proxy CIDR: {value}") from exc
            normalized.append(str(network))
        return tuple(dict.fromkeys(normalized))

    @model_validator(mode="after")
    def _enforce_production_gate(self) -> ApiSettings:
        if self.environment != "production":
            return self
        parsed = urlparse(self.issuer)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise ValueError("production issuer must be https with a host")
        if not self.secure_cookies:
            raise ValueError("production requires secure cookies")
        if "*" in self.cors_origins:
            raise ValueError("production CORS origins must be an exact allowlist, not a wildcard")
        if not self.oidc_signing_key_dir or not self.oidc_signing_key_dir.strip():
            raise ValueError("production requires AIYA_OIDC_SIGNING_KEY_DIR")
        if (
            self.admin_session_secret == "dev-admin-session-secret-change-me"
            or len(self.admin_session_secret) < 32
        ):
            raise ValueError("production requires a strong AIYA_ADMIN_SESSION_SECRET")
        return self


def load_api_settings(overrides: dict[str, Any] | None = None) -> ApiSettings:
    return ApiSettings(**overrides) if overrides else ApiSettings()

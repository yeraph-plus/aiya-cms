"""API-level settings for the composition root.

Contract source: context/spec/composition.md §2.3, http-openapi.md §9.

These are deployment/profile concerns (issuer, audiences, cookie
security, CORS); kernel settings stay technical (database, workers).
"""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, model_validator


class ApiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: Literal["dev", "production"] = "dev"
    issuer: str = "http://127.0.0.1:8080"
    api_audience: str = "aiya-admin"
    secure_cookies: bool = False
    cors_origins: tuple[str, ...] = ()
    worker_sleep_seconds: float = 1.0

    @model_validator(mode="after")
    def _enforce_production_gate(self) -> ApiSettings:
        if self.environment != "production":
            return self
        parsed = urlparse(self.issuer)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise ValueError("production issuer must be https with a host")
        if not self.secure_cookies:
            raise ValueError("production requires secure cookies")
        return self


def load_api_settings(overrides: dict[str, Any] | None = None) -> ApiSettings:
    return ApiSettings(**overrides) if overrides else ApiSettings()

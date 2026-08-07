"""API-level settings for the composition root.

Contract source: context/spec/composition.md §2.3, http-openapi.md §9.

These are deployment/profile concerns (issuer, audiences, cookie
security, CORS); kernel settings stay technical (database, workers).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ApiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: str = "dev"
    issuer: str = "http://127.0.0.1:8080"
    api_audience: str = "aiya-admin"
    secure_cookies: bool = False
    cors_origins: tuple[str, ...] = ()
    worker_sleep_seconds: float = 1.0


def load_api_settings(overrides: dict[str, Any] | None = None) -> ApiSettings:
    settings = ApiSettings(**overrides) if overrides else ApiSettings()
    if settings.environment == "production":
        if not settings.issuer.startswith("https://"):
            raise ValueError("production issuer must be https")
        if not settings.secure_cookies:
            raise ValueError("production requires secure cookies")
    return settings

"""Configuration loading and typed settings.

Contract source: context/spec/kernel/foundation.md §1.

Settings are parsed once at boot into an immutable Pydantic model. Priority
is explicit: overrides (tests, composition root) > environment > defaults.
The model never re-reads the environment at runtime, and secret values are
masked in every representation.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["dev", "test", "production"]


class Settings(BaseSettings):
    """Immutable kernel settings; only technical keys live here."""

    model_config = SettingsConfigDict(
        env_prefix="AIYA_",
        env_file=None,
        extra="forbid",
        frozen=True,
    )

    environment: Environment = "dev"
    database_url: SecretStr = SecretStr("")  # required: env/override must supply
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    log_level: str = "INFO"

    outbox_batch_size: int = 20
    outbox_lease_seconds: int = 60
    outbox_retry_base_seconds: float = 1.0

    task_batch_size: int = 10
    task_lease_seconds: int = 60
    worker_grace_seconds: float = 30.0
    worker_sleep_seconds: float = 1.0

    workflow_lease_seconds: int = 60

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in logging._nameToLevel:  # noqa: SLF001
            raise ValueError(f"unknown log level {value!r}")
        return normalized

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: SecretStr) -> SecretStr:
        url = value.get_secret_value()
        if not url:
            raise ValueError("database_url is required")
        if not url.startswith(("postgresql+asyncpg://", "sqlite+aiosqlite://")):
            raise ValueError("database_url must use postgresql+asyncpg or sqlite+aiosqlite")
        return value


def load_settings(*, overrides: dict[str, Any] | None = None) -> Settings:
    """Parse settings once; *overrides* win over the environment."""

    if overrides is None:
        return Settings()
    return Settings(**overrides)

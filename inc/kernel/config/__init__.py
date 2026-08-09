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
from urllib.parse import quote

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["dev", "test", "production"]


class Settings(BaseSettings):
    """Immutable kernel settings; only technical keys live here."""

    model_config = SettingsConfigDict(
        env_prefix="AIYA_",
        env_file=None,
        extra="forbid",
        frozen=True,
        validate_default=True,
    )

    environment: Environment = "dev"
    # Connection fields are decomposed (host/user/password/...); docker-compose
    # and 1panel-style panels inject these separately. An explicit
    # database_url/redis_url override (used by SQLite tests and exotic
    # deployments) wins over the decomposed fields. pg_host has no default so
    # that a completely unconfigured boot still fails fast.
    pg_host: str = ""
    pg_port: int = 5432
    pg_user: str = "aiya"
    pg_password: SecretStr = SecretStr("")
    pg_database: str = "aiya"
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: SecretStr = SecretStr("")

    database_url: SecretStr = SecretStr("")
    redis_url: SecretStr = SecretStr("")
    log_level: str = "INFO"

    outbox_batch_size: int = 20
    outbox_lease_seconds: int = 60
    outbox_retry_base_seconds: float = 1.0

    task_batch_size: int = 10
    task_lease_seconds: int = 60
    worker_grace_seconds: float = 30.0
    worker_sleep_seconds: float = 1.0

    workflow_lease_seconds: int = 60

    @model_validator(mode="before")
    @classmethod
    def _assemble_urls(cls, values: Any) -> Any:
        """Assemble database_url/redis_url from decomposed fields when unset."""

        if not isinstance(values, dict):
            return values
        data = dict(values)

        def _secret(v: Any) -> str:
            return v.get_secret_value() if isinstance(v, SecretStr) else str(v or "")

        if not data.get("database_url"):
            pg_host = _secret(data.get("pg_host"))
            if pg_host:
                password = quote(_secret(data.get("pg_password")), safe="")
                data["database_url"] = (
                    f"postgresql+asyncpg://{data.get('pg_user', 'aiya')}:{password}"
                    f"@{pg_host}:{data.get('pg_port', 5432)}"
                    f"/{data.get('pg_database', 'aiya')}"
                )
        if not data.get("redis_url"):
            redis_password = _secret(data.get("redis_password"))
            host = data.get("redis_host", "127.0.0.1")
            port = data.get("redis_port", 6379)
            db = data.get("redis_db", 0)
            credentials = f":{quote(redis_password, safe='')}@" if redis_password else ""
            data["redis_url"] = f"redis://{credentials}{host}:{port}/{db}"
        return data

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

    @field_validator("redis_url")
    @classmethod
    def _validate_redis_url(cls, value: SecretStr) -> SecretStr:
        url = value.get_secret_value()
        if url and not url.startswith(("redis://", "rediss://")):
            raise ValueError("redis_url must use redis:// or rediss://")
        return value


def load_settings(*, overrides: dict[str, Any] | None = None) -> Settings:
    """Parse settings once; *overrides* win over the environment."""

    if overrides is None:
        return Settings()
    return Settings(**overrides)

"""Typed environment configuration for the application scaffold."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from the environment with ``AIYA_`` prefix."""

    model_config = SettingsConfigDict(
        env_prefix="AIYA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://aiya:aiya@localhost:5432/aiya"
    redis_url: str = "redis://localhost:6379/0"
    smtp_host: str = "localhost"
    smtp_port: int = Field(default=1025, ge=1, le=65535)
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = "no-reply@aiya.local"
    jwt_secret: SecretStr = SecretStr("dev-only-change-me")
    jwt_access_ttl_seconds: int = Field(default=900, gt=0)
    jwt_refresh_ttl_seconds: int = Field(default=1_209_600, gt=0)
    cache_backend: Literal["redis", "memory"] = "redis"
    cors_origins: list[str] = ["http://localhost:7000"]
    public_base_url: str = "http://localhost:7000"
    cookie_name: str = "aiya_refresh"
    cookie_secure: bool = False

    @model_validator(mode="after")
    def reject_dev_secret_in_production(self) -> Settings:
        if self.env == "prod":
            secret = self.jwt_secret.get_secret_value()
            if len(secret.strip()) < 32:
                raise ValueError(
                    "AIYA_JWT_SECRET must be at least 32 non-whitespace characters in prod"
                )
        return self

    @model_validator(mode="after")
    def require_secure_cookie_in_production(self) -> Settings:
        if self.env == "prod" and not self.cookie_secure:
            raise ValueError("AIYA_COOKIE_SECURE must be true in prod")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""

    return Settings()

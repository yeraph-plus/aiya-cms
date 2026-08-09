"""Environment-driven PostgreSQL URLs for host and Compose test runs.

The admin URL defaults to the decomposed AIYA_PG_* connection fields (the
single source of truth for PostgreSQL credentials).
"""

from __future__ import annotations

import os


def _admin_url() -> str:
    """Admin URL to the default ``postgres`` database for test DB creation."""

    user = os.getenv("AIYA_PG_USER", "aiya")
    password = os.getenv("AIYA_PG_PASSWORD", "aiya")
    host = os.getenv("AIYA_PG_HOST", "127.0.0.1")
    port = os.getenv("AIYA_PG_PORT", "5432")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/postgres"


def postgres_url(database: str, *, async_driver: bool = True) -> str:
    base = _admin_url().rsplit("/", 1)[0]
    if not async_driver:
        base = base.replace("postgresql+asyncpg://", "postgresql://", 1)
    return f"{base}/{database}"


def admin_url(*, async_driver: bool = True) -> str:
    return postgres_url("postgres", async_driver=async_driver)

"""Environment-driven PostgreSQL URLs for host and Compose test runs."""

from __future__ import annotations

import os


def _admin_url() -> str:
    return os.getenv(
        "AIYA_TEST_PG_ADMIN_URL",
        "postgresql+asyncpg://aiya:aiya@localhost:5432/postgres",
    )


def postgres_url(database: str, *, async_driver: bool = True) -> str:
    base = _admin_url().rsplit("/", 1)[0]
    if not async_driver:
        base = base.replace("postgresql+asyncpg://", "postgresql://", 1)
    return f"{base}/{database}"


def admin_url(*, async_driver: bool = True) -> str:
    return postgres_url("postgres", async_driver=async_driver)

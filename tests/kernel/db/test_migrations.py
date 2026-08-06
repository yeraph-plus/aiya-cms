"""Red tests locking the Alembic async migration chain (M1.2-M1.10).

Contract source: context/spec/quality-release.md and context/spec/kernel.md

Runs the real async Alembic environment against a dedicated database to prove
upgrade/downgrade idempotency across the M1.2 empty boundary and the M1.5
identity, RBAC, auth and task tables. (The "db component itself builds no tables" invariant lives in
tests/architecture/test_db_conventions.py.)
"""

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path

import asyncpg
import pytest
from alembic.config import Config

from alembic import command
from inc.kernel.config import get_settings
from tests.support.postgres import admin_url, postgres_url

MIGRATIONS_DB_NAME = "aiya_test_migrations"
PG_ADMIN_DSN = admin_url(async_driver=False)
MIGRATIONS_DSN = postgres_url(MIGRATIONS_DB_NAME, async_driver=False)
MIGRATIONS_URL = MIGRATIONS_DSN.replace("postgresql://", "postgresql+asyncpg://")
ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"


def _reset_migrations_database() -> None:
    async def _reset() -> None:
        conn = await asyncpg.connect(PG_ADMIN_DSN)
        try:
            await conn.execute(f'DROP DATABASE IF EXISTS "{MIGRATIONS_DB_NAME}" WITH (FORCE)')
            await conn.execute(f'CREATE DATABASE "{MIGRATIONS_DB_NAME}"')
        finally:
            await conn.close()

    asyncio.run(_reset())


def _table_names() -> list[str]:
    async def _query() -> list[str]:
        conn = await asyncpg.connect(MIGRATIONS_DSN)
        try:
            rows = await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            )
            return [row["tablename"] for row in rows]
        finally:
            await conn.close()

    return asyncio.run(_query())


def _current_revision() -> str | None:
    if "alembic_version" not in _table_names():
        return None

    async def _query() -> str | None:
        conn = await asyncpg.connect(MIGRATIONS_DSN)
        try:
            row = await conn.fetchrow("SELECT version_num FROM alembic_version")
            return row["version_num"] if row else None
        finally:
            await conn.close()

    return asyncio.run(_query())


def _business_tables() -> list[str]:
    """Non-infrastructure tables; the db component must build none (spec §5)."""
    return [name for name in _table_names() if name != "alembic_version"]


@pytest.fixture
def alembic_cfg() -> Iterator[Config]:
    _reset_migrations_database()
    previous_url = os.environ.get("AIYA_DATABASE_URL")
    os.environ["AIYA_DATABASE_URL"] = MIGRATIONS_URL
    get_settings.cache_clear()
    try:
        yield Config(str(ALEMBIC_INI))
    finally:
        if previous_url is None:
            os.environ.pop("AIYA_DATABASE_URL", None)
        else:
            os.environ["AIYA_DATABASE_URL"] = previous_url
        get_settings.cache_clear()


def test_migration_chain_upgrade_downgrade_upgrade(alembic_cfg: Config) -> None:
    command.upgrade(alembic_cfg, "head")
    assert _current_revision() == "0010_declarative_content_columns"
    assert set(_business_tables()) == {
        "users",
        "identities",
        "organizations",
        "roles",
        "permissions",
        "role_permissions",
        "user_roles",
        "refresh_tokens",
        "task_instances",
        "mail_outbox",
        "audit_logs",
        "settings",
        "contents",
        "terms",
        "term_relationships",
        "comments",
        "interactions",
        "password_reset_tokens",
    }

    command.downgrade(alembic_cfg, "base")
    assert _current_revision() is None
    assert _business_tables() == []

    command.upgrade(alembic_cfg, "head")
    assert _current_revision() == "0010_declarative_content_columns"
    assert set(_business_tables()) == {
        "users",
        "identities",
        "organizations",
        "roles",
        "permissions",
        "role_permissions",
        "user_roles",
        "refresh_tokens",
        "task_instances",
        "mail_outbox",
        "audit_logs",
        "settings",
        "contents",
        "terms",
        "term_relationships",
        "comments",
        "interactions",
        "password_reset_tokens",
    }

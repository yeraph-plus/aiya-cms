"""Async Alembic environment driven by the explicit migration manifest.

Contract source: context/spec/kernel/database.md §6.

Model modules are imported exclusively from ``alembic/migration_manifest.py``
(no package scanning, no side-effect registration). ``target_metadata`` is
the kernel Base metadata; capability tables attach to the same Base.
"""

from __future__ import annotations

import importlib
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import Connection, inspect, pool, text
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

_ENV_DIR = Path(__file__).resolve().parent
if str(_ENV_DIR) not in sys.path:
    sys.path.insert(0, str(_ENV_DIR))

from migration_manifest import MIGRATION_OWNER_MODULES  # noqa: E402

for _owner, _module in MIGRATION_OWNER_MODULES.items():
    importlib.import_module(_module)

from inc.kernel.db import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """Resolve the database URL from decomposed settings, env override, or alembic.ini.

    The kernel Settings assemble ``AIYA_DATABASE_URL`` from the decomposed
    ``AIYA_PG_*`` fields; that URL wins. A direct ``AIYA_DATABASE_URL`` env
    var (deployments that still pass a full URL) is honoured as a fallback,
    then alembic.ini.
    """

    from inc.kernel.config import load_settings

    try:
        kernel_settings = load_settings()
        url = kernel_settings.database_url.get_secret_value()
        if url:
            return url
    except Exception:  # noqa: BLE001 - fall back to explicit env/ini
        pass
    return os.environ.get("AIYA_DATABASE_URL") or config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    """Run migrations without creating a DB connection."""

    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


_RELEASE_BASELINE_REVISION = "release_0001"


def _reject_legacy_database(connection: Connection) -> None:
    """Release is an empty-database baseline; never reinterpret old state."""

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "alembic_version" in tables:
        revisions = {
            str(row[0])
            for row in connection.execute(text("SELECT version_num FROM alembic_version"))
        }
        if revisions == {_RELEASE_BASELINE_REVISION}:
            # A database already installed from this exact release baseline
            # is the only non-empty state accepted by idempotent install.
            return
        if revisions:
            raise RuntimeError(
                "release migration baseline refuses existing Alembic revision(s): "
                f"{sorted(revisions)}; deploy to a new empty database"
            )
    # The release baseline is intentionally installable only into an empty
    # database.  Checking a prefix allow-list is unsafe here: older/business
    # tables such as ``audit_entries`` or ``kernel_outbox`` do not share a
    # capability prefix and would otherwise be silently reinterpreted.  Any
    # table besides Alembic's own version table therefore proves that this is
    # not a fresh database (the exact release revision was handled above for
    # idempotent installs).
    existing = sorted(table for table in tables if table != "alembic_version")
    if existing:
        raise RuntimeError(
            "release migration baseline refuses existing database tables: "
            f"{existing}; deploy to a new empty database"
        )


def do_run_migrations(connection: Connection) -> None:
    """Configure and run migrations on an active SQLAlchemy connection."""

    _reject_legacy_database(connection)
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run the synchronous Alembic callbacks."""

    section = dict(config.get_section(config.config_ini_section, {}))
    section["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    # Alembic's migration transaction is coordinated with this explicit async
    # transaction.  A bare ``connect()`` rolls the DDL back when the async
    # connection closes, leaving an apparently successful empty-database
    # upgrade with no tables.
    async with connectable.begin() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run online migrations through the async event loop."""

    import asyncio

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

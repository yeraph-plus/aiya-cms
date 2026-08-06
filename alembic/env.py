"""Async Alembic environment driven by the explicit migration manifest.

Contract source: context/spec/kernel/database.md §6.

Model modules are imported exclusively from ``alembic/migration_manifest.py``
(no package scanning, no side-effect registration). ``target_metadata`` is
None until the R3 kernel Base exists; autogenerate then attaches the kernel
Base metadata.
"""

from __future__ import annotations

import importlib
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

_ENV_DIR = Path(__file__).resolve().parent
if str(_ENV_DIR) not in sys.path:
    sys.path.insert(0, str(_ENV_DIR))

from migration_manifest import MIGRATION_OWNER_MODULES  # noqa: E402

for _owner, _module in MIGRATION_OWNER_MODULES.items():
    importlib.import_module(_module)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations without creating a DB connection."""

    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: object) -> None:
    """Configure and run migrations on an active SQLAlchemy connection."""

    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run the synchronous Alembic callbacks."""

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
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

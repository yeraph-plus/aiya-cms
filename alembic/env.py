"""Async Alembic environment for the M0 empty migration set."""

from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

import inc.kernel.audit.models  # noqa: F401  (registers audit models on Base.metadata)
import inc.kernel.auth.models  # noqa: F401  (registers auth models on Base.metadata)
import inc.kernel.comment.models  # noqa: F401  (registers comment models on Base.metadata)
import inc.kernel.content.models  # noqa: F401  (registers content models on Base.metadata)
import inc.kernel.identity.models  # noqa: F401  (registers identity models on Base.metadata)
import inc.kernel.mail.models  # noqa: F401  (registers mail models on Base.metadata)
import inc.kernel.rbac.models  # noqa: F401  (registers RBAC models on Base.metadata)
import inc.kernel.settings.models  # noqa: F401  (registers settings models on Base.metadata)
import inc.kernel.tasks.models  # noqa: F401  (registers task models on Base.metadata)
import inc.kernel.taxonomy.models  # noqa: F401  (registers taxonomy models on Base.metadata)
import inc.modules.interaction.models  # noqa: F401  (registers interaction models on Base.metadata)
from alembic import context
from inc.kernel.config import get_settings
from inc.kernel.db import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without creating a DB connection."""

    context.configure(
        url=settings.database_url,
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

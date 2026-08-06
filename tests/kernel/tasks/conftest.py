"""PostgreSQL fixtures for M1.10 task integration tests."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import inc.kernel.auth.models  # noqa: F401
import inc.kernel.identity.models  # noqa: F401
import inc.kernel.rbac.models  # noqa: F401
import inc.kernel.tasks.models  # noqa: F401
from inc.kernel.config import Settings
from inc.kernel.db import DB_CODES, Base
from inc.kernel.errors import COMMON_CODES, clear_registry, register_error_codes
from inc.kernel.rbac import RBAC_CODES
from inc.kernel.tasks import TASK_CODES
from tests.support.postgres import admin_url, postgres_url

PG_ADMIN_URL = admin_url()
TEST_DB_NAME = "aiya_test_tasks"
TEST_DB_URL = postgres_url(TEST_DB_NAME)


@pytest.fixture(autouse=True)
def register_task_codes() -> None:
    clear_registry()
    register_error_codes(*COMMON_CODES, *DB_CODES, *RBAC_CODES, *TASK_CODES)


async def ensure_database() -> None:
    engine = create_async_engine(PG_ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": TEST_DB_NAME},
            )
            if not exists:
                await connection.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    finally:
        await engine.dispose()


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    await ensure_database()
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.fixture
async def session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def task_settings() -> Settings:
    return Settings(_env_file=None, jwt_secret="task-test-secret-that-is-long-enough")

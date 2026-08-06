"""Shared PG-backed fixtures for the kernel db component tests (M1.2).

Requires the docker-compose PostgreSQL (postgres:16-alpine) on localhost:5432
with credentials aiya/aiya. The dedicated ``aiya_test`` database is created on
demand; sample models live on a private metadata (see :mod:`_samples`) so they
never leak into the app ``Base.metadata`` that Alembic targets.
"""

from collections.abc import AsyncIterator

import pytest
from _samples import _TestBase
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from inc.kernel.db import DB_001, DB_002
from inc.kernel.errors import clear_registry, register_error_codes
from tests.support.postgres import admin_url, postgres_url

PG_ADMIN_URL = admin_url()
TEST_DB_NAME = "aiya_test"
TEST_DB_URL = postgres_url(TEST_DB_NAME)


@pytest.fixture(autouse=True)
def register_db_codes() -> None:
    """DB_001/DB_002 must be registered before AppError can use them."""
    clear_registry()
    register_error_codes(DB_001, DB_002)


async def ensure_database(url: str, db_name: str) -> None:
    """Create ``db_name`` on the server in ``url`` if it does not exist."""
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        await engine.dispose()


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """Function-scoped engine on ``aiya_test`` with sample tables created."""
    await ensure_database(PG_ADMIN_URL, TEST_DB_NAME)
    eng = create_async_engine(TEST_DB_URL)
    async with eng.begin() as conn:
        await conn.run_sync(_TestBase.metadata.create_all)
    try:
        yield eng
    finally:
        async with eng.begin() as conn:
            await conn.run_sync(_TestBase.metadata.drop_all)
        await eng.dispose()


@pytest.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as s:
        yield s

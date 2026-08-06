"""PG fixtures for the M1.8 auth integration tests."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Import models so create_all sees every dependency in the auth transaction.
import inc.kernel.auth.models  # noqa: F401
import inc.kernel.identity.models  # noqa: F401
import inc.kernel.rbac.models  # noqa: F401
from inc.kernel.auth import AUTH_CODES
from inc.kernel.config import Settings
from inc.kernel.db import DB_CODES, Base, UoWExecutor
from inc.kernel.errors import COMMON_CODES, clear_registry, register_error_codes
from inc.kernel.identity import IDENTITY_CODES
from inc.kernel.rbac import RBAC_CODES, RBACUnitOfWork, seed_rbac
from tests.support.postgres import admin_url, postgres_url

PG_ADMIN_URL = admin_url()
TEST_DB_NAME = "aiya_test_auth"
TEST_DB_URL = postgres_url(TEST_DB_NAME)


@pytest.fixture(autouse=True)
def register_auth_codes() -> None:
    clear_registry()
    register_error_codes(*COMMON_CODES)
    register_error_codes(*DB_CODES)
    register_error_codes(*IDENTITY_CODES)
    register_error_codes(*RBAC_CODES)
    register_error_codes(*AUTH_CODES)


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
        await connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        await connection.exec_driver_sql("CREATE SCHEMA public")
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await seed_rbac(UoWExecutor(lambda: RBACUnitOfWork(factory)))
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
            await connection.exec_driver_sql("CREATE SCHEMA public")
        await engine.dispose()


@pytest.fixture
async def session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def auth_settings() -> Settings:
    return Settings(_env_file=None, jwt_secret="auth-test-secret-that-is-long-enough")

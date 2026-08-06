"""Shared kernel test fixtures: fresh SQLite per test, FakeClock, UoW.

Kernel unit tests run against SQLite (aiosqlite) with the same UoW/JSONB
code paths; PostgreSQL acceptance runs in the Compose test profile.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from inc.kernel.db import Base, SqlAlchemyUnitOfWork, UoWFactory
from inc.kernel.time.fake import FakeClock
from tests.kernel._test_models import AppliedEvent  # noqa: F401  (registers test tables)


@pytest.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(db_engine: AsyncEngine) -> async_sessionmaker[Any]:
    return async_sessionmaker(db_engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
def uow_factory(session_factory: async_sessionmaker[Any]) -> UoWFactory:
    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    return factory


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 1, 1, tzinfo=UTC))

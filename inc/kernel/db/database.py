"""Async engine and session factory creation.

Contract source: context/spec/kernel/database.md §1/§2.

Engine and session creation is confined to this module (architectural
red line). The composition root calls these once at boot; importing this
module connects nothing.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str, **kwargs: Any) -> AsyncEngine:
    """Create a configured async engine (no connection is opened yet)."""

    return create_async_engine(database_url, **kwargs)


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Session factory with expire_on_commit disabled (DTO-style reads)."""

    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


__all__ = ["create_engine", "create_session_factory"]

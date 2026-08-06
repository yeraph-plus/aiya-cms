"""Unit of Work.

Contract source: context/spec/kernel/database.md §2.

Command handlers receive a UoW factory, never a Session. Business changes
and outbox appends commit in one database transaction; exceptions roll back
by default.
"""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class UnitOfWork(Protocol):
    """Transaction boundary handed to commands and handlers."""

    session: Any

    async def __aenter__(self) -> UnitOfWork: ...

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class UoWFactory(Protocol):
    """Callable producing a fresh UoW; one per command or handler."""

    def __call__(self) -> UnitOfWork: ...


class SqlAlchemyUnitOfWork:
    """Async SQLAlchemy UoW: explicit commit, rollback on failure or exit."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._committed = False

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UoW is not entered")
        return self._session

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        self._session = self._session_factory()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        try:
            if self._session is None:
                return False
            if exc_type is not None:
                # Exceptions roll back; uncommitted changes are never persisted.
                await self.rollback()
        finally:
            if self._session is not None:
                await self._session.close()
                self._session = None
        return False

    async def commit(self) -> None:
        await self.session.commit()
        self._committed = True

    async def rollback(self) -> None:
        if self._session is not None:
            await self._session.rollback()

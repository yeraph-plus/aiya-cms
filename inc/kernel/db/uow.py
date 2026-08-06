"""Async unit-of-work transaction boundary (spec §3/§6).

Entering opens a session; exiting rolls back unless :meth:`commit` was called,
so an uncommitted UoW can never silently leave data behind.
"""

from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Protocol, Self, TypeVar, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

ResultT = TypeVar("ResultT")


class AbstractUnitOfWork:
    """Opens a session on enter; rolls back on exit unless committed."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._committed = False

    @property
    def session(self) -> AsyncSession:
        """The live session; only available inside the ``async with`` block."""
        if self._session is None:
            raise RuntimeError("unit of work has not been entered")
        return self._session

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self._committed = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        session = self._session
        assert session is not None
        try:
            if exc_type is not None or not self._committed:
                await session.rollback()
        finally:
            await session.close()
            self._session = None

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self.session.commit()
        self._committed = True

    async def rollback(self) -> None:
        """Roll back the current transaction."""
        await self.session.rollback()
        self._committed = False

    async def flush(self) -> None:
        """Flush pending ORM changes without ending the transaction."""
        await self.session.flush()


class UoWContext(Protocol):
    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def flush(self) -> None: ...


UoWT = TypeVar("UoWT", bound=UoWContext)


class UoWExecutor[UoWT]:
    """Own a UoW lifetime so services never commit or touch a Session."""

    def __init__(self, uow_factory: Callable[[], UoWT]) -> None:
        self._uow_factory = uow_factory

    async def read(self, operation: Callable[[UoWT], Awaitable[ResultT]]) -> ResultT:
        """Run a read operation and roll back its read-only transaction on exit."""
        uow = self._uow_factory()
        async with cast(UoWContext, uow):
            return await operation(uow)

    async def write(self, operation: Callable[[UoWT], Awaitable[ResultT]]) -> ResultT:
        """Run a write operation and commit exactly once after it succeeds."""
        uow = self._uow_factory()
        async with cast(UoWContext, uow):
            result = await operation(uow)
            await cast(UoWContext, uow).commit()
            return result

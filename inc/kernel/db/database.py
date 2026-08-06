"""Production-owned async engine and session factory."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from inc.kernel.config import Settings, get_settings


@dataclass(slots=True)
class Database:
    """Application database resources created by kernel/db."""

    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    async def dispose(self) -> None:
        """Release all pooled connections."""
        await self.engine.dispose()


def create_database(settings: Settings | None = None) -> Database:
    """Create the async engine and non-expiring session factory for the app."""
    resolved = settings or get_settings()
    engine = create_async_engine(resolved.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return Database(engine=engine, session_factory=session_factory)

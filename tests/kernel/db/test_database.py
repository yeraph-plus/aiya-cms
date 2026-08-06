"""Tests for the production-owned engine/session factory."""

from inc.kernel.config import Settings
from inc.kernel.db import create_database


async def test_create_database_builds_expire_on_commit_false_factory() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://aiya:aiya@localhost:5432/aiya",
    )
    database = create_database(settings)
    try:
        assert database.session_factory.kw["expire_on_commit"] is False
    finally:
        await database.dispose()

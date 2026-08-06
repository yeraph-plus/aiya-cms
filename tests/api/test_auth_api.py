"""Real PostgreSQL API journey required by the M1 G5 gate."""

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import inc.kernel.audit.models  # noqa: F401
import inc.kernel.auth.models  # noqa: F401
import inc.kernel.identity.models  # noqa: F401
import inc.kernel.mail.models  # noqa: F401
import inc.kernel.rbac.models  # noqa: F401
import inc.kernel.settings.models  # noqa: F401
import inc.kernel.tasks.models  # noqa: F401
from inc.api.app import create_app
from inc.kernel.config import Settings
from inc.kernel.db import Base, UoWExecutor
from inc.kernel.rbac import RBACUnitOfWork, seed_rbac
from tests.support.postgres import admin_url, postgres_url

PG_ADMIN_URL = admin_url()
TEST_DB_URL = postgres_url("aiya_test_api")


async def _ensure_database() -> None:
    engine = create_async_engine(PG_ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = 'aiya_test_api'")
            )
            if not exists:
                await connection.execute(text('CREATE DATABASE "aiya_test_api"'))
    finally:
        await engine.dispose()


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    await _ensure_database()
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.mark.asyncio
async def test_register_login_me_refresh_logout_real_pg(engine: AsyncEngine) -> None:
    settings = Settings(
        _env_file=None,
        env="test",
        database_url=TEST_DB_URL,
        cache_backend="memory",
        jwt_secret="api-test-secret-that-is-long-enough",
    )
    application = create_app(settings)
    container = application.state.container
    await seed_rbac(UoWExecutor(lambda: RBACUnitOfWork(engine_session_factory(engine))))
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        public_settings = await client.get("/api/v1/public/settings")
        assert public_settings.status_code == 200
        assert "admin_email" not in public_settings.json()["site_profile"]
        rejected = await client.get(
            "/api/v1/settings",
            headers={"Authorization": "Bearer definitely-not-a-jwt"},
        )
        assert rejected.status_code == 401
        assert rejected.json()["code"] == "AUTH_003"
        registered = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "api_user",
                "email": "api@example.com",
                "password": "secret-pass-123",
            },
        )
        assert registered.status_code == 201
        forgot = await client.post(
            "/api/v1/auth/forgot-password", json={"email": "api@example.com"}
        )
        assert forgot.status_code == 202
        logged_in = await client.post(
            "/api/v1/auth/login",
            json={"identifier": "api_user", "password": "secret-pass-123"},
        )
        assert logged_in.status_code == 200
        pair = logged_in.json()
        access = pair["access_token"]
        old_refresh = pair["refresh_token"]
        headers = {"Authorization": f"Bearer {access}"}
        me = await client.get("/api/v1/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["username"] == "api_user"
        refreshed = await client.post("/api/v1/auth/refresh", headers=headers)
        assert refreshed.status_code == 200
        new_refresh = refreshed.json()["refresh_token"]
        assert new_refresh != old_refresh
        assert (
            await client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": old_refresh},
                cookies={"aiya_refresh": ""},
            )
        ).status_code == 401
        assert (
            await client.post("/api/v1/auth/logout", json={"refresh_token": new_refresh})
        ).status_code == 204
        assert (
            await client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
        ).status_code == 401
    await container.database.dispose()


def engine_session_factory(engine: AsyncEngine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(engine, expire_on_commit=False)

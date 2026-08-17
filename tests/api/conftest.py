"""API test fixtures: full cms app over SQLite with minted bearer tokens."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from inc.api.app import create_app
from inc.api.config import ApiSettings
from inc.api.manifest import cms_dev
from inc.capabilities.access.commands import (
    BootstrapAdministrator,
    EnsureBaseRoles,
)
from inc.capabilities.access.commands import (
    CommandContext as AccessCommandContext,
)
from inc.capabilities.identity.commands import (
    CommandContext as IdentityCommandContext,
)
from inc.capabilities.identity.commands import (
    RegisterLocalUser,
)
from inc.kernel.db import UoWFactory
from inc.kernel.time.fake import FakeClock

TEST_ISSUER = "http://testserver"
TEST_AUDIENCE = "aiya-admin"
ADMIN_PASSWORD = "correct horse battery staple"


@pytest.fixture
def api_settings() -> ApiSettings:
    return ApiSettings(
        issuer=TEST_ISSUER,
        api_audience=TEST_AUDIENCE,
        cors_origins=("http://admin.test",),
        worker_sleep_seconds=0.01,
    )


@pytest.fixture
async def client(
    db_engine: AsyncEngine,
    session_factory: Any,
    uow_factory: UoWFactory,
    clock: FakeClock,
    api_settings: ApiSettings,
) -> Any:
    app = create_app(
        manifest=cms_dev,
        uow_factory=uow_factory,
        clock=clock,
        settings=api_settings,
        start_workers=False,
    )
    services = app.state.services
    await EnsureBaseRoles(
        AccessCommandContext(
            uow_factory=uow_factory,
            clock=clock,
            outbox=services.outbox,
            permissions=services.permission_registry,
            subject_exists=_always_exists(),
            audit_actor_id="test",
            audit_trace_id="test",
        )
    )()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        async_client.app = app  # type: ignore[attr-defined]
        yield async_client


@pytest.fixture
async def admin_token(client: Any, uow_factory: UoWFactory, clock: FakeClock) -> str:
    """Register a user, bootstrap the admin role, mint an access token."""

    app = client.app
    services = app.state.services
    identity_ctx = IdentityCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        hasher=services.hasher,
        outbox=services.outbox,
        audit_actor_id="system",
        audit_trace_id="test",
    )
    result = await RegisterLocalUser(identity_ctx)(
        username="admin", email="admin@example.com", password=ADMIN_PASSWORD
    )
    subject_id = result.subject.id

    access_ctx = AccessCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=services.outbox,
        permissions=services.permission_registry,
        subject_exists=_always_exists(),
        audit_actor_id="system",
        audit_trace_id="test",
    )
    await BootstrapAdministrator(access_ctx)(subject_type="identity", subject_id=subject_id)
    return await _mint_token(services, subject_id)


class _AlwaysExists:
    async def exists(self, subject_type: str, subject_id: str) -> bool:
        return True


def _always_exists() -> Any:
    return _AlwaysExists()


async def _mint_token(services: Any, subject_id: str) -> str:
    key = await services.keys.ensure_active_key()
    now = datetime.now(UTC)
    claims = {
        "iss": TEST_ISSUER,
        "sub": subject_id,
        "aud": [TEST_ISSUER, TEST_AUDIENCE],
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "iat": int(now.timestamp()),
        "scope": "openid profile email admin",
        "client_id": "admin",
    }
    return jwt.encode(claims, key.private_key, algorithm="RS256", headers={"kid": key.kid})


async def _mint_token_for(services: Any, subject_id: str) -> str:
    return await _mint_token(services, subject_id)

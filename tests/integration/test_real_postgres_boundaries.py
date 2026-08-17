"""Release acceptance checks against the production PostgreSQL service.

The suite uses SQLite for fast unit/API coverage, while this module always
exercises the client lifecycle and session expiry contracts on PostgreSQL.
``AIYA_DATABASE_URL`` is therefore a required release-test configuration.
"""

from __future__ import annotations

import os
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from inc.capabilities.audit.schemas import AUDIT_EVENT_KEY, AuditEntryRecorded
from inc.capabilities.oidc_provider.api import (
    SESSION_LIFETIME_SECONDS,
    OidcHttpServices,
)
from inc.capabilities.oidc_provider.clients import (
    ClientCommandContext,
    DisableClient,
    EnableClient,
    RegisterClient,
)
from inc.capabilities.oidc_provider.keys import InMemorySigningKeyStore, KeyService
from inc.capabilities.oidc_provider.models import OidcClient, OidcSession
from inc.kernel.db import Base, SqlAlchemyUnitOfWork
from inc.kernel.events import EventSchemaRegistry, OutboxWriter
from inc.kernel.time.fake import FakeClock


def _required_database_url() -> str:
    """Return the production PostgreSQL URL or fail the release gate."""

    value = os.environ.get("AIYA_DATABASE_URL")
    if not value:
        pytest.fail("AIYA_DATABASE_URL is required for PostgreSQL acceptance coverage")
    return value


class _Authenticator:
    async def authenticate(self, username: str, password: str) -> str | None:
        return None


async def test_postgres_enable_client_and_expire_oidc_session() -> None:
    database_url = _required_database_url()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    clock = FakeClock()
    registry = EventSchemaRegistry()
    registry.register(AUDIT_EVENT_KEY, AuditEntryRecorded)
    outbox = OutboxWriter(registry, clock)
    client_id = f"pg-boundary-{uuid.uuid4().hex}"
    subject_id = f"pg-session-{uuid.uuid4().hex}"
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        client_context = ClientCommandContext(
            uow_factory=uow_factory,
            clock=clock,
            outbox=outbox,
            audit_actor_id="integration-test",
            audit_trace_id="postgres-boundary",
        )
        await RegisterClient(client_context)(
            name="PostgreSQL boundary client",
            client_type="public",
            redirect_uris=["http://127.0.0.1:3999/callback"],
            client_id=client_id,
        )
        await DisableClient(client_context)(client_id=client_id)
        enabled = await EnableClient(client_context)(client_id=client_id)
        assert enabled.status == "active"

        keys = KeyService(
            uow_factory=uow_factory,
            store=InMemorySigningKeyStore(),
            clock=clock,
        )
        service = OidcHttpServices(
            issuer="https://integration.example",
            uow_factory=uow_factory,
            clock=clock,
            keys=keys,
            authenticator=_Authenticator(),
            authorization=None,  # type: ignore[arg-type]
            token=None,  # type: ignore[arg-type]
            userinfo=None,  # type: ignore[arg-type]
            revocation=None,  # type: ignore[arg-type]
            logout=None,  # type: ignore[arg-type]
            secure_cookies=True,
        )
        session_handle = await service.establish_session(subject_id, client_id)
        assert await service.subject_from_session(session_handle) == subject_id
        clock.advance(timedelta(seconds=SESSION_LIFETIME_SECONDS + 1))
        assert await service.subject_from_session(session_handle) is None
    finally:
        async with uow_factory() as uow:
            await uow.session.execute(
                delete(OidcSession).where(OidcSession.subject_id == subject_id)
            )
            await uow.session.execute(delete(OidcClient).where(OidcClient.client_id == client_id))
            await uow.commit()
        await engine.dispose()

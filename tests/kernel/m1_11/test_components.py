"""Contract tests for the M1.11 kernel components."""

from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import inc.kernel.audit.models  # noqa: F401
import inc.kernel.auth.models  # noqa: F401
import inc.kernel.identity.models  # noqa: F401
import inc.kernel.mail.models  # noqa: F401
import inc.kernel.rbac.models  # noqa: F401
import inc.kernel.settings.models  # noqa: F401
import inc.kernel.tasks.models  # noqa: F401
from inc.kernel.audit import AuditQuery, AuditService, AuditUnitOfWork
from inc.kernel.auth import AUTH_CODES
from inc.kernel.cache import MemoryCache
from inc.kernel.config import Settings
from inc.kernel.db import DB_CODES, Base, UoWExecutor
from inc.kernel.errors import COMMON_CODES, clear_registry, register_error_codes
from inc.kernel.events import EventBus, register_event_types
from inc.kernel.identity import IDENTITY_CODES
from inc.kernel.mail import (
    MAIL_CODES,
    MailService,
    MailTemplate,
    MailTemplateRegistry,
    MailUnitOfWork,
)
from inc.kernel.rbac import RBAC_CODES
from inc.kernel.security import Principal
from inc.kernel.settings import (
    SETTING_CODES,
    Setting,
    SettingDefinition,
    SettingPatch,
    SettingRegistry,
    SettingsService,
    SettingsUnitOfWork,
    SiteProfileSettings,
)
from inc.kernel.tasks import TASK_CODES
from tests.support.postgres import admin_url, postgres_url

PG_ADMIN_URL = admin_url()
TEST_DB_URL = postgres_url("aiya_test_m111")


class WelcomeContext(BaseModel):
    name: str


class FakeTransport:
    def __init__(self) -> None:
        self.messages = []

    async def send(self, message) -> None:  # type: ignore[no-untyped-def]
        self.messages.append(message)


@pytest.fixture(autouse=True)
def register_codes() -> None:
    clear_registry()
    register_error_codes(
        *COMMON_CODES,
        *DB_CODES,
        *IDENTITY_CODES,
        *RBAC_CODES,
        *AUTH_CODES,
        *TASK_CODES,
        *MAIL_CODES,
        *SETTING_CODES,
    )
    register_event_types("mail.send_failed", "audit.recorded", "setting.updated")


async def _ensure_database() -> None:
    from sqlalchemy import text

    engine = create_async_engine(PG_ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = 'aiya_test_m111'")
            )
            if not exists:
                await connection.execute(text('CREATE DATABASE "aiya_test_m111"'))
    finally:
        await engine.dispose()


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    await _ensure_database()
    engine: AsyncEngine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.mark.asyncio
async def test_mail_outbox_and_settings_and_audit(session_factory) -> None:  # type: ignore[no-untyped-def]
    bus = EventBus(("mail.send_failed", "audit.recorded", "setting.updated"))
    transport = FakeTransport()
    templates = MailTemplateRegistry(
        (MailTemplate("welcome", "Hi {name}", "Hello {name}", WelcomeContext),)
    )
    mail = MailService(
        UoWExecutor(lambda: MailUnitOfWork(session_factory)),
        transport=transport,
        registry=templates,
        event_bus=bus,
        settings=Settings(_env_file=None, cache_backend="memory"),
    )
    audit = AuditService(UoWExecutor(lambda: AuditUnitOfWork(session_factory)), event_bus=bus)
    settings = SettingsService(
        UoWExecutor(lambda: SettingsUnitOfWork(session_factory)),
        MemoryCache(),
        registry=SettingRegistry((SettingDefinition(SiteProfileSettings),)),
        event_bus=bus,
    )
    principal = Principal(id=UUID(int=1), username="admin")

    mail_id = await mail.enqueue("a@example.com", "welcome", WelcomeContext(name="A"))
    assert mail_id
    assert (await mail.get(mail_id)).status == "sent"
    await settings.update("site.profile", SettingPatch(values={"title": "New"}), principal)
    assert (await settings.get("site.profile")).title == "New"  # type: ignore[attr-defined]
    async with session_factory() as session:
        row = await session.scalar(select(Setting).where(Setting.key == "site.profile"))
        assert row is not None
        assert row.value.root == {"title": "New"}
    await audit.record("setting:update", principal, target_type="setting")
    await bus.wait_idle()
    result = await audit.query(AuditQuery(action="setting:update"))
    assert result.total == 1

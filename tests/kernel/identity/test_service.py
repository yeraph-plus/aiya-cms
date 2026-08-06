"""Red tests locking the identity service and user state machine (M1.5).

Contract source: context/kernel/identity.md §4/§6/§11, ADR-0017.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from inc.kernel.db import DB_002, UoWExecutor, integrity_to_app_error
from inc.kernel.errors import COMMON_409, AppError
from inc.kernel.identity import (
    IdentityService,
    IdentityUnitOfWork,
    UserCreate,
    UserRead,
)
from inc.kernel.identity.models import Identity, UserStatus


def _service(session_factory: async_sessionmaker[AsyncSession]) -> IdentityService:
    return IdentityService(UoWExecutor(lambda: IdentityUnitOfWork(session_factory)))


async def test_create_user_roundtrip_and_get(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(session_factory)
    created = await service.create_user(
        UserCreate(username="alice", email="alice@example.com", display_name="Alice")
    )

    assert isinstance(created.id, uuid.UUID)
    assert created.username == "alice"
    assert created.email == "alice@example.com"
    assert created.display_name == "Alice"
    assert created.status == UserStatus.ACTIVE

    fetched = await service.get_user(created.id)
    assert fetched == created


async def test_get_user_missing_raises_user_001(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(session_factory)
    with pytest.raises(AppError) as excinfo:
        await service.get_user(uuid.uuid4())
    assert excinfo.value.code.code == "USER_001"
    assert excinfo.value.code.http_status == 404


async def test_create_user_duplicate_username_maps_to_db_002(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(session_factory)
    await service.create_user(UserCreate(username="dup", email="a@example.com", display_name="A"))
    with pytest.raises(AppError) as excinfo:
        await service.create_user(
            UserCreate(username="dup", email="b@example.com", display_name="B")
        )
    assert excinfo.value.code == DB_002
    assert excinfo.value.code.http_status == 409


async def test_create_user_duplicate_email_maps_to_db_002(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(session_factory)
    await service.create_user(UserCreate(username="x", email="same@example.com", display_name="X"))
    with pytest.raises(AppError) as excinfo:
        await service.create_user(
            UserCreate(username="y", email="same@example.com", display_name="Y")
        )
    assert excinfo.value.code == DB_002


async def test_get_users_batch_is_single_query_without_misses(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
) -> None:
    service = _service(session_factory)
    ids = [
        (
            await service.create_user(
                UserCreate(username=f"u{i}", email=f"u{i}@example.com", display_name=f"U{i}")
            )
        ).id
        for i in range(3)
    ]

    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _capture)
    try:
        result = await service.get_users([*ids, uuid.uuid4()])
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _capture)

    assert set(result) == set(ids)
    assert all(isinstance(v, UserRead) for v in result.values())
    assert sum("FROM users" in s for s in statements) == 1


async def test_ban_unban_lifecycle(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(session_factory)
    user = await service.create_user(
        UserCreate(username="banme", email="ban@example.com", display_name="B")
    )

    banned = await service.ban(user.id)
    assert banned.status == UserStatus.BANNED

    with pytest.raises(AppError) as excinfo:
        await service.ban(user.id)
    assert excinfo.value.code == COMMON_409

    unbanned = await service.unban(user.id)
    assert unbanned.status == UserStatus.ACTIVE

    with pytest.raises(AppError) as excinfo:
        await service.unban(user.id)
    assert excinfo.value.code == COMMON_409


async def test_unban_publishes_audit_lifecycle_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from inc.kernel.events import fresh_event_bus
    from inc.kernel.security import Principal

    bus = fresh_event_bus()
    service = IdentityService(
        UoWExecutor(lambda: IdentityUnitOfWork(session_factory)), event_bus=bus
    )
    events = []

    async def collect(event) -> None:  # type: ignore[no-untyped-def]
        events.append(event)

    bus.subscribe("user.banned", collect)
    bus.subscribe("user.unbanned", collect)
    bus.freeze()
    user = await service.create_user(
        UserCreate(username="audit_unban", email="audit-unban@example.com", display_name="A")
    )
    actor = Principal(id=uuid.uuid4(), username="admin")
    await service.ban(user.id, actor)
    await bus.wait_idle()
    await service.unban(user.id, actor)
    await bus.wait_idle()

    assert [event.type for event in events] == ["user.banned", "user.unbanned"]


async def test_delete_anonymizes_and_is_terminal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(session_factory)
    user = await service.create_user(
        UserCreate(username="gone", email="gone@example.com", display_name="G")
    )

    deleted = await service.delete(user.id)
    assert deleted.status == UserStatus.DELETED
    assert deleted.email.startswith("deleted-")
    assert deleted.email.endswith("@invalid.local")
    assert deleted.username.startswith("deleted-")
    assert deleted.email != user.email
    assert deleted.username != user.username

    # deleted is terminal: no further transitions, including re-delete
    with pytest.raises(AppError) as excinfo:
        await service.ban(user.id)
    assert excinfo.value.code == COMMON_409

    with pytest.raises(AppError) as excinfo:
        await service.delete(user.id)
    assert excinfo.value.code == COMMON_409

    # anonymized values free the original username/email for reuse
    reuse = await service.create_user(
        UserCreate(username="gone", email="gone@example.com", display_name="R")
    )
    assert reuse.username == "gone"


async def test_delete_releases_password_identity_and_clears_secret(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(session_factory)
    user = await service.create_user(
        UserCreate(username="credential", email="credential@example.com", display_name="C")
    )

    async with IdentityUnitOfWork(session_factory) as uow:
        await uow.identities.add(
            Identity(
                user_id=user.id,
                provider="password",
                provider_uid=user.email,
                secret_hash="hash",
                verified=True,
            )
        )
        await uow.commit()

    await service.delete(user.id)

    async with IdentityUnitOfWork(session_factory) as uow:
        identities = await uow.identities.list_for_user(user.id)
        assert len(identities) == 1
        assert identities[0].provider_uid != user.email
        assert identities[0].secret_hash is None
        assert identities[0].verified is False


async def test_concurrent_delete_and_ban_preserves_deleted_terminal_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(session_factory)
    user = await service.create_user(
        UserCreate(username="race", email="race@example.com", display_name="Race")
    )

    results = await asyncio.gather(
        service.delete(user.id),
        service.ban(user.id),
        return_exceptions=True,
    )

    assert sum(isinstance(result, UserRead) for result in results) == 1
    assert sum(isinstance(result, AppError) for result in results) == 1
    assert (await service.get_user(user.id)).status == UserStatus.DELETED


async def test_missing_user_for_transition_raises_user_001(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(session_factory)
    with pytest.raises(AppError) as excinfo:
        await service.ban(uuid.uuid4())
    assert excinfo.value.code.code == "USER_001"


async def test_unique_identity_provider_uid_violation_maps_to_db_002(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(session_factory)
    user = await service.create_user(
        UserCreate(username="i1", email="i1@example.com", display_name="I1")
    )

    async with IdentityUnitOfWork(session_factory) as uow:
        await uow.identities.add(
            Identity(user_id=user.id, provider="password", provider_uid="i1@example.com")
        )
        await uow.commit()

    with pytest.raises(IntegrityError) as excinfo:
        async with IdentityUnitOfWork(session_factory) as uow:
            await uow.identities.add(
                Identity(user_id=user.id, provider="password", provider_uid="i1@example.com")
            )
            await uow.commit()

    mapped = integrity_to_app_error(excinfo.value)
    assert mapped.code == DB_002
    assert mapped.code.http_status == 409

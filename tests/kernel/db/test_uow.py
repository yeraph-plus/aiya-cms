"""Red tests locking the AbstractUnitOfWork transaction boundary (M1.2 db).

Contract source: context/kernel/db-uow-repository.md §3/§11
"""

import asyncio

import pytest
from _samples import SamplePayload, SampleRepository, SampleUnitOfWork, SampleUser
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inc.kernel.db import DB_002, UoWExecutor, integrity_to_app_error


async def test_uncommitted_exit_rolls_back(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user = SampleUser(email="ghost@example.com", payload=SamplePayload(tags=[], score=0.0))

    async with SampleUnitOfWork(session_factory) as uow:
        await uow.users.add(user)

    # uow exited without commit -> row must not be visible to a fresh session
    async with session_factory() as check:
        repo = SampleRepository(check)
        assert await repo.get_or_none(user.id) is None


async def test_commit_makes_data_visible(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user = SampleUser(email="kept@example.com", payload=SamplePayload(tags=["kept"], score=2.0))

    async with SampleUnitOfWork(session_factory) as uow:
        await uow.users.add(user)
        await uow.commit()

    async with session_factory() as check:
        repo = SampleRepository(check)
        assert await repo.get_or_none(user.id) is not None


async def test_updated_at_auto_refreshes_after_commit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user = SampleUser(email="touch@example.com", payload=SamplePayload(tags=[], score=0.0))

    async with SampleUnitOfWork(session_factory) as uow:
        await uow.users.add(user)
        await uow.commit()
        await uow.session.refresh(user)
        created_at = user.created_at
        updated_at = user.updated_at

        assert created_at is not None
        assert updated_at is not None

        await asyncio.sleep(0.02)
        user.email = "touch2@example.com"
        await uow.commit()
        await uow.session.refresh(user)

    assert user.updated_at > updated_at
    assert user.created_at == created_at


async def test_unique_violation_maps_to_db_002(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    email = "unique@example.com"

    async with SampleUnitOfWork(session_factory) as uow:
        await uow.users.add(SampleUser(email=email, payload=SamplePayload(tags=[], score=0.0)))
        await uow.commit()

    with pytest.raises(IntegrityError) as excinfo:
        async with SampleUnitOfWork(session_factory) as uow:
            await uow.users.add(SampleUser(email=email, payload=SamplePayload(tags=[], score=1.0)))
            await uow.commit()

    mapped = integrity_to_app_error(excinfo.value)
    assert mapped.code == DB_002
    assert mapped.code.http_status == 409


async def test_uow_executor_owns_write_commit_and_read_rollback(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    executor = UoWExecutor(lambda: SampleUnitOfWork(session_factory))
    user = SampleUser(email="executor@example.com", payload=SamplePayload(tags=[], score=1.0))

    async def add(uow: SampleUnitOfWork) -> None:
        await uow.users.add(user)

    await executor.write(add)

    async def read(uow: SampleUnitOfWork) -> SampleUser | None:
        return await uow.users.get_or_none(user.id)

    assert await executor.read(read) is not None

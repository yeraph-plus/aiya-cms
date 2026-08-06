"""Red tests locking the Repository generic primitives (M1.2 db).

Contract source: context/kernel/db-uow-repository.md §3/§11
"""

import pytest
from _samples import SamplePayload, SampleRepository, SampleUser
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from inc.kernel.db import Page, Repository, new_uuid7


async def test_repository_generic_returns_model_type(session: AsyncSession) -> None:
    repo: Repository[SampleUser] = SampleRepository(session)

    found = await repo.get_or_none(new_uuid7())

    assert found is None


async def test_add_commit_get_roundtrip(session: AsyncSession) -> None:
    repo = SampleRepository(session)
    user = SampleUser(
        email="roundtrip@example.com",
        payload=SamplePayload(tags=["a"], score=1.0),
    )

    await repo.add(user)
    await session.commit()

    got = await repo.get_or_none(user.id)
    assert got is not None
    assert isinstance(got, SampleUser)
    assert got.email == "roundtrip@example.com"


async def test_get_raises_when_missing(session: AsyncSession) -> None:
    repo = SampleRepository(session)

    with pytest.raises(NoResultFound):
        await repo.get(new_uuid7())


async def test_delete_removes_row(session: AsyncSession) -> None:
    repo = SampleRepository(session)
    user = SampleUser(
        email="del@example.com",
        payload=SamplePayload(tags=[], score=0.0),
    )
    await repo.add(user)
    await session.commit()

    await repo.delete(user)
    await session.commit()

    assert await repo.get_or_none(user.id) is None


async def test_list_paginates(session: AsyncSession) -> None:
    repo = SampleRepository(session)
    for i in range(25):
        await repo.add(
            SampleUser(
                email=f"user{i}@example.com",
                payload=SamplePayload(tags=[str(i)], score=float(i)),
            )
        )
    await session.commit()

    page1 = await repo.list(page=1, size=10)
    assert isinstance(page1, Page)
    assert page1.total == 25
    assert page1.page == 1
    assert page1.size == 10
    assert len(page1.items) == 10

    page3 = await repo.list(page=3, size=10)
    assert len(page3.items) == 5

    beyond = await repo.list(page=99, size=10)
    assert beyond.items == []
    assert beyond.total == 25


async def test_subclass_specific_query(session: AsyncSession) -> None:
    repo = SampleRepository(session)
    user = SampleUser(
        email="byemail@example.com",
        payload=SamplePayload(tags=[], score=0.0),
    )
    await repo.add(user)
    await session.commit()

    assert (await repo.get_by_email("byemail@example.com")) is not None
    assert await repo.get_by_email("missing@example.com") is None

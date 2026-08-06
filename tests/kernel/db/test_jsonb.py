"""Red tests locking the JsonBModel type decorator (M1.2 db).

Contract source: context/kernel/db-uow-repository.md §3/§11
"""

import pytest
from _samples import SamplePayload, SampleUser
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_jsonb_roundtrip_preserves_model_and_fields(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user = SampleUser(
        email="jsonb@example.com",
        payload=SamplePayload(tags=["alpha", "beta"], score=3.5),
    )
    session.add(user)
    await session.commit()

    # read from a fresh session so the row passes through process_result_value
    async with session_factory() as check:
        result = await check.scalar(select(SampleUser).where(SampleUser.id == user.id))

    assert result is not None
    payload = result.payload
    assert isinstance(payload, SamplePayload)
    assert payload.tags == ["alpha", "beta"]
    assert payload.score == 3.5


async def test_jsonb_accepts_raw_dict_and_validates(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user = SampleUser(
        email="dict@example.com",
        payload={"tags": ["dict"], "score": 1.25},
    )
    session.add(user)
    await session.commit()

    async with session_factory() as check:
        result = await check.scalar(select(SampleUser).where(SampleUser.id == user.id))

    assert isinstance(result.payload, SamplePayload)
    assert result.payload.tags == ["dict"]
    assert result.payload.score == 1.25


async def test_jsonb_rejects_invalid_payload(session: AsyncSession) -> None:
    user = SampleUser(
        email="bad@example.com",
        payload={"tags": 42, "score": "not-a-number"},
    )
    session.add(user)

    with pytest.raises(StatementError) as excinfo:
        await session.flush()
    # SQLAlchemy wraps the bind-processor failure; the cause is a Pydantic
    # validation error, which is the contract a caller should inspect.
    assert isinstance(excinfo.value.orig, ValidationError)

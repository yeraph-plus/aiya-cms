"""Database primitive tests: conventions, JSONB, UoW, pagination, ownership."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import Integer, String, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import (
    Base,
    JsonBModel,
    Page,
    SqlAlchemyUnitOfWork,
    TableOwnership,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    fetch_page,
    new_uuid7,
)


class _Sample(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "test_sample"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)


class _Payload(BaseModel):
    schema_version: str
    tags: list[str] = []
    value: int = 0


class _JsonSample(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "test_json_sample"

    payload: Mapped[_Payload] = mapped_column(JsonBModel(_Payload, "1"), nullable=False)


@pytest.fixture
def session_factory(db_engine: AsyncEngine) -> async_sessionmaker[Any]:
    return async_sessionmaker(db_engine, expire_on_commit=False, autoflush=False)


def test_uuid7_and_conventions() -> None:
    assert isinstance(new_uuid7(), uuid.UUID)
    assert new_uuid7() != new_uuid7()
    row = _Sample()
    # app-side defaults apply at insert, not at construction
    assert row.id is None
    assert row.created_at is None


async def test_uow_commit_rollback_and_exception(
    session_factory: async_sessionmaker[Any],
) -> None:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        uow.session.add(_Sample(name="committed", rank=0))
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        uow.session.add(_Sample(name="rolled-back", rank=0))
        # no commit -> exit rolls back

    with pytest.raises(RuntimeError):
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            uow.session.add(_Sample(name="exception", rank=0))
            await uow.session.flush()
            raise RuntimeError("boom")

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        names = (await uow.session.execute(select(_Sample.name))).scalars().all()
        assert set(names) == {"committed"}


async def test_uow_session_unavailable_outside_context(
    session_factory: async_sessionmaker[Any],
) -> None:
    uow = SqlAlchemyUnitOfWork(session_factory)
    with pytest.raises(RuntimeError):
        _ = uow.session


async def test_jsonb_roundtrip_and_envelope(session_factory: async_sessionmaker[Any]) -> None:
    payload = _Payload(schema_version="1", tags=["a", "b"], value=7)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        uow.session.add(_JsonSample(payload=payload))
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        row = (await uow.session.execute(select(_JsonSample))).scalars().first()
        assert row is not None
        assert isinstance(row.payload, _Payload)
        assert row.payload.tags == ["a", "b"]
        assert row.payload.value == 7


def test_jsonb_rejects_unbound_value() -> None:
    with pytest.raises(TypeError):
        JsonBModel(_Payload, "1").process_bind_param({"not": "bound"}, None)


def test_jsonb_requires_schema_version() -> None:
    with pytest.raises(ValueError):
        JsonBModel(_Payload, "")


async def test_fetch_page_same_filter_total(session_factory: async_sessionmaker[Any]) -> None:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        for i in range(7):
            uow.session.add(_Sample(name=f"row-{i}", rank=i))
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        statement = select(_Sample).where(_Sample.rank >= 2).order_by(_Sample.rank, _Sample.id)
        page: Page[_Sample] = await fetch_page(uow.session, statement, page=2, size=2)
        assert page.total == 5  # same filter counts all matches
        assert [row.name for row in page.items] == ["row-4", "row-5"]
        assert page.page == 2
        assert page.size == 2


async def test_fetch_page_rejects_bad_args(session_factory: async_sessionmaker[Any]) -> None:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        statement = select(_Sample).order_by(_Sample.id)
        with pytest.raises(ValueError):
            await fetch_page(uow.session, statement, page=0, size=10)
        with pytest.raises(ValueError):
            await fetch_page(uow.session, statement, page=1, size=0)
        with pytest.raises(ValueError):
            await fetch_page(uow.session, statement, page=1, size=201)


def test_table_ownership_decorator_and_assert() -> None:
    assert TableOwnership.owner_of("kernel_outbox") == "kernel:events"

    with pytest.raises(ValueError):
        TableOwnership.owned_by("someone:else")

    TableOwnership.assert_owner("kernel_outbox", "kernel:events")
    with pytest.raises(Exception) as excinfo:
        TableOwnership.assert_owner("kernel_outbox", "kernel:tasks")
    assert "kernel:events" in str(excinfo.value)

    snapshot = TableOwnership.snapshot()
    assert snapshot["kernel_workflow_instances"] == "kernel:workflow"
    assert snapshot["kernel_task_instances"] == "kernel:tasks"

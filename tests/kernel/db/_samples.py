"""Sample domain models for the kernel db component tests (M1.2).

Kept on a private :class:`_TestBase` metadata so they never leak into the app
``Base.metadata`` that Alembic targets (the db component builds no business
tables, spec §5).
"""

import uuid

from pydantic import BaseModel
from sqlalchemy import String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from inc.kernel.db import (
    AbstractUnitOfWork,
    JsonBModel,
    Repository,
    TimestampMixin,
    new_uuid7,
)


class _TestBase(DeclarativeBase):
    """Private metadata root for sample tables."""


class SamplePayload(BaseModel):
    tags: list[str]
    score: float


class SampleUser(_TestBase, TimestampMixin):
    __tablename__ = "db_test_sample_users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    payload: Mapped[SamplePayload] = mapped_column(JsonBModel(SamplePayload), nullable=False)


class SampleRepository(Repository[SampleUser]):
    """Concrete repository over :class:`SampleUser` for the primitive tests."""

    model = SampleUser

    async def get_by_email(self, email: str) -> SampleUser | None:
        from sqlalchemy import select

        result = await self.session.scalars(select(SampleUser).where(SampleUser.email == email))
        return result.first()


class SampleUnitOfWork(AbstractUnitOfWork):
    """Concrete UoW exposing the :class:`SampleRepository` as ``users``."""

    @property
    def users(self) -> SampleRepository:
        return SampleRepository(self.session)

"""Generic single-aggregate repository base (spec §3/§6).

Subclasses declare ``model = ConcreteModel`` and add their specific queries;
the ``ModelT`` type parameter keeps the primitives statically typed.
"""

from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from sqlalchemy import ColumnElement, func, inspect, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper

from .page import Page


class Repository[ModelT]:
    """Base repository primitives over one aggregate; commit is the UoW's job."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: UUID) -> ModelT:
        """Return the aggregate by primary key, raising NoResultFound if absent."""
        item = await self.get_or_none(id)
        if item is None:
            raise NoResultFound(f"{self.model.__name__} with id={id} not found")
        return item

    async def get_or_none(self, id: UUID) -> ModelT | None:
        """Return the aggregate by primary key, or None."""
        pk = self._primary_key()
        result = await self.session.scalars(select(self.model).where(pk == id))
        return result.first()

    async def get_for_update_or_none(self, id: UUID) -> ModelT | None:
        """Return the aggregate while locking its row for the current transaction."""
        pk = self._primary_key()
        stmt = select(self.model).where(pk == id).with_for_update()
        result = await self.session.scalars(stmt)
        return result.first()

    async def list(self, *, page: int = 1, size: int = 20) -> Page[ModelT]:
        """Return a paginated slice ordered by primary key (insertion order for UUIDv7)."""
        page = max(page, 1)
        size = min(max(size, 1), 100)
        total = await self._count()
        stmt = (
            select(self.model)
            .order_by(*self._default_order())
            .limit(size)
            .offset((page - 1) * size)
        )
        rows = (await self.session.scalars(stmt)).all()
        return Page(items=[*rows], total=total, page=page, size=size)

    async def add(self, model: ModelT) -> None:
        """Queue ``model`` for insertion."""
        self.session.add(model)

    async def delete(self, model: ModelT) -> None:
        """Queue ``model`` for deletion."""
        await self.session.delete(model)

    async def _count(self) -> int:
        result = await self.session.scalar(select(func.count()).select_from(self.model))
        return int(result or 0)

    def _primary_key(self) -> ColumnElement[Any]:
        mapper = cast(Mapper[Any], inspect(self.model))
        if len(mapper.primary_key) != 1:
            raise TypeError(f"{self.model.__name__} must have a single-column primary key")
        return mapper.primary_key[0]

    def _default_order(self) -> Sequence[ColumnElement[Any]]:
        mapper = cast(Mapper[Any], inspect(self.model))
        return mapper.primary_key

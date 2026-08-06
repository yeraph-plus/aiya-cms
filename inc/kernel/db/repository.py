"""Generic repository primitive.

Contract source: context/spec/kernel/database.md §2.

A repository wraps persistence for one aggregate and never returns ORM
objects to services or handlers; DTO conversion happens at the public
boundary. This base provides only save/delete plumbing; business queries
are concrete per-aggregate methods.
"""

from __future__ import annotations

from typing import Any

from inc.kernel.db.base import Base
from inc.kernel.db.uow import UnitOfWork


class Repository[T: Base]:
    """Persistence wrapper bound to one UoW."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    @property
    def session(self) -> Any:
        return self._uow.session

    def add(self, entity: T) -> None:
        self.session.add(entity)

    async def delete(self, entity: T) -> None:
        await self.session.delete(entity)

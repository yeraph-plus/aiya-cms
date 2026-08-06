"""Database primitives: Base, Repository/UoW contracts, pagination, JSONB.

Contract source: context/spec/kernel/database.md.

Importing this package registers no connections and creates no tables.
"""

from __future__ import annotations

from inc.kernel.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, new_uuid7
from inc.kernel.db.database import create_engine, create_session_factory
from inc.kernel.db.jsonb import JsonBModel
from inc.kernel.db.ownership import TableOwnership
from inc.kernel.db.page import MAX_PAGE_SIZE, Page, fetch_page
from inc.kernel.db.repository import Repository
from inc.kernel.db.uow import SqlAlchemyUnitOfWork, UnitOfWork, UoWFactory

__all__ = [
    "Base",
    "JsonBModel",
    "MAX_PAGE_SIZE",
    "Page",
    "Repository",
    "SqlAlchemyUnitOfWork",
    "TableOwnership",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "UnitOfWork",
    "UoWFactory",
    "create_engine",
    "create_session_factory",
    "fetch_page",
    "new_uuid7",
]

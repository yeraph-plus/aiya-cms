"""Table ownership declaration.

Contract source: context/spec/kernel/database.md §5.

Every table registers exactly one owner — ``kernel:<component>`` or
``capability:<name>`` — via a class decorator at model definition time.
Ownership is metadata, not runtime behavior: nothing connects or starts
because a model is imported. Alembic validation and migration guards use
``assert_owner`` to reject revisions touching sibling tables.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from inc.kernel.db.base import Base
from inc.kernel.errors import ErrorCategory, KernelError

_OWNER_PATTERN = ("kernel:", "capability:")


class TableOwnership:
    """Registry of table -> owner declared at model definition time."""

    _entries: ClassVar[dict[str, str]] = {}

    @classmethod
    def owned_by(cls, owner: str) -> Callable[[type[Base]], type[Base]]:
        """Class decorator declaring the owning component of a table."""

        if not owner.startswith(_OWNER_PATTERN):
            raise ValueError(
                f"invalid table owner {owner!r}: expected kernel:<component> or capability:<name>"
            )
        if owner.startswith("kernel:"):
            component = owner.removeprefix("kernel:")
            if not component or any(part.isspace() for part in component):
                raise ValueError(f"invalid kernel table owner {owner!r}")

        def decorator(model: type[Base]) -> type[Base]:
            table = model.__tablename__
            if table in cls._entries and cls._entries[table] != owner:
                raise ValueError(f"table {table!r} already owned by {cls._entries[table]!r}")
            cls._entries[table] = owner
            return model

        return decorator

    @classmethod
    def owner_of(cls, table: str) -> str | None:
        return cls._entries.get(table)

    @classmethod
    def assert_owner(cls, table: str, owner: str) -> None:
        """Fail-fast when a migration/owner writes a foreign table."""

        declared = cls._entries.get(table)
        if declared is None:
            raise KernelError(
                code="kernel.table_ownership",
                category=ErrorCategory.INTERNAL,
                message=f"table {table!r} has no declared owner",
            )
        if declared != owner:
            raise KernelError(
                code="kernel.table_ownership",
                category=ErrorCategory.INTERNAL,
                message=f"table {table!r} is owned by {declared!r}, not {owner!r}",
            )

    @classmethod
    def snapshot(cls) -> dict[str, str]:
        return dict(cls._entries)

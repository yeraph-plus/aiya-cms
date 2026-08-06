"""Architecture guards for the kernel db component (M1.2).

Contract source: context/kernel/db-uow-repository.md §1/§5, ADR-0003.

Two enforceable rules:

- **Session red-line** (ADR-0003 / dependency-rules §1.5): session/connection
  creation (async_sessionmaker, create_async_engine, AsyncSession, AsyncEngine,
  asyncpg) is only allowed inside ``inc/kernel/db``, never in kernel
  siblings, api, or modules. Declaring models with sqlalchemy types is fine.
- **Table conventions** (spec §5): single ``id`` UUIDv7 primary key with an
  app-side default, tz-aware ``created_at``/``updated_at``, and JSONB columns
  only via :class:`JsonBModel`.
"""

import re
import uuid
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import Integer, String, Uuid
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TimestampMixin, new_uuid7


class _ConformingBase(DeclarativeBase):
    """Metadata whose only table obeys the conventions."""


class _ConformingPayload(BaseModel):
    tags: list[str]


class _Conforming(_ConformingBase, TimestampMixin):
    __tablename__ = "db_convention_conforming"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    email: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[_ConformingPayload] = mapped_column(JsonBModel(_ConformingPayload))


class _NonConformingBase(DeclarativeBase):
    """Metadata whose table breaks every convention."""


class _NonConforming(_NonConformingBase):
    __tablename__ = "db_convention_bad"

    key: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    data: Mapped[dict] = mapped_column(postgresql.JSONB)


def _metadata_violations(metadata: object) -> list[str]:
    """Return the convention violations found across ``metadata`` (spec §5)."""
    violations: list[str] = []
    association_tables = {"role_permissions", "user_roles", "term_relationships"}
    # M1.11 append-only audit and key/value settings use their documented
    # natural keys and timestamp shape rather than aggregate conventions.
    special_tables = {"audit_logs", "settings"}
    for table_name, table in metadata.tables.items():  # type: ignore[attr-defined]
        # RBAC association tables are the explicit composite-key exception in
        # ADR-0019; they have no aggregate timestamps by design.
        if table_name in association_tables:
            continue
        if table_name in special_tables:
            continue
        pk_columns = table.primary_key.columns
        if len(pk_columns) != 1:
            violations.append(f"{table_name}: expected a single-column primary key")
        else:
            pk = pk_columns[0]
            if pk.name != "id":
                violations.append(f"{table_name}: primary key must be named 'id'")
            if pk.type.python_type is not uuid.UUID:
                violations.append(f"{table_name}: primary key must be a UUID")
            if pk.default is None:
                violations.append(f"{table_name}: primary key must be generated app-side")
        for colname in ("created_at", "updated_at"):
            col = table.columns.get(colname)
            if col is None:
                violations.append(f"{table_name}: missing {colname}")
            elif (
                col.type.python_type is not datetime
                or getattr(col.type, "timezone", None) is not True
            ):
                violations.append(f"{table_name}: {colname} must be a tz-aware datetime")
        for col in table.columns:
            if isinstance(col.type, postgresql.JSONB):
                violations.append(f"{table_name}.{col.name}: JSONB must use JsonBModel")
    return violations


def test_conforming_metadata_passes() -> None:
    assert _metadata_violations(_ConformingBase.metadata) == []


def test_non_conforming_metadata_is_reported() -> None:
    violations = _metadata_violations(_NonConformingBase.metadata)

    assert any("must be named 'id'" in v for v in violations)
    assert any("must be a UUID" in v for v in violations)
    assert any("must be generated app-side" in v for v in violations)
    assert any("missing created_at" in v for v in violations)
    assert any("missing updated_at" in v for v in violations)
    assert any("JSONB must use JsonBModel" in v for v in violations)


def test_db_component_defines_no_tables() -> None:
    # spec §5: the db component itself creates no tables
    db_root = Path(__file__).parents[2] / "inc" / "kernel" / "db"
    for path in db_root.rglob("*.py"):
        assert "__tablename__" not in path.read_text(encoding="utf-8"), (
            f"{path.name} defines a table inside the db component"
        )


def test_registered_business_tables_follow_conventions() -> None:
    # every table the app registers on Base (identity/rbac/auth)
    # must obey spec §5
    import inc.kernel.auth.models  # noqa: F401  (registers auth models on Base)
    import inc.kernel.comment.models  # noqa: F401
    import inc.kernel.content.models  # noqa: F401
    import inc.kernel.identity  # noqa: F401  (registers models on Base)
    import inc.kernel.rbac.models  # noqa: F401  (registers RBAC models on Base)
    import inc.kernel.tasks.models  # noqa: F401  (registers task models on Base)
    import inc.kernel.taxonomy.models  # noqa: F401

    assert _metadata_violations(Base.metadata) == []


_SESSION_SYMBOLS = (
    "async_sessionmaker",
    "create_async_engine",
    "AsyncSession",
    "AsyncEngine",
)

# asyncpg appears legitimately inside connection strings (the default
# AIYA_DATABASE_URL is "postgresql+asyncpg://..."), so only flag real driver
# usage: attribute access (asyncpg.connect / asyncpg.create_pool) or imports.
_ASYNCPG_PATTERNS = (r"\basyncpg\.", r"\bimport asyncpg\b")


def test_session_creation_confined_to_db_component() -> None:
    # ADR-0003 / 01-dependency-rules §1.5: sessions/connections only ever exist
    # inside kernel/db. Components may import sqlalchemy types and select to
    # declare models and write queries, but must never open a session/engine.
    source_root = Path(__file__).parents[2] / "inc"
    allowed_prefix = str(source_root / "kernel" / "db")
    offenders: list[str] = []
    for path in source_root.rglob("*.py"):
        if str(path).startswith(allowed_prefix):
            continue
        content = path.read_text(encoding="utf-8")
        for symbol in _SESSION_SYMBOLS:
            if re.search(rf"\b{symbol}\b", content):
                offenders.append(f"{path.relative_to(source_root)}: {symbol}")
        # ADR-0011 explicitly permits the tasks shell to own one independent
        # asyncpg LISTEN connection; all other connection creation remains in db.
        allows_task_listener = path.parts[-2:] == ("tasks", "scheduler.py")
        for pattern in _ASYNCPG_PATTERNS:
            if not allows_task_listener and re.search(pattern, content):
                offenders.append(f"{path.relative_to(source_root)}: asyncpg")
    assert offenders == []

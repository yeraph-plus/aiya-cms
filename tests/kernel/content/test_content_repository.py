"""G3 red tests for SQL Content query and trash-purge semantics."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib import import_module
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql


def _repositories_module():
    try:
        return import_module("inc.kernel.content.repositories")
    except ModuleNotFoundError as exc:  # pragma: no cover - G3 red assertion
        pytest.fail("G3 target missing: inc.kernel.content.repositories")
        raise AssertionError from exc


class _Rows:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = rows or []

    def all(self) -> list[Any]:
        return self._rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _Session:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def scalar(self, statement: Any) -> int:
        self.statements.append(statement)
        return 0

    async def scalars(self, statement: Any) -> _Rows:
        self.statements.append(statement)
        return _Rows()

    async def execute(self, statement: Any) -> _Rows:
        self.statements.append(statement)
        return _Rows()


@pytest.mark.asyncio
async def test_content_query_searches_excerpt_and_sorts_by_comment_count() -> None:
    repositories = _repositories_module()
    session = _Session()

    page = await repositories.ContentRepository(session).list_for_type(
        "post",
        statuses=["published"],
        q="seo",
        sort="comment_count",
        order="desc",
    )

    sql = "\n".join(
        str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for statement in session.statements
    )
    assert page.total == 0
    assert "contents.excerpt ILIKE" in sql
    assert "contents.comment_count DESC" in sql


@pytest.mark.asyncio
async def test_comment_count_delta_keeps_content_type_scope() -> None:
    repositories = _repositories_module()
    session = _Session()
    await repositories.ContentRepository(session).apply_comment_count_delta(
        uuid4(), 1, content_type="post"
    )
    sql = str(
        session.statements[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "contents.id" in sql
    assert "contents.type = 'post'" in sql
    assert "greatest(contents.comment_count + 1, 0)" in sql


@pytest.mark.asyncio
async def test_purge_uses_trashed_at_instead_of_updated_at() -> None:
    repositories = _repositories_module()
    session = _Session()
    await repositories.ContentRepository(session).purge_trash_before(datetime.now(UTC))

    sql = str(
        session.statements[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "contents.status = 'trash'" in sql
    assert "contents.trashed_at" in sql
    assert "WHERE contents.status = 'trash' AND contents.updated_at" not in sql

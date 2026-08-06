"""G5 red tests for comment query scoping and stable SQL ordering."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib import import_module
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql


def _repositories_module():
    try:
        return import_module("inc.kernel.comment.repositories")
    except ModuleNotFoundError as exc:  # pragma: no cover - G5 red assertion
        pytest.fail("G5 target missing: inc.kernel.comment.repositories")
        raise AssertionError from exc


class _Rows:
    def all(self) -> list[Any]:
        return []

    def first(self) -> Any:
        return None


class _Session:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def scalar(self, statement: Any) -> int:
        self.statements.append(statement)
        return 0

    async def scalars(self, statement: Any) -> _Rows:
        self.statements.append(statement)
        return _Rows()


@pytest.mark.asyncio
async def test_moderation_query_supports_keyword_filters_and_updated_sort() -> None:
    repositories = _repositories_module()
    session = _Session()
    await repositories.CommentRepository(session).list_moderation(
        status="approved",
        target_type="post",
        target_id=uuid4(),
        q="hello",
        updated_from=datetime(2026, 1, 1, tzinfo=UTC),
        sort="updated_at",
        order="desc",
    )
    sql = "\n".join(
        str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for statement in session.statements
    )
    assert "comments.status = 'approved'" in sql
    assert "comments.target_type = 'post'" in sql
    assert "comments.content ILIKE" in sql
    assert "comments.updated_at DESC" in sql


@pytest.mark.asyncio
async def test_thread_queries_keep_target_scope_and_root_descendant_shape() -> None:
    repositories = _repositories_module()
    session = _Session()
    target_id = uuid4()
    await repositories.CommentRepository(session).list_roots(
        "post", target_id, approved_only=True, page=1, size=20
    )
    await repositories.CommentRepository(session).list_descendants([uuid4()], approved_only=True)
    sql = "\n".join(
        str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for statement in session.statements
    )
    assert "comments.target_type = 'post'" in sql
    assert "comments.parent_id IS NULL" in sql
    assert "comments.root_id IN" in sql

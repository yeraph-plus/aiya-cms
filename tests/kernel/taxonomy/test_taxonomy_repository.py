"""G4 red tests for taxonomy SQL scope and grouped filtering."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib import import_module
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql


def _repositories_module():
    try:
        return import_module("inc.kernel.taxonomy.repositories")
    except ModuleNotFoundError as exc:  # pragma: no cover - G4 red assertion
        pytest.fail("G4 target missing: inc.kernel.taxonomy.repositories")
        raise AssertionError from exc


class _Rows:
    def all(self) -> list[Any]:
        return []


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
async def test_term_list_searches_name_slug_and_keeps_type_scope() -> None:
    repositories = _repositories_module()
    session = _Session()

    await repositories.TermRepository(session).list_filtered(
        "post",
        q="news",
        sort="updated_at",
        order="desc",
        updated_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    sql = "\n".join(
        str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for statement in session.statements
    )

    assert "terms.content_type = 'post'" in sql
    assert "terms.name ILIKE" in sql
    assert "terms.slug ILIKE" in sql
    assert "terms.updated_at DESC" in sql


@pytest.mark.asyncio
async def test_grouped_filter_is_same_group_or_and_cross_group_and() -> None:
    repositories = _repositories_module()
    session = _Session()

    await repositories.TermRepository(session).content_ids_for_filter(
        "post", {"category": ("news", "tech"), "tag": ("featured",)}
    )
    sql = str(
        session.statements[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )

    assert "terms.content_type = 'post'" in sql
    assert " OR " in sql
    assert 'HAVING count(distinct(terms."group")) = 2' in sql

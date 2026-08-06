"""G4 red tests for taxonomy DTOs and the uniform list-query contract."""

from __future__ import annotations

from importlib import import_module
from uuid import uuid4

import pytest


def _schemas_module():
    try:
        return import_module("inc.kernel.taxonomy.schemas")
    except ModuleNotFoundError as exc:  # pragma: no cover - G4 red assertion
        pytest.fail("G4 target missing: inc.kernel.taxonomy.schemas")
        raise AssertionError from exc


def test_term_dtos_keep_type_name_in_url_and_support_metadata_fields() -> None:
    schemas = _schemas_module()
    create = schemas.TermCreate(group="category", slug="news", name="News")
    read = schemas.TermRead(
        id=uuid4(),
        content_type="post",
        group="category",
        slug="news",
        name="News",
        data={},
    )

    assert create.group == "category"
    assert read.content_type == "post"
    assert "type_name" not in schemas.TermCreate.model_fields


def test_term_list_query_supports_q_group_slug_sort_and_order() -> None:
    schemas = _schemas_module()
    query = schemas.TermListQuery(
        q="news",
        group="category",
        slug="news",
        sort="name",
        order="desc",
    )

    assert query.page == 1
    assert query.size == 20
    assert query.q == "news"
    assert query.order == "desc"

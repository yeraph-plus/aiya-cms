"""G3 red tests for dynamic Content DTOs and query parameters."""

from __future__ import annotations

from importlib import import_module
from uuid import uuid4

import pytest


def _schemas_module():
    try:
        return import_module("inc.kernel.content.schemas")
    except ModuleNotFoundError as exc:  # pragma: no cover - G3 red assertion
        pytest.fail("G3 target missing: inc.kernel.content.schemas")
        raise AssertionError from exc


def test_content_dtos_use_string_status_and_expose_new_fixed_fields() -> None:
    schemas = _schemas_module()
    create = schemas.ContentCreate(
        title="Title",
        slug="title",
        excerpt="SEO",
        data={"featured": True},
    )
    update = schemas.ContentUpdate(excerpt="Updated SEO", comment_count=4)
    read = schemas.ContentRead(
        id=uuid4(),
        type="post",
        title="Title",
        slug="title",
        status="published",
        owner_id=uuid4(),
        content="body",
        excerpt="SEO",
        view_count=0,
        like_count=0,
        rating_sum=0,
        rating_count=0,
        comment_count=4,
        data={"featured": "true"},
        published_at=None,
        trashed_at=None,
    )

    assert create.excerpt == "SEO"
    assert update.comment_count == 4
    assert read.status == "published"
    assert read.comment_count == 4


def test_content_query_supports_excerpt_and_comment_count_sort() -> None:
    schemas = _schemas_module()
    query = schemas.ContentListQuery(
        q="seo",
        status="published",
        sort="comment_count",
        order="asc",
    )

    assert query.status == "published"
    assert query.sort == "comment_count"
    assert query.order == "asc"

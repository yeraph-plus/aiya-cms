"""G5 red tests for comment DTO and query contracts."""

from __future__ import annotations

from importlib import import_module
from uuid import uuid4

import pytest


def _schemas_module():
    try:
        return import_module("inc.kernel.comment.schemas")
    except ModuleNotFoundError as exc:  # pragma: no cover - G5 red assertion
        pytest.fail("G5 target missing: inc.kernel.comment.schemas")
        raise AssertionError from exc


def test_comment_dtos_support_target_and_jsonb_metadata() -> None:
    schemas = _schemas_module()
    create = schemas.CommentCreate(target_type="post", target_id=uuid4(), content="hello")
    assert create.data == {}
    query = schemas.CommentModerationQuery(q="hello", status="approved", sort="depth")
    assert query.page == 1
    assert query.size == 20
    assert query.q == "hello"


def test_thread_query_has_uniform_pagination_keyword_and_sort_contract() -> None:
    schemas = _schemas_module()
    query = schemas.CommentThreadQuery(q="hello", page=2, size=10, sort="updated_at", order="desc")
    assert query.page == 2
    assert query.size == 10
    assert query.sort == "updated_at"
    assert query.order == "desc"

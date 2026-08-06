"""G5 red tests for kernel Comment ORM and JSONB boundaries."""

from __future__ import annotations

from importlib import import_module
from uuid import uuid4

import pytest


def _models_module():
    try:
        return import_module("inc.kernel.comment.models")
    except ModuleNotFoundError as exc:  # pragma: no cover - G5 red assertion
        pytest.fail("G5 target missing: inc.kernel.comment.models")
        raise AssertionError from exc


def test_comment_kernel_model_has_thread_target_and_jsonb_fields() -> None:
    models = _models_module()
    columns = models.Comment.__table__.columns

    assert {
        "target_type",
        "target_id",
        "parent_id",
        "root_id",
        "depth",
        "owner_id",
        "status",
        "content",
        "data",
        "updated_at",
    } <= set(columns.keys())

    item = models.Comment(
        id=uuid4(),
        target_type="post",
        target_id=uuid4(),
        owner_id=uuid4(),
        status="pending",
        content="hello",
        data=models.CommentExtra.model_validate({"flags": ["review"]}),
    )
    assert item.depth in (None, 0)
    assert item.data.model_dump(mode="json")["flags"] == ["review"]

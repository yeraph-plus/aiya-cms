"""G3 red tests for the kernel Content ORM and fixed columns."""

from __future__ import annotations

from importlib import import_module
from uuid import uuid4

import pytest


def _models_module():
    try:
        return import_module("inc.kernel.content.models")
    except ModuleNotFoundError as exc:  # pragma: no cover - G3 red assertion
        pytest.fail("G3 target missing: inc.kernel.content.models")
        raise AssertionError from exc


def _schemas_module():
    try:
        return import_module("inc.kernel.content.schemas")
    except ModuleNotFoundError as exc:  # pragma: no cover - G3 red assertion
        pytest.fail("G3 target missing: inc.kernel.content.schemas")
        raise AssertionError from exc


def test_content_kernel_model_has_fixed_seo_count_and_trash_columns() -> None:
    models = _models_module()
    schemas = _schemas_module()
    columns = models.Content.__table__.columns

    assert {"excerpt", "comment_count", "trashed_at", "updated_at"} <= set(columns.keys())
    assert columns["comment_count"].nullable is False
    assert columns["excerpt"].nullable is False
    assert columns["trashed_at"].nullable is True

    item = models.Content(
        id=uuid4(),
        type="post",
        title="A title",
        slug="a-title",
        status="published",
        owner_id=uuid4(),
        content="body",
        excerpt="SEO excerpt",
        comment_count=2,
        data=schemas.ContentDataValues.model_validate({"featured": "true"}),
    )

    assert isinstance(item.status, str)
    assert item.excerpt == "SEO excerpt"
    assert item.comment_count == 2
    assert item.data.root == {"featured": "true"}

"""G4 red tests for kernel Term and relationship ORM models."""

from __future__ import annotations

from importlib import import_module
from uuid import uuid4

import pytest


def _models_module():
    try:
        return import_module("inc.kernel.taxonomy.models")
    except ModuleNotFoundError as exc:  # pragma: no cover - G4 red assertion
        pytest.fail("G4 target missing: inc.kernel.taxonomy.models")
        raise AssertionError from exc


def test_term_kernel_model_has_type_group_slug_scope_and_jsonb_data() -> None:
    models = _models_module()
    columns = models.Term.__table__.columns

    assert {"content_type", "group", "slug", "name", "data", "updated_at"} <= set(columns.keys())
    assert {"content_id", "term_id"} <= set(models.TermRelationship.__table__.columns.keys())

    term = models.Term(
        id=uuid4(),
        content_type="post",
        group="category",
        slug="news",
        name="News",
        data=models.TermData.model_validate({"description": "A category"}),
    )

    assert term.content_type == "post"
    assert term.group == "category"
    assert term.data.model_dump(mode="json")["description"] == "A category"

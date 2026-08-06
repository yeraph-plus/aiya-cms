"""G1 red tests for ContentDataValues normalization and validation."""

from __future__ import annotations

from importlib import import_module

import pytest


def _schemas_module():
    try:
        return import_module("inc.kernel.content.schemas")
    except ModuleNotFoundError as exc:  # pragma: no cover - G1 red assertion
        pytest.fail("G2 target missing: inc.kernel.content.schemas must expose ContentDataValues")
        raise AssertionError from exc


def _definitions_module():
    try:
        return import_module("inc.kernel.content.definitions")
    except ModuleNotFoundError as exc:  # pragma: no cover - G1 red assertion
        pytest.fail(
            "G2 target missing: content declarations must be available for data interpretation"
        )
        raise AssertionError from exc


def _interpreter_module():
    try:
        return import_module("inc.kernel.content.interpreter")
    except ModuleNotFoundError as exc:  # pragma: no cover - G1 red assertion
        pytest.fail("G2 target missing: ContentTypeInterpreter must normalize declared data values")
        raise AssertionError from exc


def _declaration():
    definitions = _definitions_module()

    class DataType(definitions.ContentType):
        type_name = "data-demo"
        statuses = (definitions.ContentStatusDef(slug="draft", is_public=False),)
        default_status = "draft"
        fields = (
            definitions.ContentField(
                slug="title",
                title="Title",
                description="",
                input_type="text",
                required=True,
            ),
            definitions.ContentField(
                slug="featured",
                title="Featured",
                description="",
                input_type="bool",
            ),
            definitions.ContentField(
                slug="priority",
                title="Priority",
                description="",
                input_type="number",
            ),
            definitions.ContentField(
                slug="website",
                title="Website",
                description="",
                input_type="url",
            ),
        )

    return DataType


def test_data_values_are_normalized_to_strings() -> None:
    interpreter = _interpreter_module().ContentTypeInterpreter()
    compiled = interpreter.compile(_declaration())

    values = interpreter.validate_data(
        compiled,
        {
            "title": " Hello ",
            "featured": True,
            "priority": 12,
            "website": "https://example.test",
        },
    )

    assert values.root == {
        "title": " Hello ",
        "featured": "true",
        "priority": "12",
        "website": "https://example.test",
    }
    assert all(isinstance(value, str) for value in values.root.values())
    assert isinstance(values, _schemas_module().ContentDataValues)

    with pytest.raises(ValueError, match="strings"):
        _schemas_module().ContentDataValues.model_validate({"title": 1})


def test_unknown_data_key_and_missing_required_field_are_rejected() -> None:
    interpreter = _interpreter_module().ContentTypeInterpreter()
    compiled = interpreter.compile(_declaration())

    with pytest.raises((TypeError, ValueError), match="unknown|declared"):
        interpreter.validate_data(compiled, {"title": "ok", "unknown": "x"})

    with pytest.raises((TypeError, ValueError), match="required|title"):
        interpreter.validate_data(compiled, {"featured": False})

    with pytest.raises((TypeError, ValueError), match="url|URL"):
        interpreter.validate_data(compiled, {"title": "ok", "website": "not-a-url"})

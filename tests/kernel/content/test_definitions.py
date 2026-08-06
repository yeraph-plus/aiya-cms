"""G1 red tests for the declarative ContentType contract.

The kernel declaration layer is intentionally not implemented yet.  These
tests describe the public shape that G2 must provide.
"""

from __future__ import annotations

from importlib import import_module

import pytest


def _definitions_module():
    try:
        return import_module("inc.kernel.content.definitions")
    except ModuleNotFoundError as exc:  # pragma: no cover - G1 red assertion
        pytest.fail(
            "G2 target missing: inc.kernel.content.definitions must expose the "
            "declarative content definitions"
        )
        raise AssertionError from exc


def _interpreter_module():
    try:
        return import_module("inc.kernel.content.interpreter")
    except ModuleNotFoundError as exc:  # pragma: no cover - G1 red assertion
        pytest.fail(
            "G2 target missing: inc.kernel.content.interpreter must compile "
            "ContentType declarations"
        )
        raise AssertionError from exc


def _demo_declaration():
    definitions = _definitions_module()

    class DemoContentType(definitions.ContentType):
        type_name = "demo"
        statuses = (
            definitions.ContentStatusDef(slug="draft", is_public=False),
            definitions.ContentStatusDef(slug="published", is_public=True),
        )
        default_status = "draft"
        transitions = (
            definitions.ContentTransitionDef(
                action="publish",
                from_statuses=("draft",),
                to_status="published",
                capability="content:publish",
            ),
        )
        fields = (
            definitions.ContentField(
                slug="summary",
                title="Summary",
                description="Short summary",
                input_type="text",
                required=True,
            ),
            definitions.ContentField(
                slug="featured",
                title="Featured",
                description="Whether the item is featured",
                input_type="bool",
            ),
        )
        taxonomy_groups = (
            definitions.TaxonomyGroupDef(
                slug="category", title="Category", description="Categories"
            ),
        )
        comment_policy = definitions.CommentPolicy(
            allow=True, max_depth=3, auto_approve=False, rate_limit=10
        )
        trash_policy = definitions.TrashPolicy(retention_days=30)

    return DemoContentType


def test_interpreter_compiles_complete_content_type_to_immutable_definition() -> None:
    interpreter = _interpreter_module().ContentTypeInterpreter()
    compiled = interpreter.compile(_demo_declaration())

    assert compiled.type_name == "demo"
    assert compiled.default_status == "draft"
    assert [status.slug for status in compiled.statuses] == ["draft", "published"]
    assert [field.slug for field in compiled.fields] == ["summary", "featured"]
    assert [group.slug for group in compiled.taxonomy_groups] == ["category"]
    assert compiled.comment_policy.max_depth == 3

    with pytest.raises((AttributeError, TypeError)):
        compiled.type_name = "changed"


def test_declaration_rejects_missing_required_values_and_invalid_transition() -> None:
    definitions = _definitions_module()
    interpreter = _interpreter_module().ContentTypeInterpreter()

    class MissingTypeName(definitions.ContentType):
        statuses = (definitions.ContentStatusDef(slug="draft", is_public=False),)
        default_status = "draft"
        fields = ()

    with pytest.raises((TypeError, ValueError), match="type_name"):
        interpreter.compile(MissingTypeName)

    class UnknownTransitionStatus(definitions.ContentType):
        type_name = "broken-transition"
        statuses = (definitions.ContentStatusDef(slug="draft", is_public=False),)
        default_status = "draft"
        transitions = (
            definitions.ContentTransitionDef(
                action="publish",
                from_statuses=("missing",),
                to_status="published",
                capability="content:publish",
            ),
        )
        fields = ()

    with pytest.raises((TypeError, ValueError), match="status"):
        interpreter.compile(UnknownTransitionStatus)

    class InvalidTypeName(definitions.ContentType):
        type_name = "Bad Type"
        statuses = (definitions.ContentStatusDef(slug="draft", is_public=False),)
        default_status = "draft"
        fields = ()

    with pytest.raises((TypeError, ValueError), match="type_name"):
        interpreter.compile(InvalidTypeName)

    class UnknownDefaultStatus(definitions.ContentType):
        type_name = "unknown-default"
        statuses = (definitions.ContentStatusDef(slug="draft", is_public=False),)
        default_status = "published"
        fields = ()

    with pytest.raises((TypeError, ValueError), match="default|status"):
        interpreter.compile(UnknownDefaultStatus)


def test_duplicate_declaration_slugs_and_non_callable_validator_fail_fast() -> None:
    definitions = _definitions_module()
    interpreter = _interpreter_module().ContentTypeInterpreter()

    class DuplicateSlugs(definitions.ContentType):
        type_name = "duplicate-slugs"
        statuses = (
            definitions.ContentStatusDef(slug="draft", is_public=False),
            definitions.ContentStatusDef(slug="draft", is_public=True),
        )
        default_status = "draft"
        fields = (
            definitions.ContentField(
                slug="same",
                title="Same",
                description="",
                input_type="text",
            ),
            definitions.ContentField(
                slug="same",
                title="Same again",
                description="",
                input_type="text",
            ),
        )
        taxonomy_groups = (
            definitions.TaxonomyGroupDef(slug="category", title="Category"),
            definitions.TaxonomyGroupDef(slug="category", title="Category again"),
        )

    with pytest.raises((TypeError, ValueError), match="duplicate|unique"):
        interpreter.compile(DuplicateSlugs)

    class DuplicateActions(definitions.ContentType):
        type_name = "duplicate-actions"
        statuses = (definitions.ContentStatusDef(slug="draft", is_public=False),)
        default_status = "draft"
        transitions = (
            definitions.ContentTransitionDef(
                action="publish",
                from_statuses=("draft",),
                to_status="draft",
                capability="content:publish",
            ),
            definitions.ContentTransitionDef(
                action="publish",
                from_statuses=("draft",),
                to_status="draft",
                capability="content:publish",
            ),
        )
        fields = ()

    with pytest.raises((TypeError, ValueError), match="duplicate|unique|action"):
        interpreter.compile(DuplicateActions)

    class InvalidValidator(definitions.ContentType):
        type_name = "invalid-validator"
        statuses = (definitions.ContentStatusDef(slug="draft", is_public=False),)
        default_status = "draft"
        fields = (
            definitions.ContentField(
                slug="summary",
                title="Summary",
                description="",
                input_type="text",
                validator="not-callable",
            ),
        )

    with pytest.raises((TypeError, ValueError), match="validator|callable"):
        interpreter.compile(InvalidValidator)


def test_metadata_projection_does_not_expose_validator_callback() -> None:
    definitions = _definitions_module()
    interpreter = _interpreter_module().ContentTypeInterpreter()

    def validate_summary(value: str) -> str:
        return value.strip()

    class MetadataType(definitions.ContentType):
        type_name = "metadata"
        statuses = (definitions.ContentStatusDef(slug="draft", is_public=False),)
        default_status = "draft"
        fields = (
            definitions.ContentField(
                slug="summary",
                title="Summary",
                description="Short summary",
                input_type="text",
                required=True,
                validator=validate_summary,
            ),
        )

    compiled = interpreter.compile(MetadataType)
    metadata = compiled.metadata()
    field = metadata["fields"][0]

    assert field["slug"] == "summary"
    assert field["input_type"] == "text"
    assert field["required"] is True
    assert "validator" not in field

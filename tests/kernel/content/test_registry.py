"""G1 red tests for explicit ContentType registration and freezing."""

from __future__ import annotations

from importlib import import_module

import pytest


def _registry_module():
    try:
        return import_module("inc.kernel.content.registry")
    except ModuleNotFoundError as exc:  # pragma: no cover - G1 red assertion
        pytest.fail(
            "G2 target missing: inc.kernel.content.registry must provide an "
            "explicit frozen registry"
        )
        raise AssertionError from exc


def _definitions_module():
    try:
        return import_module("inc.kernel.content.definitions")
    except ModuleNotFoundError as exc:  # pragma: no cover - G1 red assertion
        pytest.fail("G2 target missing: ContentType declarations are not available")
        raise AssertionError from exc


def _declaration(type_name: str):
    definitions = _definitions_module()

    class DemoContentType(definitions.ContentType):
        pass

    DemoContentType.type_name = type_name
    DemoContentType.statuses = (definitions.ContentStatusDef(slug="draft", is_public=False),)
    DemoContentType.default_status = "draft"
    DemoContentType.fields = ()
    return DemoContentType


def test_registry_requires_explicit_registration_and_freezes_once() -> None:
    registry = _registry_module().ContentTypeRegistry()
    first = _declaration("first")
    second = _declaration("second")

    registry.register(first)
    assert registry.keys() == ("first",)
    assert registry.require("first").type_name == "first"

    with pytest.raises((TypeError, ValueError), match="duplicate|registered"):
        registry.register(first)

    registry.freeze()
    assert registry.is_frozen is True
    with pytest.raises((RuntimeError, TypeError), match="frozen"):
        registry.register(second)


def test_registry_rejects_unknown_type_and_mutation_after_freeze() -> None:
    registry = _registry_module().ContentTypeRegistry()
    registry.register(_declaration("only"))
    registry.freeze()

    with pytest.raises((KeyError, LookupError, ValueError), match="only|unknown|type"):
        registry.require("missing")

    compiled = registry.require("only")
    with pytest.raises((AttributeError, TypeError)):
        compiled.type_name = "changed"

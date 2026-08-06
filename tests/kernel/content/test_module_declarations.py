"""G6 red tests for the three explicit content declarations."""

from __future__ import annotations

from importlib import import_module

import pytest

from inc.kernel.content import ContentTypeRegistry


def _definition(type_name: str):
    try:
        return import_module(f"inc.modules.{type_name}.definition")
    except ModuleNotFoundError as exc:  # pragma: no cover - G6 red assertion
        pytest.fail(f"G6 target missing: inc.modules.{type_name}.definition")
        raise AssertionError from exc


def test_post_forum_issue_compile_as_explicit_kernel_declarations() -> None:
    declarations = [
        _definition("post").PostContentType,
        _definition("forum").ForumContentType,
        _definition("issue").IssueContentType,
    ]
    registry = ContentTypeRegistry(declarations)

    assert registry.keys() == ("post", "forum", "issue")
    post = registry.require("post")
    assert [group.slug for group in post.taxonomy_groups] == ["category", "tag"]
    assert post.comment_policy.max_depth == 3
    assert registry.require("forum").comment_policy.max_depth == 5
    assert registry.require("issue").comment_policy.auto_approve is False


def test_declarations_are_isolated_and_have_no_module_service_or_model() -> None:
    for type_name in ("post", "forum", "issue"):
        module = _definition(type_name)
        assert hasattr(module, f"{type_name.title()}ContentType")
        package = module.__package__
        assert package is not None
        assert all(
            not getattr(module, name, None).__class__.__module__.startswith("inc.modules.")
            for name in module.__dict__
            if name.endswith("Service") or name.endswith("Repository")
        )

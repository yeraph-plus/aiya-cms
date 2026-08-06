"""Boot registry contract tests (boot.md §2/§3)."""

from __future__ import annotations

import pytest

from inc.kernel.boot import Registry
from inc.kernel.errors import KernelError


def test_register_and_lookup() -> None:
    registry: Registry[str] = Registry("workflow")
    registry.register("post.submit.v1", "handler", owner="feature:post")
    assert registry.lookup("post.submit.v1") == "handler"


def test_duplicate_key_fails_even_with_same_value() -> None:
    registry: Registry[str] = Registry("workflow")
    registry.register("a.b.c", "x", owner="tests")
    with pytest.raises(KernelError) as excinfo:
        registry.register("a.b.c", "x", owner="tests")
    assert excinfo.value.code == "kernel.registry_duplicate"


def test_unknown_lookup_raises_stable_error() -> None:
    registry: Registry[str] = Registry("workflow")
    with pytest.raises(KernelError) as excinfo:
        registry.lookup("missing.key.v1")
    assert excinfo.value.code == "kernel.registry_unknown"


def test_freeze_blocks_mutation() -> None:
    registry: Registry[str] = Registry("workflow")
    registry.register("a.b.c", "x", owner="tests")
    registry.freeze()
    with pytest.raises(KernelError) as excinfo:
        registry.register("a.b.d", "y", owner="tests")
    assert excinfo.value.code == "kernel.registry_frozen"
    assert registry.lookup("a.b.c") == "x"  # reads still work after freeze


def test_validate_reports_missing_dependencies() -> None:
    registry: Registry[str] = Registry("workflow")
    registry.register("a.b.c", "x", owner="tests", dependencies=("a.b.d",))
    problems = registry.validate()
    assert problems == ["a.b.c depends on unregistered a.b.d"]

    registry.register("a.b.d", "y", owner="tests")
    assert registry.validate() == []


def test_report_is_sorted_and_secret_free() -> None:
    registry: Registry[str] = Registry("workflow")
    registry.register("b.key.v1", "b", owner="kernel:events", version="2")
    registry.register(
        "a.key.v1", "a", owner="kernel:events", version="1", dependencies=("b.key.v1",)
    )
    report = registry.report()
    assert report == (
        "workflow a.key.v1 owner=kernel:events version=1 deps=b.key.v1",
        "workflow b.key.v1 owner=kernel:events version=2",
    )
    assert "kernel:events" in report[0]


def test_empty_registry_reports_and_validates_cleanly() -> None:
    registry: Registry[str] = Registry("workflow")
    assert registry.report() == ()
    assert registry.validate() == []
    assert len(registry) == 0


def test_keys_are_sorted() -> None:
    registry: Registry[str] = Registry("workflow")
    registry.register("b.key.v1", "b", owner="tests")
    registry.register("a.key.v1", "a", owner="tests")
    assert registry.keys() == ("a.key.v1", "b.key.v1")

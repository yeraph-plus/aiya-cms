"""Guards: capability/feature declarations are pure, immutable and uniquely keyed.

Contract source: context/spec/composition.md §2 and §3, context/spec/features.md §6.

Each capability and feature ships a ``definition.py`` exporting a single
``spec`` object. The declaration must be immutable, carry a stable key that
matches its package name, and feature requirements must only reference
capabilities that exist.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from inc.kernel.boot import CapabilitySpec, FeatureSpec

INITIAL_CAPABILITIES = (
    "identity",
    "access",
    "oidc_provider",
    "audit",
    "settings",
    "content",
    "comments",
    "community",
    "notification",
    "taxonomy",
    "assets",
    "points",
    "payments",
    "membership",
    "engagement",
)

INITIAL_FEATURES = (
    "auth",
    "post",
    "page",
    "site_settings",
    "check_in",
    "membership_grants",
    "site_cleanup",
    "content_engagement",
    "content_bucket",
)


def _load_definitions(package: str, names: tuple[str, ...]) -> list[tuple[str, Any]]:
    loaded: list[tuple[str, Any]] = []
    for name in names:
        module = importlib.import_module(f"inc.{package}.{name}.definition")
        loaded.append((name, getattr(module, "spec", None)))
    return loaded


def test_capability_definitions_are_immutable_and_keyed() -> None:
    for name, spec in _load_definitions("capabilities", INITIAL_CAPABILITIES):
        assert isinstance(spec, CapabilitySpec), f"{name}: missing CapabilitySpec"
        assert spec.name == name, f"{name}: key does not match package name"
        assert spec.schema_version, f"{name}: schema_version must not be empty"


def test_feature_definitions_are_immutable_and_keyed() -> None:
    for name, spec in _load_definitions("features", INITIAL_FEATURES):
        assert isinstance(spec, FeatureSpec), f"{name}: missing FeatureSpec"
        assert spec.name == name, f"{name}: key does not match package name"
        assert spec.version, f"{name}: version must not be empty"
        unknown = [
            capability for capability in spec.requires if capability not in INITIAL_CAPABILITIES
        ]
        assert unknown == [], f"{name}: requires unknown capabilities {unknown}"


def test_capability_and_feature_keys_are_disjoint() -> None:
    assert set(INITIAL_CAPABILITIES).isdisjoint(INITIAL_FEATURES)


def test_declarations_are_frozen() -> None:
    for _, spec in _load_definitions("capabilities", INITIAL_CAPABILITIES):
        with pytest.raises(AttributeError):
            spec.name = "mutated"  # type: ignore[misc]
    for _, spec in _load_definitions("features", INITIAL_FEATURES):
        with pytest.raises(AttributeError):
            spec.name = "mutated"  # type: ignore[misc]

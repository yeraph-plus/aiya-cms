"""Boot declarations and registry primitives.

Contract source: context/spec/kernel/boot.md.

This module provides the immutable declaration types used by capability,
feature and application manifests. It holds no registries and performs no
validation; registries, validate/freeze and the boot sequence land in R3,
which also extends these declarations with the registration metadata that
real usage demands (no speculative fields).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    """Pure-data declaration of a business capability."""

    name: str
    schema_version: str


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """Pure-data declaration of a vertical feature."""

    name: str
    version: str
    requires: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AppManifest:
    """Static selection of capabilities, features and runtime services."""

    name: str
    capabilities: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    adapters: tuple[tuple[str, str], ...] = ()
    routers: tuple[str, ...] = ()
    workers: tuple[str, ...] = ()
    cron_enabled: bool = False

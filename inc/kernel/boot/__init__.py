"""Boot declarations and registry primitives.

Contract source: context/spec/kernel/boot.md.

This package provides immutable declaration types (CapabilitySpec,
FeatureSpec, AppManifest) and the typed build registry with
validate/freeze/report semantics. Registries are container-local; importing
this package mutates nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from inc.kernel.boot.registry import Registry, RegistryEntry

__all__ = [
    "AppManifest",
    "CapabilitySpec",
    "FeatureSpec",
    "Registry",
    "RegistryEntry",
    "RouterSpec",
]


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    """Pure-data declaration of a business capability."""

    name: str
    schema_version: str
    access_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """Pure-data declaration of a vertical feature."""

    name: str
    version: str
    requires: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RouterSpec:
    """Declaration of an HTTP router surface.

    Contract source: context/spec/composition.md §7, http-openapi.md §11.
    Capabilities and features export RouterSpec declarations; only the
    composition root mounts them with unified middleware and auth.
    """

    owner: str
    prefix: str
    name: str
    requires_capabilities: tuple[str, ...] = ()
    access_keys: tuple[str, ...] = ()


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

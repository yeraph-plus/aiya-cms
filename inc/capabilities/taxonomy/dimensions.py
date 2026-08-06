"""Taxonomy capability: flat multi-dimensional labels.

Contract source: context/spec/capabilities/taxonomy.md.

A category is a dimension configuration, not a model: no parent-child
trees, no recursive queries, no cross-capability foreign keys. Assignments
reference targets by opaque id; the TargetExists Port validates existence
without importing the target capability.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict

from inc.kernel.errors import ErrorCategory, KernelError

_KEY = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
_TERM_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

SELECTION_MODES = ("single", "multiple")


class TermMetadata(BaseModel):
    """Per-term metadata schema; arbitrary extra keys allowed."""

    model_config = ConfigDict(extra="allow")


class DimensionSpec:
    """Immutable declaration of a taxonomy dimension (registered by a feature)."""

    __slots__ = (
        "dimension_key",
        "version",
        "display_name",
        "target_types",
        "selection_mode",
        "min_items",
        "max_items",
        "term_schema",
        "term_slug_pattern",
        "manage_permission",
        "public_visible",
    )

    def __init__(
        self,
        *,
        dimension_key: str,
        version: str,
        display_name: str,
        target_types: tuple[str, ...],
        selection_mode: str = "multiple",
        min_items: int = 0,
        max_items: int | None = None,
        term_schema: type[BaseModel] = TermMetadata,
        term_slug_pattern: str = r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        manage_permission: str | None = None,
        public_visible: bool = True,
    ) -> None:
        if not _KEY.match(dimension_key):
            raise ValueError(f"invalid dimension_key {dimension_key!r}")
        if not version:
            raise ValueError(f"dimension {dimension_key} requires a version")
        if not target_types:
            raise ValueError(f"dimension {dimension_key} requires target types")
        if selection_mode not in SELECTION_MODES:
            raise ValueError(
                f"dimension {dimension_key} has invalid selection_mode {selection_mode!r}"
            )
        if min_items < 0 or (max_items is not None and (max_items < 1 or max_items < min_items)):
            raise ValueError(f"dimension {dimension_key} has invalid min/max items")
        if not isinstance(term_schema, type) or not issubclass(term_schema, BaseModel):
            raise ValueError(f"dimension {dimension_key} requires a Pydantic term schema")
        re.compile(term_slug_pattern)
        if manage_permission is not None and not re.match(
            r"^[a-z0-9]+(\.[a-z0-9_]+)+$", manage_permission
        ):
            raise ValueError(f"dimension {dimension_key} declares invalid permission key")
        if max_items is not None and selection_mode == "single" and max_items > 1:
            raise ValueError(
                f"dimension {dimension_key}: single mode cannot allow more than one item"
            )

        self.dimension_key = dimension_key
        self.version = version
        self.display_name = display_name
        self.target_types = target_types
        self.selection_mode = selection_mode
        self.min_items = min_items
        self.max_items = (
            max_items if max_items is not None else (1 if selection_mode == "single" else 50)
        )
        self.term_schema = term_schema
        self.term_slug_pattern = term_slug_pattern
        self.manage_permission = manage_permission
        self.public_visible = public_visible

    def accepts_target(self, target_type: str) -> bool:
        return target_type in self.target_types


class DimensionRegistry:
    """dimension_key -> DimensionSpec; frozen after boot."""

    def __init__(self, *, permission_keys: Any = None) -> None:
        self._dimensions: dict[str, DimensionSpec] = {}
        self._frozen = False
        self._permission_keys = permission_keys

    def register(self, spec: DimensionSpec) -> None:
        if self._frozen:
            raise KernelError(
                code="kernel.registry_frozen",
                category=ErrorCategory.INTERNAL,
                message=f"dimension registry is frozen; cannot register {spec.dimension_key}",
            )
        if spec.dimension_key in self._dimensions:
            raise KernelError(
                code="taxonomy.duplicate_dimension",
                category=ErrorCategory.INTERNAL,
                message=f"duplicate dimension {spec.dimension_key}",
            )
        if self._permission_keys is not None and spec.manage_permission is not None:
            self._permission_keys.require(spec.manage_permission)
        self._dimensions[spec.dimension_key] = spec

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def require(self, dimension_key: str) -> DimensionSpec:
        spec = self._dimensions.get(dimension_key)
        if spec is None:
            raise KernelError(
                code="taxonomy.unknown_dimension",
                category=ErrorCategory.INTERNAL,
                message=f"dimension {dimension_key!r} is not registered",
            )
        return spec

    def specs(self) -> tuple[DimensionSpec, ...]:
        return tuple(self._dimensions.values())

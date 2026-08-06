"""Setting group declarations and registry.

Contract source: context/spec/capabilities/settings.md §2.

SettingGroupSpec declares a structured configuration group; the registry
fails fast on unknown groups/fields, duplicate keys or non-serializable
defaults. Registration only declares the schema, never writes rows.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from inc.kernel.errors import ErrorCategory, KernelError

_KEY = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


class SettingGroupSpec:
    """Immutable declaration of a settings group."""

    __slots__ = (
        "group_key",
        "version",
        "value_schema",
        "public_fields",
        "sensitive_fields",
        "update_permission",
        "cache_policy",
        "emit_events",
    )

    def __init__(
        self,
        *,
        group_key: str,
        version: str,
        value_schema: type[BaseModel],
        public_fields: tuple[str, ...] = (),
        sensitive_fields: tuple[str, ...] = (),
        update_permission: str,
        cache_policy: str = "none",
        emit_events: bool = True,
    ) -> None:
        if not _KEY.match(group_key):
            raise ValueError(f"invalid group_key {group_key!r}")
        if not version:
            raise ValueError(f"group {group_key} requires a version")
        if not isinstance(value_schema, type) or not issubclass(value_schema, BaseModel):
            raise ValueError(f"group {group_key} requires a Pydantic value schema")
        if not re.match(r"^[a-z0-9]+(\.[a-z0-9_]+)+$", update_permission):
            raise ValueError(f"group {group_key} declares invalid update permission key")
        unknown_public = set(public_fields) - set(value_schema.model_fields)
        unknown_sensitive = set(sensitive_fields) - set(value_schema.model_fields)
        if unknown_public:
            raise ValueError(
                f"group {group_key} declares public fields not in schema: {sorted(unknown_public)}"
            )
        if unknown_sensitive:
            raise ValueError(
                f"group {group_key} declares sensitive fields not in schema: "
                f"{sorted(unknown_sensitive)}"
            )
        if set(public_fields) & set(sensitive_fields):
            raise ValueError(f"group {group_key} marks a field both public and sensitive")
        defaults = value_schema.model_construct()
        try:
            value_schema.model_validate(defaults.model_dump(mode="json"))
        except Exception as exc:
            raise ValueError(
                f"group {group_key} defaults are not JSON-serializable: {exc}"
            ) from exc

        self.group_key = group_key
        self.version = version
        self.value_schema = value_schema
        self.public_fields = public_fields
        self.sensitive_fields = sensitive_fields
        self.update_permission = update_permission
        self.cache_policy = cache_policy
        self.emit_events = emit_events

    def defaults(self) -> dict[str, Any]:
        return self.value_schema.model_construct().model_dump(mode="json")


class SettingGroupRegistry:
    """group_key -> SettingGroupSpec; frozen after boot."""

    def __init__(self) -> None:
        self._groups: dict[str, SettingGroupSpec] = {}
        self._frozen = False

    def register(self, spec: SettingGroupSpec) -> None:
        if self._frozen:
            raise KernelError(
                code="kernel.registry_frozen",
                category=ErrorCategory.INTERNAL,
                message=f"settings registry is frozen; cannot register {spec.group_key}",
            )
        if spec.group_key in self._groups:
            raise KernelError(
                code="settings.duplicate_group",
                category=ErrorCategory.INTERNAL,
                message=f"duplicate settings group {spec.group_key}",
            )
        self._groups[spec.group_key] = spec

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def require(self, group_key: str) -> SettingGroupSpec:
        spec = self._groups.get(group_key)
        if spec is None:
            raise KernelError(
                code="settings.unknown_group",
                category=ErrorCategory.INTERNAL,
                message=f"settings group {group_key!r} is not registered",
            )
        return spec

    def specs(self) -> tuple[SettingGroupSpec, ...]:
        return tuple(self._groups.values())

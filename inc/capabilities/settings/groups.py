"""Registered settings groups and their field descriptors.

Contract source: context/spec/capabilities/settings.md §2.

Groups and fields are code-owned declarations.  The registry validates the
descriptor contract at boot; it never creates or initializes database rows.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from inc.kernel.errors import ErrorCategory, KernelError

_KEY = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
SettingFieldType = Literal["bool", "text", "textarea", "select", "radio", "mult", "upload"]
_JSON_SCALAR = str | int | float | bool | None


class SettingOption(BaseModel):
    """One stable machine value exposed to an admin form."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: _JSON_SCALAR


class SettingFieldMetadata(BaseModel):
    """Validated structural metadata; display text belongs to the client."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    options: tuple[SettingOption, ...] = ()
    rows: int | None = Field(default=None, ge=1, le=100)
    accept: tuple[str, ...] = ()
    max_length: int | None = Field(default=None, gt=0)
    max_size: int | None = Field(default=None, gt=0)
    multiple: bool = False


class SettingFieldSpec(BaseModel):
    """Code-owned descriptor for one persisted setting field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slug: str
    type: SettingFieldType
    type_sub: str | None = None
    default: Any
    metadata: SettingFieldMetadata = Field(default_factory=SettingFieldMetadata)
    public: bool = False
    sensitive: bool = False

    @model_validator(mode="after")
    def _validate_descriptor(self) -> SettingFieldSpec:
        if not _KEY.match(self.slug):
            raise ValueError(f"invalid setting field slug {self.slug!r}")
        if self.public and self.sensitive:
            raise ValueError(f"setting field {self.slug} cannot be public and sensitive")
        if self.type in {"select", "radio"} and not self.metadata.options:
            raise ValueError(f"setting field {self.slug} requires options")
        if self.type not in {"select", "radio"} and self.metadata.options:
            raise ValueError(f"setting field {self.slug} options require select or radio type")
        if self.type == "mult" and not self.type_sub:
            raise ValueError(f"setting field {self.slug} requires type_sub")
        if self.type == "upload" and self.type_sub not in {"single", "multiple"}:
            raise ValueError(
                f"setting field {self.slug} upload type_sub must be single or multiple"
            )
        if self.type == "upload" and self.type_sub == "multiple" and not self.metadata.multiple:
            raise ValueError(
                f"setting field {self.slug} multiple upload requires metadata.multiple"
            )
        return self


def _json_normalize(value: Any) -> Any:
    """Normalize Pydantic values to the exact JSON shape persisted in storage."""

    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    return json.loads(json.dumps(value, default=str))


def _validated_defaults(
    value_schema: type[BaseModel], fields: tuple[SettingFieldSpec, ...]
) -> dict[str, Any]:
    values = {field.slug: field.default for field in fields}
    model = value_schema.model_validate(values)
    dumped = model.model_dump()
    return {key: _json_normalize(value) for key, value in dumped.items()}


class SettingGroupSpec:
    """Immutable declaration of a settings group."""

    __slots__ = (
        "group_key",
        "version",
        "value_schema",
        "fields",
        "update_permission",
        "cache_policy",
        "emit_events",
        "_field_map",
    )

    def __init__(
        self,
        *,
        group_key: str,
        version: str,
        value_schema: type[BaseModel],
        fields: tuple[SettingFieldSpec, ...],
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
        if not re.match(r"^[a-z0-9]+(?:\.[a-z0-9_]+)+$", update_permission):
            raise ValueError(f"group {group_key} declares invalid update permission key")
        if not fields:
            raise ValueError(f"group {group_key} requires at least one field")
        if any(not isinstance(field, SettingFieldSpec) for field in fields):
            raise ValueError(f"group {group_key} fields must be SettingFieldSpec instances")
        slugs = tuple(field.slug for field in fields)
        if len(set(slugs)) != len(slugs):
            raise ValueError(f"group {group_key} declares duplicate field slug")
        schema_fields = set(value_schema.model_fields)
        field_slugs = set(slugs)
        if field_slugs != schema_fields:
            raise ValueError(
                f"group {group_key} fields must match value schema: "
                f"missing={sorted(schema_fields - field_slugs)}, "
                f"unknown={sorted(field_slugs - schema_fields)}"
            )
        if any(field.public and field.sensitive for field in fields):
            raise ValueError(f"group {group_key} contains a public sensitive field")
        try:
            defaults = _validated_defaults(value_schema, fields)
        except Exception as exc:
            raise ValueError(f"group {group_key} defaults failed schema validation: {exc}") from exc
        for field in fields:
            if defaults[field.slug] != _json_normalize(field.default):
                raise ValueError(
                    f"group {group_key} default for {field.slug} differs from value schema"
                )

        self.group_key = group_key
        self.version = version
        self.value_schema = value_schema
        self.fields = tuple(fields)
        self.update_permission = update_permission
        self.cache_policy = cache_policy
        self.emit_events = emit_events
        self._field_map = {field.slug: field for field in fields}

    @property
    def public_fields(self) -> tuple[str, ...]:
        return tuple(field.slug for field in self.fields if field.public)

    @property
    def sensitive_fields(self) -> tuple[str, ...]:
        return tuple(field.slug for field in self.fields if field.sensitive)

    def field(self, slug: str) -> SettingFieldSpec:
        field = self._field_map.get(slug)
        if field is None:
            raise KernelError(
                code="settings.unknown_field",
                category=ErrorCategory.VALIDATION,
                message=f"settings group {self.group_key!r} has no field {slug!r}",
            )
        return field

    def defaults(self) -> dict[str, Any]:
        return _validated_defaults(self.value_schema, self.fields)


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

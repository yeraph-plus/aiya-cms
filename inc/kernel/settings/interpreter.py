"""Interpret declarative setting definitions into validated runtime values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from .definitions import SettingGroup
from .models import (
    SettingFieldDefinitionRead,
    SettingGroupRead,
    SettingOverrides,
    SettingPatch,
)
from .registry import SettingDefinition


class SettingInterpreter:
    """Single boundary for defaults, overrides, validators and metadata."""

    def __init__(self, definition: SettingDefinition) -> None:
        self.definition = definition
        self.group: type[SettingGroup] = definition.group
        self.model = self.group.value_model()
        self.fields = definition.fields
        self._fields = {field.slug: field for field in self.fields}

    def resolve(self, overrides: Mapping[str, Any]) -> BaseModel:
        values = self._defaults()
        values.update(dict(overrides))
        return self._validate(values)

    def apply_patch(
        self, overrides: Mapping[str, Any], patch: SettingPatch
    ) -> tuple[BaseModel, SettingOverrides]:
        unknown = (set(patch.values) | set(patch.unset)) - set(self._fields)
        if unknown:
            raise ValueError(f"unknown setting field: {sorted(unknown)[0]}")
        overlap = set(patch.values) & set(patch.unset)
        if overlap:
            raise ValueError(f"setting field cannot be both value and unset: {sorted(overlap)[0]}")
        next_overrides = dict(overrides)
        for slug in patch.unset:
            next_overrides.pop(slug, None)
        values = dict(next_overrides)
        values.update(patch.values)
        resolved = self._validate({**self._defaults(), **values})
        defaults = self._defaults()
        # A value equal to its code default does not need a database override.
        next_overrides = {
            slug: getattr(resolved, slug)
            for slug in self._fields
            if slug not in patch.unset and getattr(resolved, slug) != defaults[slug]
        }
        return resolved, SettingOverrides.model_validate(next_overrides)

    def describe(self, resolved: BaseModel, overrides: Mapping[str, Any]) -> SettingGroupRead:
        schema = self.model.model_json_schema()
        properties = schema.get("properties", {})
        fields = []
        for field in self.fields:
            field_schema = properties.get(field.slug, {})
            fields.append(
                SettingFieldDefinitionRead(
                    slug=field.slug,
                    title=field.title,
                    description=field.description,
                    type=self._type_name(field_schema, field.value_type),
                    is_public=field.is_public,
                    default=field.default,
                    value=getattr(resolved, field.slug),
                    is_overridden=field.slug in overrides,
                    schema=field_schema if isinstance(field_schema, dict) else {},
                )
            )
        return SettingGroupRead(
            slug=self.group.slug,
            title=self.group.group_title or self.group.slug,
            description=self.group.group_description,
            order=self.group.order,
            fields=fields,
        )

    def public_values(self, resolved: BaseModel) -> dict[str, Any]:
        return {
            field.slug: getattr(resolved, field.slug) for field in self.fields if field.is_public
        }

    def _defaults(self) -> dict[str, Any]:
        return {field.slug: field.default for field in self.fields}

    def _validate(self, values: Mapping[str, Any]) -> BaseModel:
        try:
            normalized = self.model.model_validate(dict(values))
            data = normalized.model_dump()
            for field in self.fields:
                if field.validator is not None:
                    data[field.slug] = field.validator(data[field.slug])
            data = self.group.validate_group(data)
            return self.model.model_validate(data)
        except (ValidationError, ValueError, TypeError) as exc:
            raise ValueError(str(exc)) from exc

    @staticmethod
    def _type_name(schema: Mapping[str, Any], value_type: Any) -> str:
        schema_type = schema.get("type")
        if isinstance(schema_type, str):
            return schema_type
        any_of = schema.get("anyOf")
        if isinstance(any_of, list):
            for item in any_of:
                if isinstance(item, dict) and isinstance(item.get("type"), str):
                    return str(item["type"])
        if value_type is bool:
            return "boolean"
        if value_type is int:
            return "integer"
        if value_type is float:
            return "number"
        return "object"

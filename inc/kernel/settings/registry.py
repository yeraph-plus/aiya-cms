"""Explicit registry for declarative runtime-setting groups."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import BaseModel

from .definitions import SettingField, SettingGroup


@dataclass(frozen=True, slots=True)
class SettingDefinition:
    group: type[SettingGroup]

    @property
    def key(self) -> str:
        return self.group.slug

    @property
    def fields(self) -> tuple[SettingField[object], ...]:
        return tuple(self.group.fields())

    @property
    def model(self) -> type[BaseModel]:
        return self.group.value_model()


class SettingRegistry:
    def __init__(self, definitions: Iterable[SettingDefinition] = ()) -> None:
        self._definitions: dict[str, SettingDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: SettingDefinition) -> None:
        key = definition.key
        if not key or len(key) > 128:
            raise ValueError("setting group slug must be 1-128 characters")
        if key in self._definitions:
            raise ValueError(f"duplicate setting group: {key}")
        fields = definition.group.fields()
        slugs = [field.slug for field in fields]
        if len(slugs) != len(set(slugs)):
            raise ValueError(f"duplicate setting field slug in {key}")
        definition.group.value_model()
        self._definitions[key] = definition

    def get(self, key: str) -> SettingDefinition | None:
        return self._definitions.get(key)

    def keys(self) -> frozenset[str]:
        return frozenset(self._definitions)

    def definitions(self) -> tuple[SettingDefinition, ...]:
        return tuple(self._definitions.values())

    def clear(self) -> None:
        self._definitions.clear()


setting_registry = SettingRegistry()


def register_setting(group: type[SettingGroup]) -> None:
    setting_registry.register(SettingDefinition(group))


def clear_setting_registry() -> None:
    setting_registry.clear()

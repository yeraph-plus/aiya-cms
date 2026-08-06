"""Contracts for declarative runtime settings definitions and interpretation."""

from __future__ import annotations

import pytest

from inc import setting
from inc.kernel.settings import (
    SettingDefinition,
    SettingField,
    SettingGroup,
    SettingInterpreter,
    SettingPatch,
    SettingRegistry,
)


def validate_title(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("title must not be empty")
    return value


class DemoSettings(SettingGroup):
    slug = "demo"
    group_title = "Demo"
    group_description = "Declarative demo settings"

    title = SettingField(
        slug="title",
        title="Title",
        description="A title",
        value_type=str,
        default="Default",
        validator=validate_title,
    )
    enabled = SettingField(
        slug="enabled",
        title="Enabled",
        description="Whether enabled",
        value_type=bool,
        default=True,
        is_public=True,
    )


def test_declarative_definition_exposes_metadata_and_defaults() -> None:
    definition = SettingDefinition(DemoSettings)
    interpreter = SettingInterpreter(definition)

    assert definition.key == "demo"
    assert [field.slug for field in definition.fields] == ["title", "enabled"]
    assert interpreter.resolve({}).model_dump() == {"title": "Default", "enabled": True}
    metadata = interpreter.describe(interpreter.resolve({}), {}).fields
    assert metadata[0].slug == "title"
    assert metadata[1].is_public is True


def test_patch_persists_only_non_default_user_values_and_unset_restores_default() -> None:
    interpreter = SettingInterpreter(SettingDefinition(DemoSettings))

    resolved, overrides = interpreter.apply_patch(
        {}, SettingPatch(values={"title": " Custom ", "enabled": True})
    )
    assert resolved.title == "Custom"
    assert overrides.root == {"title": "Custom"}

    resolved, overrides = interpreter.apply_patch(
        overrides.root, SettingPatch(values={}, unset=["title"])
    )
    assert resolved.title == "Default"
    assert overrides.root == {}


def test_unknown_field_and_invalid_callback_are_rejected() -> None:
    interpreter = SettingInterpreter(SettingDefinition(DemoSettings))

    with pytest.raises(ValueError, match="unknown setting field"):
        interpreter.apply_patch({}, SettingPatch(values={"unknown": 1}))

    with pytest.raises(ValueError, match="both value and unset"):
        interpreter.apply_patch({}, SettingPatch(values={"title": "x"}, unset=["title"]))

    with pytest.raises(ValueError, match="title must not be empty"):
        interpreter.apply_patch({}, SettingPatch(values={"title": "  "}))


def test_registry_rejects_duplicate_group_and_field_slugs() -> None:
    registry = SettingRegistry()
    registry.register(SettingDefinition(DemoSettings))
    with pytest.raises(ValueError, match="duplicate setting group"):
        registry.register(SettingDefinition(DemoSettings))

    class DuplicateFields(SettingGroup):
        slug = "duplicate-fields"
        first = SettingField(
            slug="same", title="First", description="", value_type=str, default="a"
        )
        second = SettingField(
            slug="same", title="Second", description="", value_type=str, default="b"
        )

    with pytest.raises(ValueError, match="duplicate setting field"):
        registry.register(SettingDefinition(DuplicateFields))


@pytest.mark.asyncio
async def test_internal_setting_facade_is_context_bound() -> None:
    with pytest.raises(RuntimeError, match="not bound"):
        await setting.get(DemoSettings.title)

    class Reader:
        async def get_field(self, field: SettingField[str]) -> str:
            return str(field.default)

    token = setting.bind(Reader())  # type: ignore[arg-type]
    try:
        assert await setting.get(DemoSettings.title) == "Default"
    finally:
        setting.reset(token)

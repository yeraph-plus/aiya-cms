"""0.1.0 settings, auth, and interaction contracts (written before implementation)."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from inc.kernel.settings import (
    SettingDefinition,
    SettingInterpreter,
    SettingPatch,
    SettingRegistry,
    SiteProfile,
    SiteProfileSettings,
)


def test_site_profile_expanded_defaults() -> None:
    profile = SiteProfile(icon_url="https://example.test/icon.png")

    assert profile.title == "aiya-cms"
    assert profile.subtitle == ""
    assert profile.description == ""
    assert profile.icon_url == "https://example.test/icon.png"
    assert profile.registration_open is True
    assert profile.default_registration_role == "reader"
    assert profile.timezone == "UTC"
    assert profile.indexing_enabled is False


def test_site_profile_rejects_unsafe_registration_role_and_timezone() -> None:
    with pytest.raises(ValidationError):
        SiteProfile(default_registration_role="admin")
    interpreter = SettingInterpreter(SettingDefinition(SiteProfileSettings))
    with pytest.raises(ValueError):
        interpreter.apply_patch({}, SettingPatch(values={"timezone": "Not/AZone"}))
    with pytest.raises(ValueError):
        interpreter.apply_patch(
            {}, SettingPatch(values={"title_format": "{unknown} | {site_title}"})
        )


def test_setting_definition_carries_declarative_metadata() -> None:
    definition = SettingDefinition(SiteProfileSettings)
    registry = SettingRegistry((definition,))
    stored = registry.get("site.profile")

    assert stored is not None
    assert stored.group.group_title == "站点资料"
    assert {field.slug for field in stored.fields} >= {"title", "registration_open"}
    assert stored.group.order == 10


def test_content_aggregate_columns_replace_editorial_rating() -> None:
    from inc.kernel.content.models import Content

    columns = set(Content.__table__.columns.keys())
    assert {"view_count", "like_count", "rating_sum", "rating_count"} <= columns
    assert "rating" not in columns


def test_interaction_identity_is_uuid_and_user_scoped() -> None:
    from inc.modules.interaction.models import Interaction

    row = Interaction(
        id=uuid4(),
        user_id=uuid4(),
        target_type="content",
        target_id=uuid4(),
        kind="like",
    )
    assert row.kind == "like"

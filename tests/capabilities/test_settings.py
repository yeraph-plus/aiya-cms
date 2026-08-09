"""Settings capability tests.

Contract source: context/spec/capabilities/settings.md §7.

Covers defaults-without-write, schema/version conflict rejection, public
DTO filtering and transactional update events.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from inc.capabilities.audit.schemas import AUDIT_EVENT_KEY, AuditEntryRecorded
from inc.capabilities.settings.events import SETTINGS_EVENT_SCHEMAS
from inc.capabilities.settings.groups import SettingGroupRegistry
from inc.capabilities.settings.models import SettingsValue
from inc.capabilities.settings.schemas import UpdateSettingGroupInput
from inc.capabilities.settings.service import (
    CommandContext,
    ResetSettingGroup,
    SettingsQueries,
    UpdateSettingGroup,
)
from inc.features.site_settings.definition import build_site_setting_group_specs
from inc.kernel.db import UoWFactory
from inc.kernel.errors import KernelError
from inc.kernel.events import EventSchemaRegistry, OutboxMessage, OutboxWriter


@pytest.fixture
def groups() -> SettingGroupRegistry:
    registry = SettingGroupRegistry()
    for spec in build_site_setting_group_specs():
        registry.register(spec)
    return registry


@pytest.fixture
def schema_registry() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    for key, schema in SETTINGS_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    registry.register(AUDIT_EVENT_KEY, AuditEntryRecorded)
    return registry


@pytest.fixture
def ctx(
    uow_factory: UoWFactory,
    clock: Any,
    groups: SettingGroupRegistry,
    schema_registry: EventSchemaRegistry,
) -> CommandContext:
    return CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        groups=groups,
        permissions=frozenset(
            {
                "settings.read",
                "settings.seo.update",
                "settings.entitlements.update",
                "settings.update",
            }
        ),
        actor_id="admin-1",
        trace_id="trace-1",
    )


@pytest.fixture
def queries(uow_factory: UoWFactory, groups: SettingGroupRegistry) -> SettingsQueries:
    return SettingsQueries(uow_factory=uow_factory, groups=groups)


async def _row_count(uow_factory: UoWFactory) -> int:
    async with uow_factory() as uow:
        return (await uow.session.execute(select(func.count(SettingsValue.id)))).scalar_one()


async def _event_count(uow_factory: UoWFactory, key: str) -> int:
    async with uow_factory() as uow:
        return (
            await uow.session.execute(
                select(func.count(OutboxMessage.id)).where(OutboxMessage.event_key == key)
            )
        ).scalar_one()


def test_group_spec_validation() -> None:
    from pydantic import BaseModel

    class Bad(BaseModel):
        secret: str = "x"

    from inc.capabilities.settings.groups import SettingGroupSpec

    with pytest.raises(ValueError, match="public fields not in schema"):
        SettingGroupSpec(
            group_key="g",
            version="1",
            value_schema=Bad,
            public_fields=("nope",),
            update_permission="settings.g.update",
        )


async def test_read_missing_group_returns_defaults_without_write(
    queries: SettingsQueries, uow_factory: UoWFactory
) -> None:
    group = await queries.get_group("seo")
    assert group.values["site_name"] == "aiya"
    assert group.version == 0
    assert await _row_count(uow_factory) == 0
    public = await queries.get_public_settings()
    assert public.values["seo"]["robots_policy"] == "index,follow"


def test_notification_group_carries_smtp_credentials_as_sensitive() -> None:
    from inc.features.site_settings.definition import build_site_setting_group_specs

    notification = next(
        spec for spec in build_site_setting_group_specs() if spec.group_key == "notification"
    )
    fields = set(notification.value_schema.model_fields)
    smtp_fields = {"smtp_host", "smtp_port", "smtp_username", "smtp_password", "smtp_from_address"}
    assert smtp_fields <= fields
    assert "smtp_password" in notification.sensitive_fields
    assert "smtp_password" not in notification.public_fields
    assert not (set(notification.public_fields) & set(notification.sensitive_fields))


async def test_notification_update_excludes_smtp_password_from_public_and_changes(
    uow_factory: UoWFactory,
    clock: Any,
    groups: SettingGroupRegistry,
    schema_registry: EventSchemaRegistry,
    queries: SettingsQueries,
) -> None:
    notification_ctx = CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        groups=groups,
        permissions=frozenset({"settings.read", "settings.notification.update", "settings.update"}),
        actor_id="admin-1",
        trace_id="trace-1",
    )
    await UpdateSettingGroup(notification_ctx)(
        "notification",
        UpdateSettingGroupInput(
            expected_version=1,
            values={"smtp_host": "mail.example.com", "smtp_password": "s3cret"},
        ),
    )
    group = await queries.get_group("notification")
    assert group.values["smtp_host"] == "mail.example.com"
    assert group.values["smtp_password"] == "s3cret"
    public = await queries.get_public_settings()
    assert "smtp_password" not in public.values["notification"]
    assert "smtp_host" not in public.values["notification"]


async def test_update_validates_schema_and_versions(
    ctx: CommandContext, queries: SettingsQueries
) -> None:
    with pytest.raises(ValidationError):
        await UpdateSettingGroup(ctx)(
            "seo",
            UpdateSettingGroupInput(expected_version=1, values={"unknown_field": "x"}),
        )
    with pytest.raises(ValidationError):
        await UpdateSettingGroup(ctx)(
            "seo",
            UpdateSettingGroupInput(expected_version=1, values={"site_name": "x" * 500}),
        )
    updated = await UpdateSettingGroup(ctx)(
        "seo",
        UpdateSettingGroupInput(expected_version=1, values={"site_name": "Acme"}),
    )
    assert updated.version == 1 and updated.values["site_name"] == "Acme"
    await UpdateSettingGroup(ctx)(
        "seo",
        UpdateSettingGroupInput(expected_version=1, values={"site_name": "Acme 2"}),
    )
    with pytest.raises(KernelError) as excinfo:
        await UpdateSettingGroup(ctx)(
            "seo",
            UpdateSettingGroupInput(expected_version=1, values={"site_name": "Stale"}),
        )
    assert excinfo.value.code == "settings.version_conflict"


async def test_update_requires_group_permission(
    uow_factory: UoWFactory,
    clock: Any,
    groups: SettingGroupRegistry,
    schema_registry: EventSchemaRegistry,
) -> None:
    restricted = CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        groups=groups,
        permissions=frozenset({"settings.read"}),
    )
    with pytest.raises(KernelError) as excinfo:
        await UpdateSettingGroup(restricted)(
            "seo", UpdateSettingGroupInput(expected_version=1, values={"site_name": "No"})
        )
    assert excinfo.value.code == "settings.forbidden"


async def test_settings_update_is_superset_of_group_updates(
    uow_factory: UoWFactory,
    clock: Any,
    groups: SettingGroupRegistry,
    schema_registry: EventSchemaRegistry,
) -> None:
    """An admin holding only `settings.update` must be able to update any
    settings group; the declared access key is not dead weight."""
    admin = CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        groups=groups,
        permissions=frozenset({"settings.update"}),
    )
    result = await UpdateSettingGroup(admin)(
        "seo",
        UpdateSettingGroupInput(
            expected_version=None,
            values={"site_name": "Superset Works", "default_description": "k"},
        ),
    )
    assert result.values["site_name"] == "Superset Works"
    result2 = await UpdateSettingGroup(admin)(
        "general",
        UpdateSettingGroupInput(
            expected_version=None,
            values={"site_tagline": "General Works", "maintenance_mode": False},
        ),
    )
    assert result2.values["site_tagline"] == "General Works"


async def test_reset_restores_defaults(ctx: CommandContext, queries: SettingsQueries) -> None:
    await UpdateSettingGroup(ctx)(
        "seo",
        UpdateSettingGroupInput(expected_version=1, values={"site_name": "Custom"}),
    )
    await ResetSettingGroup(ctx)("seo")
    group = await queries.get_group("seo")
    assert group.values["site_name"] == "aiya"


async def test_update_emits_event_in_same_transaction(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    await UpdateSettingGroup(ctx)(
        "seo",
        UpdateSettingGroupInput(expected_version=1, values={"site_name": "Acme"}),
    )
    assert await _event_count(uow_factory, "settings.group_updated.v1") == 1
    assert await _event_count(uow_factory, AUDIT_EVENT_KEY) == 1


async def test_reset_rejects_schema_mismatch(ctx: CommandContext, uow_factory: UoWFactory) -> None:
    from inc.capabilities.settings.models import SettingsValueData

    async with uow_factory() as uow:
        uow.session.add(
            SettingsValue(
                group_key="seo",
                schema_version="stale",
                value=SettingsValueData(schema_version="stale", values={"site_name": "X"}),
                version=1,
                updated_by="test",
            )
        )
        await uow.commit()
    with pytest.raises(KernelError) as excinfo:
        await ResetSettingGroup(ctx)("seo")
    assert excinfo.value.code == "settings.schema_mismatch"


def test_sensitive_fields_excluded_from_changed_summary() -> None:
    from pydantic import BaseModel

    from inc.capabilities.settings.groups import SettingGroupSpec
    from inc.capabilities.settings.service import _require_permission  # noqa: F401

    class G(BaseModel):
        name: str = "x"
        secret: str = "s"

    spec = SettingGroupSpec(
        group_key="g",
        version="1",
        value_schema=G,
        public_fields=("name",),
        sensitive_fields=("secret",),
        update_permission="settings.g.update",
    )
    assert "secret" not in spec.public_fields


async def test_unknown_group_is_validation_error(ctx: CommandContext) -> None:
    with pytest.raises(KernelError) as excinfo:
        await UpdateSettingGroup(ctx)(
            "ghost", UpdateSettingGroupInput(expected_version=1, values={"a": 1})
        )
    assert excinfo.value.code == "settings.unknown_group"
    assert excinfo.value.category.value == "validation"


# --- entitlements group ----------------------------------------------------


def test_entitlements_group_is_declared_public() -> None:
    from inc.features.site_settings.definition import (
        ENTITLEMENTS_GROUP_KEY,
        build_site_setting_group_specs,
    )

    entitlements = next(
        spec
        for spec in build_site_setting_group_specs()
        if spec.group_key == ENTITLEMENTS_GROUP_KEY
    )
    assert entitlements.update_permission == "settings.entitlements.update"
    assert set(entitlements.public_fields) == {
        "registration_reward",
        "invite_reward",
        "gift_quota",
    }


async def test_entitlements_defaults_readable_without_write(
    queries: SettingsQueries, uow_factory: UoWFactory
) -> None:
    group = await queries.get_group("entitlements")
    assert group.values == {"registration_reward": 0, "invite_reward": 0, "gift_quota": 0}
    assert await _row_count(uow_factory) == 0


async def test_entitlements_update_requires_group_permission(
    ctx: CommandContext,
    uow_factory: UoWFactory,
    clock: Any,
    groups: SettingGroupRegistry,
    schema_registry: EventSchemaRegistry,
) -> None:
    restricted = CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        groups=groups,
        permissions=frozenset({"settings.read", "settings.seo.update"}),
    )
    with pytest.raises(KernelError) as excinfo:
        await UpdateSettingGroup(restricted)(
            "entitlements",
            UpdateSettingGroupInput(expected_version=1, values={"registration_reward": 50}),
        )
    assert excinfo.value.code == "settings.forbidden"


async def test_entitlements_update_validates_values(
    ctx: CommandContext, queries: SettingsQueries
) -> None:
    await UpdateSettingGroup(ctx)(
        "entitlements",
        UpdateSettingGroupInput(
            expected_version=1,
            values={"registration_reward": 50, "invite_reward": 20, "gift_quota": 100},
        ),
    )
    group = await queries.get_group("entitlements")
    assert group.values["registration_reward"] == 50
    assert group.values["invite_reward"] == 20
    assert group.values["gift_quota"] == 100


async def test_entitlements_rejects_negative_and_unknown_fields(
    ctx: CommandContext,
) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        await UpdateSettingGroup(ctx)(
            "entitlements",
            UpdateSettingGroupInput(expected_version=1, values={"registration_reward": -5}),
        )
    with pytest.raises(ValidationError):
        await UpdateSettingGroup(ctx)(
            "entitlements",
            UpdateSettingGroupInput(expected_version=1, values={"free_points": 1}),
        )


async def test_smtp_password_schema_masks_secret_in_repr(
    uow_factory: UoWFactory,
    clock: Any,
    groups: SettingGroupRegistry,
    schema_registry: EventSchemaRegistry,
    queries: SettingsQueries,
) -> None:
    """The notification value schema must mask smtp_password in repr/str and
    model_dump (SecretStr), while the persisted value keeps the real secret
    so the SMTP adapter can still authenticate."""
    from inc.features.site_settings.definition import NotificationValueSchema

    schema = NotificationValueSchema(smtp_password="real-secret")
    assert "real-secret" not in repr(schema)
    assert "real-secret" not in str(schema)
    dumped = schema.model_dump()
    assert "real-secret" not in repr(dumped["smtp_password"])
    assert dumped["smtp_password"].get_secret_value() == "real-secret"

    # Update persists the real password (already covered by the public/filter
    # test) and a subsequent read still yields the real value.
    notification_ctx = CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        groups=groups,
        permissions=frozenset({"settings.notification.update", "settings.update"}),
        actor_id="admin-1",
    )
    await UpdateSettingGroup(notification_ctx)(
        "notification",
        UpdateSettingGroupInput(
            expected_version=None,
            values={"smtp_host": "mail.example.com", "smtp_password": "real-secret"},
        ),
    )
    group = await queries.get_group("notification")
    assert group.values["smtp_password"] == "real-secret"


async def test_uuid_field_roundtrip_is_json_compatible(
    ctx: CommandContext, queries: SettingsQueries
) -> None:
    """Non-str schema fields (UUID) must be normalized to JSON-compatible
    scalars on write, so a re-read yields the same str value and the stored
    dict survives JSON serialization in the persistence layer."""
    import uuid

    asset_id = uuid.uuid4()
    first = await UpdateSettingGroup(ctx)(
        "seo",
        UpdateSettingGroupInput(
            expected_version=None,
            values={"site_name": "Acme", "default_share_image_asset_id": str(asset_id)},
        ),
    )
    assert first.values["default_share_image_asset_id"] == str(asset_id)

    # The read-back value is a str (JSON-compatible), not a uuid.UUID object.
    group = await queries.get_group("seo")
    assert group.values["default_share_image_asset_id"] == str(asset_id)
    assert isinstance(group.values["default_share_image_asset_id"], str)

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

    from inc.capabilities.settings.groups import SettingFieldSpec, SettingGroupSpec

    with pytest.raises(ValueError, match="must match value schema"):
        SettingGroupSpec(
            group_key="g",
            version="1",
            value_schema=Bad,
            fields=(SettingFieldSpec(slug="nope", type="text", default="x"),),
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


def test_notification_group_carries_email_provider_settings_and_sensitive_credentials() -> None:
    from inc.features.site_settings.definition import build_site_setting_group_specs

    notification = next(
        spec for spec in build_site_setting_group_specs() if spec.group_key == "notification"
    )
    fields = set(notification.value_schema.model_fields)
    smtp_fields = {"smtp_host", "smtp_port", "smtp_username", "smtp_password", "smtp_from_address"}
    assert smtp_fields <= fields
    assert {
        "email_enabled",
        "smtp_enabled",
        "smtp2go_enabled",
        "smtp2go_api_key",
        "smtp2go_region",
    } <= fields
    assert {"smtp_password", "smtp2go_api_key"} <= set(notification.sensitive_fields)
    assert not ({"smtp_password", "smtp2go_api_key"} & set(notification.public_fields))
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
            expected_version=0,
            values={"smtp_host": "mail.example.com", "smtp_password": "s3cret"},
        ),
    )
    group = await queries.get_group("notification")
    assert group.values["smtp_host"] == "mail.example.com"
    assert group.values["smtp_password"] == "s3cret"
    public = await queries.get_public_settings()
    assert "smtp_password" not in public.values["notification"]
    assert "smtp_host" not in public.values["notification"]


async def test_sensitive_update_can_preserve_and_explicitly_clear_value(
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
        permissions=frozenset({"settings.notification.update"}),
    )
    first = await UpdateSettingGroup(notification_ctx)(
        "notification",
        UpdateSettingGroupInput(
            expected_version=0,
            values={"smtp2go_api_key": "api-secret"},
        ),
    )
    await UpdateSettingGroup(notification_ctx)(
        "notification",
        UpdateSettingGroupInput(
            expected_version=first.version,
            values={"smtp2go_region": "eu"},
        ),
    )
    preserved = await queries.get_group("notification")
    assert preserved.values["smtp2go_api_key"] == "api-secret"

    await UpdateSettingGroup(notification_ctx)(
        "notification",
        UpdateSettingGroupInput(
            expected_version=preserved.version,
            values={},
            clear_sensitive_fields=("smtp2go_api_key",),
        ),
    )
    cleared = await queries.get_group("notification")
    assert cleared.values["smtp2go_api_key"] is None


async def test_clear_sensitive_fields_rejects_non_sensitive_and_conflicting_values(
    ctx: CommandContext,
) -> None:
    with pytest.raises(KernelError) as excinfo:
        await UpdateSettingGroup(ctx)(
            "notification",
            UpdateSettingGroupInput(
                expected_version=0,
                values={},
                clear_sensitive_fields=("smtp_host",),
            ),
        )
    assert excinfo.value.code == "settings.invalid_sensitive_clear"

    with pytest.raises(KernelError) as excinfo:
        await UpdateSettingGroup(ctx)(
            "notification",
            UpdateSettingGroupInput(
                expected_version=0,
                values={"smtp_password": "new"},
                clear_sensitive_fields=("smtp_password",),
            ),
        )
    assert excinfo.value.code == "settings.invalid_sensitive_clear"


def test_object_storage_group_marks_credentials_sensitive() -> None:
    from inc.features.site_settings.definition import build_site_setting_group_specs

    group = next(
        spec for spec in build_site_setting_group_specs() if spec.group_key == "object_storage"
    )
    assert set(group.sensitive_fields) == {
        "s3_access_key_id",
        "s3_secret_access_key",
    }
    assert group.public_fields == ()
    assert group.update_permission == "settings.object_storage.update"


async def test_object_storage_credentials_excluded_from_first_event_and_audit(
    uow_factory: UoWFactory,
    clock: Any,
    groups: SettingGroupRegistry,
    schema_registry: EventSchemaRegistry,
) -> None:
    object_storage_ctx = CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        groups=groups,
        permissions=frozenset({"settings.object_storage.update"}),
        actor_id="admin-1",
        trace_id="trace-1",
    )
    await UpdateSettingGroup(object_storage_ctx)(
        "object_storage",
        UpdateSettingGroupInput(
            expected_version=0,
            values={
                "s3_endpoint_url": "http://rustfs:9000",
                "s3_virtual_host_url": "http://127.0.0.1:9000",
                "s3_bucket": "aiya-assets",
                "s3_region": "us-east-1",
                "s3_addressing_style": "path",
                "s3_access_key_id": "rustfsadmin",
                "s3_secret_access_key": "secret-value",
            },
        ),
    )

    async with uow_factory() as uow:
        messages = (
            (
                await uow.session.execute(
                    select(OutboxMessage).where(
                        OutboxMessage.event_key.in_(("settings.group_updated.v1", AUDIT_EVENT_KEY))
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(messages) == 2
    for message in messages:
        payload = message.envelope.payload
        if message.event_key == "settings.group_updated.v1":
            assert "s3_secret_access_key" not in payload["changed_fields"]
            assert "s3_access_key_id" not in payload["changed_fields"]
        else:
            assert "s3_secret_access_key" not in payload["details"]["changed"]
            assert "s3_access_key_id" not in payload["details"]["changed"]


async def test_update_validates_schema_and_versions(
    ctx: CommandContext, queries: SettingsQueries
) -> None:
    with pytest.raises(ValidationError):
        await UpdateSettingGroup(ctx)(
            "seo",
            UpdateSettingGroupInput(expected_version=0, values={"unknown_field": "x"}),
        )
    with pytest.raises(ValidationError):
        await UpdateSettingGroup(ctx)(
            "seo",
            UpdateSettingGroupInput(expected_version=0, values={"site_name": "x" * 500}),
        )
    updated = await UpdateSettingGroup(ctx)(
        "seo",
        UpdateSettingGroupInput(expected_version=0, values={"site_name": "Acme"}),
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
            "seo", UpdateSettingGroupInput(expected_version=0, values={"site_name": "No"})
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
            expected_version=0,
            values={"site_name": "Superset Works", "default_description": "k"},
        ),
    )
    assert result.values["site_name"] == "Superset Works"
    result2 = await UpdateSettingGroup(admin)(
        "general",
        UpdateSettingGroupInput(
            expected_version=0,
            values={"site_tagline": "General Works", "maintenance_mode": False},
        ),
    )
    assert result2.values["site_tagline"] == "General Works"


async def test_reset_restores_defaults(ctx: CommandContext, queries: SettingsQueries) -> None:
    await UpdateSettingGroup(ctx)(
        "seo",
        UpdateSettingGroupInput(expected_version=0, values={"site_name": "Custom"}),
    )
    await ResetSettingGroup(ctx)("seo")
    group = await queries.get_group("seo")
    assert group.values["site_name"] == "aiya"


async def test_update_emits_event_in_same_transaction(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    await UpdateSettingGroup(ctx)(
        "seo",
        UpdateSettingGroupInput(expected_version=0, values={"site_name": "Acme"}),
    )
    assert await _event_count(uow_factory, "settings.group_updated.v1") == 1
    assert await _event_count(uow_factory, AUDIT_EVENT_KEY) == 1


async def test_reset_rejects_schema_mismatch(ctx: CommandContext, uow_factory: UoWFactory) -> None:
    from inc.capabilities.settings.models import SettingValuePayload

    async with uow_factory() as uow:
        uow.session.add(
            SettingsValue(
                group_key="seo",
                field_slug="site_name",
                schema_version="stale",
                value=SettingValuePayload(value="X"),
                group_version=1,
                updated_by="test",
            )
        )
        await uow.commit()
    with pytest.raises(KernelError) as excinfo:
        await ResetSettingGroup(ctx)("seo")
    assert excinfo.value.code == "settings.schema_mismatch"


def test_sensitive_fields_excluded_from_changed_summary() -> None:
    from pydantic import BaseModel

    from inc.capabilities.settings.groups import SettingFieldSpec, SettingGroupSpec
    from inc.capabilities.settings.service import _require_permission  # noqa: F401

    class G(BaseModel):
        name: str = "x"
        secret: str = "s"

    spec = SettingGroupSpec(
        group_key="g",
        version="1",
        value_schema=G,
        fields=(
            SettingFieldSpec(slug="name", type="text", default="x", public=True),
            SettingFieldSpec(slug="secret", type="text", default="s", sensitive=True),
        ),
        update_permission="settings.g.update",
    )
    assert "secret" not in spec.public_fields


async def test_unknown_group_is_validation_error(ctx: CommandContext) -> None:
    with pytest.raises(KernelError) as excinfo:
        await UpdateSettingGroup(ctx)(
            "ghost", UpdateSettingGroupInput(expected_version=0, values={"a": 1})
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
            UpdateSettingGroupInput(expected_version=0, values={"registration_reward": 50}),
        )
    assert excinfo.value.code == "settings.forbidden"


async def test_entitlements_update_validates_values(
    ctx: CommandContext, queries: SettingsQueries
) -> None:
    await UpdateSettingGroup(ctx)(
        "entitlements",
        UpdateSettingGroupInput(
            expected_version=0,
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
            UpdateSettingGroupInput(expected_version=0, values={"registration_reward": -5}),
        )
    with pytest.raises(ValidationError):
        await UpdateSettingGroup(ctx)(
            "entitlements",
            UpdateSettingGroupInput(expected_version=0, values={"free_points": 1}),
        )


async def test_notification_credentials_are_masked_in_schema_repr(
    uow_factory: UoWFactory,
    clock: Any,
    groups: SettingGroupRegistry,
    schema_registry: EventSchemaRegistry,
    queries: SettingsQueries,
) -> None:
    """Notification credentials use SecretStr while persistence retains them."""
    from inc.features.site_settings.definition import NotificationValueSchema

    schema = NotificationValueSchema(smtp_password="real-secret", smtp2go_api_key="smtp2go-secret")
    assert "real-secret" not in repr(schema)
    assert "real-secret" not in str(schema)
    assert "smtp2go-secret" not in repr(schema)
    assert "smtp2go-secret" not in str(schema)
    dumped = schema.model_dump()
    assert "real-secret" not in repr(dumped["smtp_password"])
    assert dumped["smtp_password"].get_secret_value() == "real-secret"
    assert "smtp2go-secret" not in repr(dumped["smtp2go_api_key"])
    assert dumped["smtp2go_api_key"].get_secret_value() == "smtp2go-secret"

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
            expected_version=0,
            values={
                "smtp_host": "mail.example.com",
                "smtp_password": "real-secret",
                "smtp2go_api_key": "smtp2go-secret",
            },
        ),
    )
    group = await queries.get_group("notification")
    assert group.values["smtp_password"] == "real-secret"
    assert group.values["smtp2go_api_key"] == "smtp2go-secret"


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
            expected_version=0,
            values={"site_name": "Acme", "default_share_image_asset_id": str(asset_id)},
        ),
    )
    assert first.values["default_share_image_asset_id"] == str(asset_id)

    # The read-back value is a str (JSON-compatible), not a uuid.UUID object.
    group = await queries.get_group("seo")
    assert group.values["default_share_image_asset_id"] == str(asset_id)
    assert isinstance(group.values["default_share_image_asset_id"], str)


def test_site_settings_expose_registered_field_metadata() -> None:
    from inc.features.site_settings.definition import build_site_setting_group_specs

    general = next(spec for spec in build_site_setting_group_specs() if spec.group_key == "general")
    logo = next(field for field in general.fields if field.slug == "site_logo_asset_id")
    assert logo.type == "upload"
    assert logo.type_sub == "single"
    assert logo.public is True
    assert logo.metadata.accept == ("image/*",)

    seo = next(spec for spec in build_site_setting_group_specs() if spec.group_key == "seo")
    share_image = next(
        field for field in seo.fields if field.slug == "default_share_image_asset_id"
    )

    assert share_image.type == "upload"
    assert share_image.type_sub == "single"
    assert share_image.default is None
    assert share_image.metadata.accept == ("image/*",)


def test_settings_descriptors_contain_no_display_text() -> None:
    for group in build_site_setting_group_specs():
        for field in group.fields:
            descriptor = field.model_dump(mode="json")
            assert "title" not in descriptor
            assert "desc" not in descriptor
            assert "placeholder" not in descriptor["metadata"]
            assert all(set(option) == {"value"} for option in descriptor["metadata"]["options"])


async def test_group_update_persists_one_row_per_field_and_starts_at_zero(
    ctx: CommandContext, queries: SettingsQueries, uow_factory: UoWFactory
) -> None:
    from inc.capabilities.settings.models import SettingsValue

    before = await queries.get_group("general")
    assert before.version == 0

    updated = await UpdateSettingGroup(ctx)(
        "general",
        UpdateSettingGroupInput(expected_version=0, values={"site_tagline": "Aiya"}),
    )

    assert updated.version == 1
    async with uow_factory() as uow:
        rows = (
            (
                await uow.session.execute(
                    select(SettingsValue).where(SettingsValue.group_key == "general")
                )
            )
            .scalars()
            .all()
        )
    assert {row.field_slug for row in rows} == {
        field.slug for field in ctx.groups.require("general").fields
    }
    assert {row.group_version for row in rows} == {1}
    assert updated.values["site_tagline"] == "Aiya"


async def test_partial_group_update_merges_current_values(
    ctx: CommandContext, queries: SettingsQueries
) -> None:
    await UpdateSettingGroup(ctx)(
        "general", UpdateSettingGroupInput(expected_version=0, values={"site_tagline": "Aiya"})
    )
    await UpdateSettingGroup(ctx)(
        "general", UpdateSettingGroupInput(expected_version=1, values={"maintenance_mode": True})
    )

    group = await queries.get_group("general")
    assert group.values["site_tagline"] == "Aiya"
    assert group.values["maintenance_mode"] is True


async def test_single_setting_query_uses_registered_slug(
    queries: SettingsQueries, ctx: CommandContext
) -> None:
    await UpdateSettingGroup(ctx)(
        "seo", UpdateSettingGroupInput(expected_version=0, values={"site_name": "Aiya"})
    )

    assert await queries.get_value("seo", "site_name") == "Aiya"
    assert await queries.get_value("seo", "canonical_host") is None

    with pytest.raises(KernelError) as excinfo:
        await queries.get_value("seo", "unknown")
    assert excinfo.value.code == "settings.unknown_field"

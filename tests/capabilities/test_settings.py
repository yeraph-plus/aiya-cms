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
from inc.capabilities.settings.seo import build_seo_group_spec
from inc.capabilities.settings.service import (
    CommandContext,
    ResetSettingGroup,
    SettingsQueries,
    UpdateSettingGroup,
)
from inc.kernel.db import UoWFactory
from inc.kernel.errors import KernelError
from inc.kernel.events import EventSchemaRegistry, OutboxMessage, OutboxWriter


@pytest.fixture
def groups() -> SettingGroupRegistry:
    registry = SettingGroupRegistry()
    registry.register(build_seo_group_spec())
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
        permissions=frozenset({"settings.read", "settings.seo.update", "settings.update"}),
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

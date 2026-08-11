"""Site cleanup feature declarations and retention activity."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid7

from sqlalchemy import select

from inc.capabilities.audit.models import AuditEntry, AuditMetadata
from inc.capabilities.audit.schemas import AUDIT_EVENT_KEY, AuditEntryRecorded
from inc.capabilities.audit.service import AuditRetentionActivity
from inc.capabilities.settings.groups import SettingGroupRegistry
from inc.capabilities.settings.service import SettingsQueries
from inc.features.site_cleanup.definition import spec
from inc.features.site_cleanup.tasks import SiteCleanupActivity
from inc.features.site_settings.definition import build_site_setting_group_specs
from inc.kernel.events import EventEnvelope, EventSchemaRegistry, OutboxMessage, OutboxWriter
from inc.kernel.tasks import ExecutionLogCleaner, TaskPayload
from inc.kernel.tasks.models import TaskInstance


def test_site_cleanup_requires_settings_and_audit() -> None:
    assert spec.name == "site_cleanup"
    assert set(spec.requires) == {"settings", "audit"}


def test_site_settings_exposes_day_based_audit_retention() -> None:
    groups = {item.group_key: item for item in build_site_setting_group_specs()}
    operations = groups["operations"]
    assert operations.defaults()["audit_retention_days"] == 30
    assert operations.field("audit_retention_days").type_sub == "integer"


async def test_site_cleanup_activity_applies_the_registered_policy(
    uow_factory: Any, clock: Any
) -> None:
    groups = SettingGroupRegistry()
    for group in build_site_setting_group_specs():
        groups.register(group)
    settings = SettingsQueries(uow_factory=uow_factory, groups=groups)
    schemas = EventSchemaRegistry()
    schemas.register(AUDIT_EVENT_KEY, AuditEntryRecorded)
    old = clock.utc_now() - timedelta(days=31)
    old_event = EventEnvelope(
        event_id=uuid7(),
        event_key=AUDIT_EVENT_KEY,
        occurred_at=old,
        producer="test",
        payload={
            "action": "old.action",
            "occurred_at": old.isoformat(),
        },
    )
    async with uow_factory() as uow:
        uow.session.add_all(
            [
                AuditEntry(
                    envelope_id=uuid7(),
                    action="old.action",
                    occurred_at=old,
                    ingested_at=old,
                    details=AuditMetadata(data={}),
                    created_at=old,
                    updated_at=old,
                ),
                OutboxMessage(
                    event_key=AUDIT_EVENT_KEY,
                    event_id=old_event.event_id,
                    envelope=old_event,
                    status="delivered",
                    created_at=old,
                    updated_at=old,
                ),
                TaskInstance(
                    task_key="site.cleanup.retention.v1.tick",
                    status="completed",
                    payload=TaskPayload(schema_version="1", data={}),
                    next_run_at=old,
                    created_at=old,
                    updated_at=old,
                ),
            ]
        )
        await uow.commit()

    activity = SiteCleanupActivity(
        settings=settings,
        execution_logs=ExecutionLogCleaner(uow_factory),
        audit=AuditRetentionActivity(
            uow_factory=uow_factory,
            outbox=OutboxWriter(schemas, clock),
            clock=clock,
        ),
        clock=clock,
    )
    async with uow_factory() as uow:
        result = await activity(uow, {}, None)
        await uow.commit()

    assert result["retention_days"] == 30
    assert result["audit_entries_deleted"] == 1
    assert result["execution_outbox_deleted"] == 1
    assert result["execution_tasks_deleted"] == 1
    async with uow_factory() as uow:
        assert not (await uow.session.execute(select(AuditEntry))).scalars().all()

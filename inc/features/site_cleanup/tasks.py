"""Explicit audit and execution-log retention activity."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from inc.capabilities.audit import AuditRetentionActivity
from inc.capabilities.settings import SettingsQueries
from inc.kernel.observability import get_logger
from inc.kernel.tasks import ExecutionLogCleaner
from inc.kernel.time import Clock

RETENTION_GROUP_KEY = "operations"
RETENTION_FIELD = "audit_retention_days"


class SiteCleanupActivity:
    """Apply the registered retention policy to terminal execution records."""

    def __init__(
        self,
        *,
        settings: SettingsQueries,
        execution_logs: ExecutionLogCleaner,
        audit: AuditRetentionActivity,
        clock: Clock,
    ) -> None:
        self._settings = settings
        self._execution_logs = execution_logs
        self._audit = audit
        self._clock = clock

    async def __call__(self, uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, int | str]:
        del ctx
        days = int(await self._settings.get_value(RETENTION_GROUP_KEY, RETENTION_FIELD))
        cutoff = self._clock.utc_now() - timedelta(days=days)
        execution = await self._execution_logs.cleanup_in_uow(uow, cutoff)
        audit_deleted = await self._audit.cleanup_in_uow(
            uow,
            cutoff=cutoff,
            details={
                "run_key": str(data.get("scheduled_for") or cutoff.isoformat()),
                "retention_days": days,
                "cutoff": cutoff.isoformat(),
                "execution_outbox_deleted": execution.outbox,
                "execution_inbox_deleted": execution.inbox,
                "execution_tasks_deleted": execution.tasks,
            },
        )
        get_logger("site_cleanup").info(
            "retention cleanup completed",
            audit_entries_deleted=audit_deleted,
            execution_outbox_deleted=execution.outbox,
            execution_inbox_deleted=execution.inbox,
            execution_tasks_deleted=execution.tasks,
            retention_days=days,
        )
        return {
            "retention_days": days,
            "audit_entries_deleted": audit_deleted,
            "execution_outbox_deleted": execution.outbox,
            "execution_inbox_deleted": execution.inbox,
            "execution_tasks_deleted": execution.tasks,
        }

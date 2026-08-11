"""Retention primitives for terminal kernel execution records.

Contract source: context/spec/capabilities/audit.md §3 and
context/spec/kernel/workflow-tasks.md §2.

Only terminal records are eligible. Pending work, leases and Cron anchors are
never touched by this cleaner; the site cleanup feature supplies the explicit
operational policy and cutoff.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete

from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.events.models import InboxReceipt, OutboxMessage
from inc.kernel.tasks.models import TaskInstance


@dataclass(frozen=True, slots=True)
class ExecutionLogCleanupCounts:
    """Rows removed from each kernel execution log."""

    outbox: int = 0
    inbox: int = 0
    tasks: int = 0


class ExecutionLogCleaner:
    """Delete terminal kernel execution records before an explicit cutoff."""

    def __init__(self, uow_factory: UoWFactory) -> None:
        self._uow_factory = uow_factory

    async def cleanup_before(  # type: ignore[return]
        self, cutoff: datetime
    ) -> ExecutionLogCleanupCounts:
        async with self._uow_factory() as uow:
            counts = await self.cleanup_in_uow(uow, cutoff)
            await uow.commit()
            return counts

    async def cleanup_in_uow(self, uow: UnitOfWork, cutoff: datetime) -> ExecutionLogCleanupCounts:
        """Delete eligible rows without committing the caller's transaction."""

        outbox_result = await uow.session.execute(
            delete(OutboxMessage).where(
                OutboxMessage.status.in_(("delivered", "dead")),
                OutboxMessage.updated_at < cutoff,
            )
        )
        inbox_result = await uow.session.execute(
            delete(InboxReceipt).where(InboxReceipt.processed_at < cutoff)
        )
        task_result = await uow.session.execute(
            delete(TaskInstance).where(
                TaskInstance.status.in_(("completed", "failed", "dead", "cancelled")),
                TaskInstance.updated_at < cutoff,
            )
        )
        return ExecutionLogCleanupCounts(
            outbox=outbox_result.rowcount or 0,
            inbox=inbox_result.rowcount or 0,
            tasks=task_result.rowcount or 0,
        )

"""Retention of terminal kernel execution records.

Contract source: context/spec/capabilities/audit.md §3 and
context/spec/kernel/workflow-tasks.md §2.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid7

from sqlalchemy import select

from inc.kernel.events import EventEnvelope
from inc.kernel.events.models import InboxReceipt, OutboxMessage
from inc.kernel.tasks import ExecutionLogCleaner, TaskPayload
from inc.kernel.tasks.models import TaskInstance


async def test_terminal_execution_records_are_cleaned_but_active_work_is_kept(
    uow_factory: Any, clock: Any
) -> None:
    old = clock.utc_now() - timedelta(days=31)
    recent = clock.utc_now() - timedelta(days=1)
    envelope = EventEnvelope(
        event_id=uuid7(),
        event_key="test.execution.recorded.v1",
        occurred_at=old,
        producer="test",
    )
    pending_event = EventEnvelope(
        event_id=uuid7(),
        event_key="test.execution.pending.v1",
        occurred_at=old,
        producer="test",
    )

    async with uow_factory() as uow:
        uow.session.add_all(
            [
                OutboxMessage(
                    event_key=envelope.event_key,
                    event_id=envelope.event_id,
                    envelope=envelope,
                    status="delivered",
                    attempts=1,
                    created_at=old,
                    updated_at=old,
                ),
                OutboxMessage(
                    event_key=pending_event.event_key,
                    event_id=pending_event.event_id,
                    envelope=pending_event,
                    status="pending",
                    next_attempt_at=recent,
                    created_at=old,
                    updated_at=old,
                ),
                InboxReceipt(
                    handler_key="test.handler.v1",
                    event_id=envelope.event_id,
                    processed_at=old,
                    created_at=old,
                    updated_at=old,
                ),
                TaskInstance(
                    task_key="test.task.completed.v1",
                    status="completed",
                    payload=TaskPayload(schema_version="1", data={}),
                    next_run_at=recent,
                    created_at=old,
                    updated_at=old,
                ),
                TaskInstance(
                    task_key="test.task.claimed.v1",
                    status="claimed",
                    payload=TaskPayload(schema_version="1", data={}),
                    next_run_at=recent,
                    created_at=old,
                    updated_at=old,
                ),
            ]
        )
        await uow.commit()

    counts = await ExecutionLogCleaner(uow_factory).cleanup_before(
        clock.utc_now() - timedelta(days=30)
    )

    assert counts.outbox == 1
    assert counts.inbox == 1
    assert counts.tasks == 1
    async with uow_factory() as uow:
        assert len((await uow.session.execute(select(OutboxMessage))).scalars().all()) == 1
        assert len((await uow.session.execute(select(InboxReceipt))).scalars().all()) == 0
        tasks = (await uow.session.execute(select(TaskInstance))).scalars().all()
        assert len(tasks) == 1 and tasks[0].status == "claimed"

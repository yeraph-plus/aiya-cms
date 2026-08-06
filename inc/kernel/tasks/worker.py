"""Task worker: lease-based claiming, retry, dead letter and shutdown.

Contract source: context/spec/kernel/workflow-tasks.md §3/§5/§8.

The worker claims due tasks with a portable conditional update (PostgreSQL
uses ``FOR UPDATE SKIP LOCKED``), executes each handler with a timeout and
its own UoW, then records retry/dead/completed outcomes. Shutdown stops
claiming new tasks and lets the in-flight task finish; a hard crash leaves
the lease to expire and be reclaimed, with idempotency protecting business
outcomes.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update

from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.errors import RetryCategory, classify_retry
from inc.kernel.observability import MetricRegistry
from inc.kernel.tasks.models import TaskInstance
from inc.kernel.tasks.registry import TaskRegistry
from inc.kernel.time import Clock
from inc.kernel.workflow.models import VersionedState
from inc.kernel.workflow.spec import ActivityContext


class TaskRepository:
    """Persistence for kernel task instances."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    @property
    def session(self) -> Any:
        return self._uow.session

    async def claim_due(
        self,
        *,
        batch: int,
        lease_owner: str,
        lease_seconds: int,
        now: Any,
    ) -> list[TaskInstance]:
        due = and_(
            TaskInstance.status.in_(("pending", "claimed")),
            TaskInstance.next_run_at <= now,
            or_(
                TaskInstance.lease_expires_at.is_(None),
                TaskInstance.lease_expires_at < now,
            ),
        )
        select_ids = (
            select(TaskInstance.id).where(due).order_by(TaskInstance.next_run_at, TaskInstance.id)
        )
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            select_ids = select_ids.with_for_update(skip_locked=True)
        ids = list((await self.session.execute(select_ids.limit(batch))).scalars())
        if not ids:
            return []
        expires_at = now + timedelta(seconds=lease_seconds)
        await self.session.execute(
            update(TaskInstance)
            .where(TaskInstance.id.in_(ids), due)
            .values(status="claimed", lease_owner=lease_owner, lease_expires_at=expires_at)
        )
        rows = (
            (
                await self.session.execute(
                    select(TaskInstance).where(TaskInstance.id.in_(ids)).order_by(TaskInstance.id)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def mark_completed(self, task: TaskInstance, *, result: dict[str, Any]) -> None:
        task.status = "completed"
        task.lease_owner = None
        task.lease_expires_at = None
        task.result = VersionedState(schema_version="1", data=result)
        task.error_category = None
        task.error_summary = None

    async def mark_retry(
        self,
        task: TaskInstance,
        *,
        next_run_at: Any,
        error_category: RetryCategory,
        error_summary: str,
    ) -> None:
        task.status = "pending"
        task.attempt += 1
        task.next_run_at = next_run_at
        task.lease_owner = None
        task.lease_expires_at = None
        task.error_category = error_category.value
        task.error_summary = error_summary[:500]

    async def mark_dead(
        self, task: TaskInstance, *, error_category: RetryCategory, error_summary: str
    ) -> None:
        task.status = "dead"
        task.attempt += 1
        task.lease_owner = None
        task.lease_expires_at = None
        task.error_category = error_category.value
        task.error_summary = error_summary[:500]

    async def count_by_status(self, status: str) -> int:
        result = await self.session.execute(
            select(TaskInstance.id).where(TaskInstance.status == status)
        )
        return len(list(result.scalars()))


class TaskWorker:
    """Lease-based executor for registered task specs."""

    def __init__(
        self,
        *,
        uow_factory: UoWFactory,
        registry: TaskRegistry,
        clock: Clock,
        metrics: MetricRegistry | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._registry = registry
        self._clock = clock
        self._metrics = metrics

    async def run_cycle(
        self,
        *,
        batch: int = 10,
        lease_owner: str = "task-worker",
        lease_seconds: int = 60,
    ) -> int:
        """Claim and execute up to *batch* due tasks; returns count."""

        async with self._uow_factory() as claim_uow:
            tasks = await TaskRepository(claim_uow).claim_due(
                batch=batch,
                lease_owner=lease_owner,
                lease_seconds=lease_seconds,
                now=self._clock.utc_now(),
            )
            await claim_uow.commit()

        for task in tasks:
            await self._execute(task)
        return len(tasks)

    async def run_forever(
        self,
        *,
        batch: int = 10,
        lease_owner: str = "task-worker",
        lease_seconds: int = 60,
        sleep_seconds: float = 1.0,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Claim loop with graceful shutdown: stop between cycles."""

        stop = stop_event or asyncio.Event()
        while not stop.is_set():
            await self.run_cycle(batch=batch, lease_owner=lease_owner, lease_seconds=lease_seconds)
            try:
                await asyncio.wait_for(stop.wait(), timeout=sleep_seconds)
            except TimeoutError:
                pass

    async def _execute(self, task: TaskInstance) -> None:
        spec = self._registry.lookup(task.task_key)
        async with self._uow_factory() as uow:
            fresh = await uow.session.get(TaskInstance, task.id)
            if spec is None or fresh is None:
                if fresh is not None:
                    await TaskRepository(uow).mark_dead(
                        fresh,
                        error_category=RetryCategory.PERMANENT,
                        error_summary="unregistered task",
                    )
                await uow.commit()
                return

            try:
                result = await asyncio.wait_for(
                    spec.handler(
                        uow,
                        fresh.payload.data,
                        ActivityContext(attempt=fresh.attempt + 1),
                    ),
                    timeout=spec.timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001 - failures feed the retry state machine
                category = classify_retry(exc)
                if not spec.retry.should_retry(category=category, attempts=fresh.attempt + 1):
                    await TaskRepository(uow).mark_dead(
                        fresh, error_category=category, error_summary=str(exc)
                    )
                else:
                    delay = spec.retry.next_attempt_delay(
                        category=category, attempts=fresh.attempt + 1
                    )
                    await TaskRepository(uow).mark_retry(
                        fresh,
                        next_run_at=self._clock.utc_now() + timedelta(seconds=delay),
                        error_category=category,
                        error_summary=str(exc),
                    )
                await uow.commit()
                return

            await TaskRepository(uow).mark_completed(fresh, result=result)
            await uow.commit()

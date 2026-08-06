"""Task worker and Cron tests: lease, retry, shutdown, single trigger.

Contract source: context/spec/kernel/workflow-tasks.md §3/§6/§8.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from inc.kernel.db import UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.tasks import (
    CronRegistry,
    CronScheduler,
    CronSpec,
    TaskPayload,
    TaskRegistry,
    TaskRepository,
    TaskSpec,
    TaskWorker,
)
from inc.kernel.tasks.models import CronState, TaskInstance
from inc.kernel.time.fake import FakeClock
from inc.kernel.workflow.spec import RetryPolicy


def make_task_registry(spec: TaskSpec) -> TaskRegistry:
    registry = TaskRegistry()
    registry.register(spec)
    return registry


async def test_worker_executes_task_successfully(
    uow_factory: UoWFactory,
    clock: FakeClock,
) -> None:
    effects: dict[str, int] = {}

    async def handler(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        effects["run"] = effects.get("run", 0) + 1
        return {"ok": True}

    spec = TaskSpec(key="test.job.run.v1", handler=handler)
    registry = make_task_registry(spec)
    worker = TaskWorker(uow_factory=uow_factory, registry=registry, clock=clock)

    async with uow_factory() as uow:
        uow.session.add(
            TaskInstance(
                task_key=spec.key,
                status="pending",
                payload=_payload(),
                next_run_at=clock.utc_now(),
                timeout_seconds=60,
            )
        )
        await uow.commit()

    assert await worker.run_cycle(lease_seconds=60) == 1
    assert effects == {"run": 1}

    async with uow_factory() as uow:
        task = (await uow.session.execute(select(TaskInstance))).scalars().first()
        assert task is not None
        assert task.status == "completed"
        assert task.result is not None and task.result.data == {"ok": True}


def _payload() -> Any:

    return TaskPayload(schema_version="1", data={})


async def test_worker_retries_then_completes(
    uow_factory: UoWFactory,
    clock: FakeClock,
) -> None:
    attempts = 0

    async def flaky(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient")
        return {"ok": True}

    spec = TaskSpec(
        key="test.job.retry.v1",
        handler=flaky,
        retry=RetryPolicy(base_delay_seconds=1.0, factor=2.0, jitter_seconds=0.0),
    )
    registry = make_task_registry(spec)
    worker = TaskWorker(uow_factory=uow_factory, registry=registry, clock=clock)

    async with uow_factory() as uow:
        uow.session.add(
            TaskInstance(
                task_key=spec.key,
                status="pending",
                payload=_payload(),
                next_run_at=clock.utc_now(),
                timeout_seconds=60,
            )
        )
        await uow.commit()

    assert await worker.run_cycle(lease_seconds=60) == 1
    async with uow_factory() as uow:
        task = (await uow.session.execute(select(TaskInstance))).scalars().first()
        assert task is not None
        assert task.status == "pending"
        assert task.attempt == 1
        assert task.next_run_at is not None

    clock.advance(timedelta(seconds=30))
    assert await worker.run_cycle(lease_seconds=60) == 1
    async with uow_factory() as uow:
        task = (await uow.session.execute(select(TaskInstance))).scalars().first()
        assert task is not None
        assert task.status == "completed"
    assert attempts == 2


async def test_worker_dead_letter_after_attempts(
    uow_factory: UoWFactory,
    clock: FakeClock,
) -> None:
    async def failing(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        raise KernelError(
            code="test.job.rejected",
            category=ErrorCategory.VALIDATION,
            message="permanent",
        )

    spec = TaskSpec(
        key="test.job.dead.v1",
        handler=failing,
        retry=RetryPolicy(max_attempts=3, jitter_seconds=0.0),
    )
    registry = make_task_registry(spec)
    worker = TaskWorker(uow_factory=uow_factory, registry=registry, clock=clock)

    async with uow_factory() as uow:
        uow.session.add(
            TaskInstance(
                task_key=spec.key,
                status="pending",
                payload=_payload(),
                next_run_at=clock.utc_now(),
                timeout_seconds=60,
            )
        )
        await uow.commit()

    assert await worker.run_cycle(lease_seconds=60) == 1
    async with uow_factory() as uow:
        task = (await uow.session.execute(select(TaskInstance))).scalars().first()
        assert task is not None
        assert task.status == "dead"
        assert task.error_category == "permanent"


async def test_worker_unregistered_task_goes_dead(
    uow_factory: UoWFactory,
    clock: FakeClock,
) -> None:
    worker = TaskWorker(uow_factory=uow_factory, registry=TaskRegistry(), clock=clock)
    async with uow_factory() as uow:
        uow.session.add(
            TaskInstance(
                task_key="test.job.ghost.v1",
                status="pending",
                payload=_payload(),
                next_run_at=clock.utc_now(),
                timeout_seconds=60,
            )
        )
        await uow.commit()

    assert await worker.run_cycle(lease_seconds=60) == 1
    async with uow_factory() as uow:
        task = (await uow.session.execute(select(TaskInstance))).scalars().first()
        assert task is not None
        assert task.status == "dead"


async def test_lease_blocks_other_workers_until_expiry(
    uow_factory: UoWFactory,
    clock: FakeClock,
) -> None:
    async def handler(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        return {}

    registry = make_task_registry(TaskSpec(key="test.job.lease.v1", handler=handler))

    async with uow_factory() as uow:
        uow.session.add(
            TaskInstance(
                task_key="test.job.lease.v1",
                status="pending",
                payload=_payload(),
                next_run_at=clock.utc_now(),
                timeout_seconds=60,
            )
        )
        await uow.commit()

    worker_b = TaskWorker(uow_factory=uow_factory, registry=registry, clock=clock)

    # worker-a crashes mid-task: lease stays valid for 60s
    async with uow_factory() as uow:
        tasks = await TaskRepository(uow).claim_due(
            batch=10, lease_owner="worker-a", lease_seconds=60, now=clock.utc_now()
        )
        await uow.commit()
    assert len(tasks) == 1

    assert await worker_b.run_cycle(lease_seconds=60) == 0  # blocked by lease

    clock.advance(timedelta(seconds=120))
    assert await worker_b.run_cycle(lease_seconds=60) == 1  # reclaimed after expiry


async def test_worker_graceful_shutdown_stops_claiming(
    uow_factory: UoWFactory,
    clock: FakeClock,
) -> None:
    started = asyncio.Event()

    async def handler(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        started.set()
        await asyncio.sleep(0.05)
        return {}

    registry = make_task_registry(TaskSpec(key="test.job.shutdown.v1", handler=handler))
    worker = TaskWorker(uow_factory=uow_factory, registry=registry, clock=clock)

    async with uow_factory() as uow:
        uow.session.add(
            TaskInstance(
                task_key="test.job.shutdown.v1",
                status="pending",
                payload=_payload(),
                next_run_at=clock.utc_now(),
                timeout_seconds=60,
            )
        )
        await uow.commit()

    stop = asyncio.Event()
    loop_task = asyncio.create_task(worker.run_forever(stop_event=stop, sleep_seconds=0.01))
    await asyncio.wait_for(started.wait(), timeout=5)
    stop.set()  # graceful shutdown request
    await asyncio.wait_for(loop_task, timeout=5)

    async with uow_factory() as uow:
        task = (await uow.session.execute(select(TaskInstance))).scalars().first()
        assert task is not None
        assert task.status == "completed"  # in-flight task finished, no new claims


async def test_cron_fires_once_per_due_trigger(
    uow_factory: UoWFactory,
    clock: FakeClock,
) -> None:
    registry = CronRegistry()
    registry.register(
        CronSpec(key="test.cron.every.minute.v1", schedule="* * * * *", timezone="UTC")
    )
    scheduler = CronScheduler(uow_factory=uow_factory, registry=registry, clock=clock)

    assert await scheduler.tick() == 0  # first tick only anchors next_run_at
    async with uow_factory() as uow:
        state = (await uow.session.execute(select(CronState))).scalars().first()
        assert state is not None

    clock.advance(timedelta(minutes=2))
    assert await scheduler.tick() == 1  # one due trigger -> one task

    async with uow_factory() as uow:
        tasks = (await uow.session.execute(select(TaskInstance))).scalars().all()
        assert len(tasks) == 1
        assert tasks[0].task_key == "test.cron.every.minute.v1.tick"

    # Re-tick immediately: no double fire.
    assert await scheduler.tick() == 0
    async with uow_factory() as uow:
        tasks = (await uow.session.execute(select(TaskInstance))).scalars().all()
        assert len(tasks) == 1


async def test_cron_multiple_instances_single_trigger(
    uow_factory: UoWFactory,
    clock: FakeClock,
) -> None:
    registry = CronRegistry()
    registry.register(CronSpec(key="test.cron.hourly.v1", schedule="0 * * * *", timezone="UTC"))
    scheduler_a = CronScheduler(uow_factory=uow_factory, registry=registry, clock=clock)
    scheduler_b = CronScheduler(uow_factory=uow_factory, registry=registry, clock=clock)

    await scheduler_a.tick()
    clock.advance(timedelta(hours=1))
    assert await scheduler_a.tick() == 1
    assert await scheduler_b.tick() == 0  # same due window, only one lease holder

    async with uow_factory() as uow:
        tasks = (await uow.session.execute(select(TaskInstance))).scalars().all()
        assert len(tasks) == 1


async def test_cron_invalid_schedule_fails_at_trigger_build(
    uow_factory: UoWFactory,
    clock: FakeClock,
) -> None:
    registry = CronRegistry()
    registry.register(CronSpec(key="test.cron.bad.v1", schedule="not a cron", timezone="UTC"))
    scheduler = CronScheduler(uow_factory=uow_factory, registry=registry, clock=clock)
    try:
        await scheduler.tick()
    except ValueError:
        return
    raise AssertionError("invalid schedule must fail fast")

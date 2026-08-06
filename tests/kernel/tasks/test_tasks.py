"""Task shell integration tests (M1.10 / tasks.md)."""

import asyncio
from typing import ClassVar

import pytest
from pydantic import BaseModel

from inc.kernel.db import UoWExecutor
from inc.kernel.errors import AppError
from inc.kernel.events import fresh_event_bus
from inc.kernel.security import Principal
from inc.kernel.tasks import (
    TASK_001,
    TASK_002,
    BaseTask,
    TaskError,
    TaskInstance,
    TaskPayload,
    TaskScheduler,
    TaskState,
    TaskUnitOfWork,
)


class WorkPayload(BaseModel):
    value: int


class WorkResult(BaseModel):
    value: int


hook_log: list[str] = []


class SuccessTask(BaseTask[WorkPayload, WorkResult]):
    task_type = "tests.success"
    Payload = WorkPayload
    Result = WorkResult
    timeout_seconds = 2

    async def run(self) -> WorkResult:
        hook_log.append("run")
        return WorkResult(value=self.payload.value * 2)

    async def on_success(self, result: WorkResult) -> None:
        hook_log.append(f"success:{result.value}")


class FailureTask(BaseTask[WorkPayload, WorkResult]):
    task_type = "tests.failure"
    Payload = WorkPayload
    Result = WorkResult
    timeout_seconds = 2

    async def run(self) -> WorkResult:
        hook_log.append("run")
        raise RuntimeError("boom")

    async def rollback(self, error: BaseException) -> None:
        hook_log.append(f"rollback:{error}")

    async def on_failure(self, error: BaseException) -> None:
        hook_log.append(f"failure:{error}")


class TimeoutTask(BaseTask[WorkPayload, WorkResult]):
    task_type = "tests.timeout"
    Payload = WorkPayload
    Result = WorkResult
    timeout_seconds = 1

    async def run(self) -> WorkResult:
        await asyncio.sleep(5)
        return WorkResult(value=1)


class InvalidTask(BaseTask[WorkPayload, WorkResult]):
    task_type: ClassVar[str] = ""
    Payload = WorkPayload
    Result = WorkResult

    async def run(self) -> WorkResult:
        return WorkResult(value=1)


def make_scheduler(session_factory, task_settings) -> TaskScheduler:
    return TaskScheduler(
        UoWExecutor(lambda: TaskUnitOfWork(session_factory)),
        event_bus=fresh_event_bus(),
        settings=task_settings,
    )


@pytest.mark.asyncio
async def test_task_success_persists_result_and_hook_order(session_factory, task_settings) -> None:
    hook_log.clear()
    scheduler = make_scheduler(session_factory, task_settings)
    scheduler.register_task_class(SuccessTask)
    task_id = await scheduler.start_task("tests.success", WorkPayload(value=3))
    await scheduler.wait_idle()
    instance = await scheduler.get_instance(task_id)
    assert instance.state is TaskState.SUCCEEDED
    assert isinstance(instance.result, WorkResult)
    assert instance.result.value == 6
    assert hook_log == ["run", "success:6"]
    await scheduler.stop()


@pytest.mark.asyncio
async def test_failure_runs_rollback_then_on_failure_and_records_failed(
    session_factory, task_settings
) -> None:
    hook_log.clear()
    scheduler = make_scheduler(session_factory, task_settings)
    scheduler.register_task_class(FailureTask)
    task_id = await scheduler.start_task("tests.failure", WorkPayload(value=1))
    await scheduler.wait_idle()
    instance = await scheduler.get_instance(task_id)
    assert instance.state is TaskState.FAILED
    assert instance.error is not None
    assert instance.error.code == "TASK_FAILED"
    assert hook_log == ["run", "rollback:boom", "failure:boom"]
    await scheduler.stop()


@pytest.mark.asyncio
async def test_timeout_cancels_task_and_marks_cancelled(session_factory, task_settings) -> None:
    scheduler = make_scheduler(session_factory, task_settings)
    scheduler.register_task_class(TimeoutTask)
    task_id = await scheduler.start_task("tests.timeout", WorkPayload(value=1))
    await scheduler.wait_idle()
    instance = await scheduler.get_instance(task_id)
    assert instance.state is TaskState.CANCELLED
    assert instance.error is not None
    assert instance.error.code == "TASK_003"
    await scheduler.stop()


@pytest.mark.asyncio
async def test_idempotency_only_deduplicates_unfinished_instances(
    session_factory, task_settings
) -> None:
    scheduler = make_scheduler(session_factory, task_settings)
    scheduler.register_task_class(SuccessTask)
    first = await scheduler.start_task(
        "tests.success", WorkPayload(value=1), idempotency_key="same"
    )
    second = await scheduler.start_task(
        "tests.success", WorkPayload(value=99), idempotency_key="same"
    )
    assert first == second
    await scheduler.wait_idle()
    third = await scheduler.start_task(
        "tests.success", WorkPayload(value=2), idempotency_key="same"
    )
    assert third != first
    await scheduler.wait_idle()
    await scheduler.stop()


def test_duplicate_task_registration_and_cron_are_explicit(session_factory, task_settings) -> None:
    scheduler = make_scheduler(session_factory, task_settings)
    scheduler.register_task_class(SuccessTask)
    with pytest.raises(AppError) as duplicate:
        scheduler.register_task_class(SuccessTask)
    assert duplicate.value.code == TASK_001
    with pytest.raises(AppError) as invalid:
        scheduler.register_task_class(InvalidTask)
    assert invalid.value.code == TASK_001

    received: list[Principal] = []

    async def cron(principal: Principal) -> None:
        received.append(principal)

    scheduler.register_cron("tests.cron", "*/5 * * * *", cron)
    scheduler.register_cron("tests.cron", "*/5 * * * *", cron)
    job = scheduler.apscheduler.get_job("tests.cron")
    assert job is not None
    asyncio.run(job.func())
    assert received and received[0].is_system_bot is True


@pytest.mark.asyncio
async def test_orphan_reaper_marks_expired_running_instance_failed(
    session_factory, task_settings
) -> None:
    scheduler = make_scheduler(session_factory, task_settings)
    scheduler.register_task_class(SuccessTask)
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)

    async def insert(uow: TaskUnitOfWork) -> None:
        await uow.tasks.add(
            TaskInstance(
                id=task_id,
                task_type="tests.success",
                state=TaskState.RUNNING.value,
                payload=TaskPayload(value=1),
                timeout_at=now - timedelta(seconds=1),
            )
        )

    task_id = __import__("uuid").uuid4()
    await scheduler._executor.write(insert)
    assert await scheduler.reap_orphans() == 1
    instance = await scheduler.get_instance(task_id)
    assert instance.state is TaskState.FAILED
    assert instance.error == TaskError(code="orphan", message="task process was not running")
    assert await scheduler.reap_orphans() == 0
    await scheduler.stop()


@pytest.mark.asyncio
async def test_wakeup_is_a_hint_and_timeout_returns_false(session_factory, task_settings) -> None:
    scheduler = make_scheduler(session_factory, task_settings)
    scheduler.register_task_class(SuccessTask)
    task_id = await scheduler.start_task("tests.success", WorkPayload(value=1))
    await scheduler.wait_idle()
    waiter = asyncio.create_task(scheduler.wait_wakeup(task_id, 1))
    await asyncio.sleep(0)
    scheduler.notify_wakeup(task_id)
    assert await waiter is True
    assert await scheduler.wait_wakeup(task_id, 0.01) is False
    await scheduler.stop()


@pytest.mark.asyncio
async def test_terminal_state_cannot_be_finished_again(session_factory, task_settings) -> None:
    scheduler = make_scheduler(session_factory, task_settings)
    scheduler.register_task_class(SuccessTask)
    task_id = await scheduler.start_task("tests.success", WorkPayload(value=1))
    await scheduler.wait_idle()
    with pytest.raises(AppError) as invalid:
        await scheduler._finish(task_id, TaskState.FAILED, error=TaskError(code="x", message="x"))
    assert invalid.value.code == TASK_002
    await scheduler.stop()

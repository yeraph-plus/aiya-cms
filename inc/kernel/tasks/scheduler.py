"""APScheduler shell, task lifecycle persistence and wakeup handling."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar, cast
from uuid import UUID

from apscheduler.jobstores.memory import MemoryJobStore  # type: ignore[import-untyped]
from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError

from inc.kernel.config import Settings, get_settings
from inc.kernel.db import Page, UoWExecutor, integrity_to_app_error, new_uuid7
from inc.kernel.errors import AppError
from inc.kernel.events import Event, EventBus, get_event_bus
from inc.kernel.logging import get_logger
from inc.kernel.security import Principal

from .base import BaseTask
from .errors import TASK_001, TASK_002, TASK_003, TASK_004
from .events import TASK_EVENT_TYPES, TaskEventPayload
from .models import (
    TaskError,
    TaskInstance,
    TaskInstanceRead,
    TaskPayload,
    TaskQuery,
    TaskResult,
    TaskState,
)
from .uow import TaskUnitOfWork

logger = get_logger(__name__)
WAKEUP_CHANNEL = "aiya_task_wakeup"

TTask = TypeVar("TTask", bound=BaseTask[Any, Any])


class TaskScheduler:
    """Explicit task class/Cron registry around APScheduler 3.x."""

    def __init__(
        self,
        executor: UoWExecutor[TaskUnitOfWork],
        *,
        event_bus: EventBus | None = None,
        settings: Settings | None = None,
        clock: Callable[[], datetime] | None = None,
        apscheduler: AsyncIOScheduler | None = None,
        listener_factory: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        self._executor = executor
        self._settings = settings or get_settings()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._event_bus = event_bus or get_event_bus()
        for event_type in TASK_EVENT_TYPES:
            if not self._event_bus.is_registered(event_type):
                self._event_bus.register(event_type)
        self._task_classes: dict[str, type[BaseTask[Any, Any]]] = {}
        self._jobs: set[asyncio.Task[None]] = set()
        self._waiters: dict[UUID, set[asyncio.Event]] = {}
        self._listener_factory = listener_factory
        self._listener_task: asyncio.Task[None] | None = None
        self._listener_stop: asyncio.Event | None = None
        self._apscheduler = apscheduler or AsyncIOScheduler(
            timezone="UTC", jobstores={"default": MemoryJobStore()}
        )

    @property
    def apscheduler(self) -> AsyncIOScheduler:
        return self._apscheduler

    def register_task_class(self, task_class: type[BaseTask[Any, Any]]) -> None:
        """Register a task class exactly once during application wiring."""

        task_type = getattr(task_class, "task_type", "")
        payload_type = getattr(task_class, "Payload", None)
        result_type = getattr(task_class, "Result", None)
        timeout_seconds = getattr(task_class, "timeout_seconds", 0)
        if (
            not inspect.isclass(task_class)
            or not issubclass(task_class, BaseTask)
            or not isinstance(task_type, str)
            or not task_type
            or not inspect.isclass(payload_type)
            or not issubclass(payload_type, BaseModel)
            or not inspect.isclass(result_type)
            or not issubclass(result_type, BaseModel)
            or not isinstance(timeout_seconds, int)
            or timeout_seconds <= 0
        ):
            raise AppError(
                TASK_001, detail={"task_type": str(task_type), "reason": "invalid class"}
            )
        if task_type in self._task_classes:
            raise AppError(TASK_001, detail={"task_type": task_type, "reason": "duplicate"})
        self._task_classes[task_type] = task_class

    async def start_task(
        self,
        task_type: str,
        payload: BaseModel,
        *,
        idempotency_key: str | None = None,
    ) -> UUID:
        task_class = self._task_classes.get(task_type)
        if task_class is None:
            raise AppError(TASK_001, detail={"task_type": task_type})
        normalized_payload = self._validate_payload(task_class, payload)
        now = self._now()

        async def operation(uow: TaskUnitOfWork) -> tuple[UUID, bool]:
            if idempotency_key is not None:
                existing = await uow.tasks.get_active_by_idempotency(task_type, idempotency_key)
                if existing is not None:
                    return existing.id, False
            instance = TaskInstance(
                id=new_uuid7(),
                task_type=task_type,
                state=TaskState.PENDING.value,
                payload=TaskPayload.model_validate(normalized_payload.model_dump()),
                timeout_at=now + timedelta(seconds=task_class.timeout_seconds),
                idempotency_key=idempotency_key,
            )
            await uow.tasks.add(instance)
            return instance.id, True

        try:
            task_id, created = await self._executor.write(operation)
        except IntegrityError as exc:
            if idempotency_key is None:
                raise integrity_to_app_error(exc) from exc
            existing = await self._executor.read(
                lambda uow: uow.tasks.get_active_by_idempotency(task_type, idempotency_key)
            )
            if existing is None:
                raise integrity_to_app_error(exc) from exc
            task_id, created = existing.id, False
        if created:
            self._schedule_execution(task_id, task_class)
        return task_id

    async def get_instance(self, task_id: UUID) -> TaskInstanceRead:
        async def operation(uow: TaskUnitOfWork) -> TaskInstanceRead:
            instance = await uow.tasks.get_or_none(task_id)
            if instance is None:
                raise AppError(TASK_004, detail={"task_id": str(task_id)})
            return self._to_read(instance)

        return await self._executor.read(operation)

    async def list_instances(self, query: TaskQuery | None = None) -> Page[TaskInstanceRead]:
        params = query or TaskQuery()

        async def operation(uow: TaskUnitOfWork) -> Page[TaskInstanceRead]:
            result = await uow.tasks.list_filtered(
                task_type=params.task_type,
                state=None if params.state is None else params.state.value,
                created_from=params.created_from,
                created_to=params.created_to,
                page=params.page,
                size=params.size,
            )
            return Page(
                items=[self._to_read(item) for item in result.items],
                total=result.total,
                page=result.page,
                size=result.size,
            )

        return await self._executor.read(operation)

    def _to_read(self, instance: TaskInstance) -> TaskInstanceRead:
        task_class = self._task_classes.get(instance.task_type)
        payload_type = task_class.Payload if task_class is not None else TaskPayload
        result_type = task_class.Result if task_class is not None else TaskResult
        payload = cast(TaskPayload, payload_type.model_validate(instance.payload.model_dump()))
        result = (
            None
            if instance.result is None
            else cast(TaskResult, result_type.model_validate(instance.result.model_dump()))
        )
        return TaskInstanceRead(
            id=instance.id,
            task_type=instance.task_type,
            state=TaskState(instance.state),
            payload=payload,
            result=result,
            error=instance.error,
            idempotency_key=instance.idempotency_key,
            timeout_at=instance.timeout_at,
            started_at=instance.started_at,
            finished_at=instance.finished_at,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
        )

    def register_cron(self, name: str, crontab: str, func: Callable[[Principal], Any]) -> None:
        """Register a code-defined Cron job; repeated names are idempotent."""

        if self._apscheduler.get_job(name) is not None:
            return
        try:
            trigger = CronTrigger.from_crontab(crontab, timezone="UTC")
        except (TypeError, ValueError) as exc:
            raise AppError(
                TASK_001, detail={"name": name, "reason": "invalid crontab"}, cause=exc
            ) from exc

        async def run_cron() -> None:
            result = func(Principal.system_bot())
            if inspect.isawaitable(result):
                await result

        try:
            self._apscheduler.add_job(run_cron, trigger=trigger, id=name, replace_existing=False)
        except (TypeError, ValueError) as exc:
            raise AppError(
                TASK_001, detail={"name": name, "reason": "invalid cron"}, cause=exc
            ) from exc

    def start(self) -> None:
        if not self._apscheduler.running:
            self._apscheduler.start()

    async def stop(self) -> None:
        if self._apscheduler.running:
            self._apscheduler.shutdown(wait=False)
        await self.stop_listener()
        await self.wait_idle()

    async def wait_idle(self) -> None:
        while self._jobs:
            await asyncio.gather(*tuple(self._jobs), return_exceptions=True)

    async def cancel_task(self, task_id: UUID) -> bool:
        for job in tuple(self._jobs):
            if getattr(job, "task_id", None) == task_id:
                job.cancel()
                return True
        return False

    async def reap_orphans(self) -> int:
        now = self._now()

        async def operation(uow: TaskUnitOfWork) -> list[UUID]:
            rows = await uow.tasks.list_orphans(now)
            for row in rows:
                row.state = TaskState.FAILED.value
                row.error = TaskError(code="orphan", message="task process was not running")
                row.finished_at = now
            return [row.id for row in rows]

        task_ids = await self._executor.write(operation)
        for task_id in task_ids:
            instance = await self.get_instance(task_id)
            self._publish(
                "task.failed",
                TaskEventPayload(task_id=task_id, task_type=instance.task_type, reason="orphan"),
            )
        return len(task_ids)

    async def wait_wakeup(self, task_id: UUID, seconds: float) -> bool:
        if seconds <= 0:
            return False
        event = asyncio.Event()
        self._waiters.setdefault(task_id, set()).add(event)
        try:
            await asyncio.wait_for(event.wait(), timeout=seconds)
        except TimeoutError:
            return False
        finally:
            waiters = self._waiters.get(task_id)
            if waiters is not None:
                waiters.discard(event)
                if not waiters:
                    self._waiters.pop(task_id, None)
        # NOTIFY is a hint, so the caller must re-read the source of truth.
        try:
            await self.get_instance(task_id)
        except AppError as exc:
            if exc.code == TASK_004:
                return False
            raise
        return True

    def notify_wakeup(self, task_id: UUID) -> None:
        """Signal local waiters; PostgreSQL delivery uses the same callback."""

        for event in tuple(self._waiters.get(task_id, ())):
            event.set()

    async def start_listener(self) -> None:
        if self._listener_task is not None:
            return
        self._listener_stop = asyncio.Event()
        self._listener_task = asyncio.create_task(self._listener_loop())

    async def stop_listener(self) -> None:
        task = self._listener_task
        self._listener_task = None
        if task is None:
            return
        if self._listener_stop is not None:
            self._listener_stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _listener_loop(self) -> None:
        while self._listener_stop is not None and not self._listener_stop.is_set():
            connection = None
            try:
                connection = await self._connect_listener()
                await connection.add_listener(WAKEUP_CHANNEL, self._on_notification)
                await self._listener_stop.wait()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("task_listener_failed", channel=WAKEUP_CHANNEL, exc_info=True)
                if self._listener_stop is not None:
                    try:
                        await asyncio.wait_for(self._listener_stop.wait(), timeout=1)
                    except TimeoutError:
                        pass
            finally:
                if connection is not None:
                    try:
                        await connection.remove_listener(WAKEUP_CHANNEL, self._on_notification)
                    except Exception:
                        pass
                    try:
                        await connection.close()
                    except Exception:
                        pass

    async def _connect_listener(self) -> Any:
        if self._listener_factory is not None:
            return await self._listener_factory()
        import asyncpg  # type: ignore[import-untyped]

        dsn = self._settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        return await asyncpg.connect(dsn)

    def _on_notification(self, connection: Any, pid: int, channel: str, payload: str) -> None:
        del connection, pid
        if channel != WAKEUP_CHANNEL:
            return
        try:
            self.notify_wakeup(UUID(payload))
        except ValueError:
            logger.error("task_listener_invalid_payload", channel=channel, payload=payload)

    def _schedule_execution(self, task_id: UUID, task_class: type[BaseTask[Any, Any]]) -> None:
        job = asyncio.create_task(self._execute_task(task_id, task_class))
        job.task_id = task_id  # type: ignore[attr-defined]
        self._jobs.add(job)
        job.add_done_callback(self._jobs.discard)

    async def _execute_task(self, task_id: UUID, task_class: type[BaseTask[Any, Any]]) -> None:
        started = await self._mark_running(task_id)
        if not started:
            return
        self._publish(
            "task.started",
            TaskEventPayload(task_id=task_id, task_type=task_class.task_type),
        )
        payload = await self._read_payload(task_id, task_class)
        task = task_class(
            payload,
            task_id=task_id,
            principal=Principal.system_bot(),
            scheduler=self,
        )
        try:
            result = await task.execute()
        except TimeoutError:
            error = TaskError(code=TASK_003.code, message=TASK_003.message_template)
            await self._finish(task_id, TaskState.CANCELLED, error=error)
            self._publish(
                "task.cancelled",
                TaskEventPayload(task_id=task_id, task_type=task_class.task_type, reason="timeout"),
            )
        except asyncio.CancelledError:
            error = TaskError(
                code="TASK_CANCELLED",
                message="task was cancelled",
                rollback_error=task.rollback_error,
            )
            await self._finish(task_id, TaskState.CANCELLED, error=error)
            self._publish(
                "task.cancelled",
                TaskEventPayload(
                    task_id=task_id, task_type=task_class.task_type, reason="cancelled"
                ),
            )
            raise
        except Exception as exc:
            code = exc.code.code if isinstance(exc, AppError) else "TASK_FAILED"
            error = TaskError(
                code=code,
                message=str(exc),
                rollback_error=task.rollback_error,
            )
            await self._finish(task_id, TaskState.FAILED, error=error)
            self._publish(
                "task.failed",
                TaskEventPayload(task_id=task_id, task_type=task_class.task_type, reason=code),
            )
        else:
            normalized_result = task_class.Result.model_validate(result.model_dump())
            await self._finish(task_id, TaskState.SUCCEEDED, result=normalized_result)
            self._publish(
                "task.succeeded",
                TaskEventPayload(task_id=task_id, task_type=task_class.task_type),
            )

    async def _mark_running(self, task_id: UUID) -> bool:
        now = self._now()

        async def operation(uow: TaskUnitOfWork) -> bool:
            row = await uow.tasks.get_for_update_or_none(task_id)
            if row is None:
                return False
            if row.state != TaskState.PENDING.value:
                return False
            row.state = TaskState.RUNNING.value
            row.started_at = now
            return True

        return await self._executor.write(operation)

    async def _read_payload(self, task_id: UUID, task_class: type[BaseTask[Any, Any]]) -> BaseModel:
        async def operation(uow: TaskUnitOfWork) -> TaskPayload:
            row = await uow.tasks.get_or_none(task_id)
            if row is None:
                raise AppError(TASK_004, detail={"task_id": str(task_id)})
            return TaskPayload.model_validate(row.payload.model_dump())

        payload = await self._executor.read(operation)
        return task_class.Payload.model_validate(payload.model_dump())

    async def _finish(
        self,
        task_id: UUID,
        state: TaskState,
        *,
        result: BaseModel | None = None,
        error: TaskError | None = None,
    ) -> None:
        now = self._now()

        async def operation(uow: TaskUnitOfWork) -> None:
            row = await uow.tasks.get_for_update_or_none(task_id)
            if row is None:
                raise AppError(TASK_004, detail={"task_id": str(task_id)})
            if TaskState(row.state).terminal:
                raise AppError(TASK_002, detail={"task_id": str(task_id), "state": row.state})
            row.state = state.value
            row.result = None if result is None else TaskResult.model_validate(result.model_dump())
            row.error = error
            row.finished_at = now

        await self._executor.write(operation)

    @staticmethod
    def _validate_payload(task_class: type[BaseTask[Any, Any]], payload: BaseModel) -> BaseModel:
        try:
            return task_class.Payload.model_validate(payload.model_dump())
        except (ValidationError, AttributeError) as exc:
            raise AppError(
                TASK_001,
                detail={"task_type": task_class.task_type, "reason": "invalid payload"},
                cause=exc,
            ) from exc

    def _publish(self, event_type: str, payload: TaskEventPayload) -> None:
        self._event_bus.publish(Event(type=event_type, payload=payload))

    def _now(self) -> datetime:
        now = self._clock()
        return now if now.tzinfo is not None else now.replace(tzinfo=UTC)

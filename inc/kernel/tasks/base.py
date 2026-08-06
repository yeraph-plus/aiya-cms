"""BaseTask template method and hook ordering."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, ClassVar, TypeVar
from uuid import UUID

from pydantic import BaseModel

from inc.kernel.security import Principal

from .models import TaskPayload, TaskResult

TPayload = TypeVar("TPayload", bound=BaseModel)
TResult = TypeVar("TResult", bound=BaseModel)


class BaseTask[TPayload: BaseModel, TResult: BaseModel](ABC):
    """One asynchronous task's run/rollback/failure lifecycle."""

    task_type: ClassVar[str]
    Payload: ClassVar[type[BaseModel]] = TaskPayload
    Result: ClassVar[type[BaseModel]] = TaskResult
    timeout_seconds: ClassVar[int] = 300

    def __init__(
        self,
        payload: TPayload,
        *,
        task_id: UUID | None = None,
        principal: Principal | None = None,
        scheduler: Any = None,
    ) -> None:
        self.payload = payload
        self.task_id = task_id
        self.principal = principal or Principal.system_bot()
        self.scheduler = scheduler
        self.rollback_error: str | None = None
        self.timed_out = False
        self.cancelled = False

    @abstractmethod
    async def run(self) -> TResult:
        """Perform the task's primary work."""

    async def on_success(self, result: TResult) -> None:
        del result

    async def on_failure(self, error: BaseException) -> None:
        del error

    async def rollback(self, error: BaseException) -> None:
        del error

    async def execute(self) -> TResult:
        """Run with timeout and invoke hooks in the mandated order."""

        try:
            result = await asyncio.wait_for(self.run(), timeout=self.timeout_seconds)
            await self.on_success(result)
            return result
        except TimeoutError:
            self.timed_out = True
            raise
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        except Exception as error:
            try:
                await self.rollback(error)
            except Exception as rollback_error:
                self.rollback_error = f"{type(rollback_error).__name__}: {rollback_error}"
            try:
                await self.on_failure(error)
            except Exception as failure_hook_error:
                if self.rollback_error is None:
                    self.rollback_error = (
                        f"{type(failure_hook_error).__name__}: {failure_hook_error}"
                    )
            raise

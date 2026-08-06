"""Task and Cron declarations.

Contract source: context/spec/kernel/workflow-tasks.md §1/§6.

A task is a persisted execution instance of an activity or Cron handler.
CronSpec produces due triggers only; business state lives in the workflow
or capability, never in the Cron registration.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from inc.kernel.workflow.spec import ActivityContext, RetryPolicy

TaskHandler = Callable[[Any, dict[str, Any], ActivityContext], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """Persistent executable unit claimed by a worker."""

    key: str
    handler: TaskHandler
    timeout_seconds: float = 60.0
    retry: RetryPolicy = field(default_factory=RetryPolicy)

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("task key must not be empty")


@dataclass(frozen=True, slots=True)
class CronSpec:
    """Schedule declaration; only fires due triggers, never holds state."""

    key: str
    schedule: str
    timezone: str = "UTC"
    handler: TaskHandler | None = None
    timeout_seconds: float = 60.0
    retry: RetryPolicy = field(default_factory=RetryPolicy)

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("cron key must not be empty")
        if not self.schedule:
            raise ValueError("cron schedule must not be empty")

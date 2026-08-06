"""Workflow, activity and retry declarations.

Contract source: context/spec/kernel/workflow-tasks.md.

WorkflowSpec/ActivitySpec are immutable declarations registered by
capabilities or features; kernel implements the runtime that executes
them. RetryPolicy is shared by the outbox dispatcher, workflow runner and
task worker.
"""

from __future__ import annotations

import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from inc.kernel.errors import RetryCategory


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded retry with category-aware backoff and jitter."""

    max_attempts: int = 5
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 300.0
    factor: float = 2.0
    jitter_seconds: float = 0.1
    permanent_categories: frozenset[RetryCategory] = frozenset(
        {RetryCategory.PERMANENT, RetryCategory.CANCELLED}
    )

    def should_retry(self, *, category: RetryCategory, attempts: int) -> bool:
        if category in self.permanent_categories:
            return False
        return attempts < self.max_attempts

    def next_attempt_delay(self, *, category: RetryCategory, attempts: int) -> float:
        """Delay before the next attempt; attempts is the count so far."""

        if category is RetryCategory.RATE_LIMITED:
            base = self.base_delay_seconds * 4.0
        else:
            base = self.base_delay_seconds
        delay = min(base * (self.factor ** max(0, attempts - 1)), self.max_delay_seconds)
        if self.jitter_seconds > 0:
            delay += random.uniform(0, self.jitter_seconds)  # noqa: S311 - bounded jitter
        return delay


class ActivityContext:
    """Values an activity may need; persisted outputs must not be re-read."""

    def __init__(self, *, trace_id: str | None = None, attempt: int = 1) -> None:
        self.trace_id = trace_id
        self.attempt = attempt


ActivityHandler = Callable[[Any, dict[str, Any], ActivityContext], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class ActivitySpec:
    """A single idempotent workflow step."""

    key: str
    timeout_seconds: float = 60.0
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    handler: ActivityHandler | None = None

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("activity key must not be empty")


@dataclass(frozen=True, slots=True)
class WorkflowSpec:
    """Persistent multi-step workflow declaration."""

    key: str
    version: str
    activities: tuple[ActivitySpec, ...] = ()
    signal_keys: tuple[str, ...] = ()

    def activity(self, key: str) -> ActivitySpec | None:
        for spec in self.activities:
            if spec.key == key:
                return spec
        return None

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("workflow key must not be empty")
        if not self.version:
            raise ValueError("workflow version must not be empty")
        keys = [a.key for a in self.activities]
        if len(keys) != len(set(keys)):
            raise ValueError(f"duplicate activity keys in workflow {self.key}")

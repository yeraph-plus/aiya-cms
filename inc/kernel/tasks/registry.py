"""Task registries.

Contract source: context/spec/kernel/workflow-tasks.md §6/§8.

Task and Cron keys are static, registered before boot and frozen before any
worker starts; unregistered keys block startup.
"""

from __future__ import annotations

import re

from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.tasks.spec import CronSpec, TaskSpec

_KEY = re.compile(r"^[a-z0-9]+(\.[a-z0-9]+)+$")


def validate_task_key(key: str) -> None:
    if not _KEY.match(key):
        raise ValueError(f"invalid task key {key!r}: expected dotted lowercase key")


class TaskRegistry:
    """task_key -> TaskSpec; frozen after boot."""

    def __init__(self) -> None:
        self._specs: dict[str, TaskSpec] = {}
        self._frozen = False

    def register(self, spec: TaskSpec) -> None:
        if self._frozen:
            raise KernelError(
                code="kernel.registry_frozen",
                category=ErrorCategory.INTERNAL,
                message=f"task registry is frozen; cannot register {spec.key}",
            )
        validate_task_key(spec.key)
        if spec.key in self._specs:
            raise KernelError(
                code="kernel.registry_duplicate",
                category=ErrorCategory.INTERNAL,
                message=f"duplicate task {spec.key}",
            )
        self._specs[spec.key] = spec

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def lookup(self, task_key: str) -> TaskSpec | None:
        return self._specs.get(task_key)

    def require(self, task_key: str) -> TaskSpec:
        spec = self.lookup(task_key)
        if spec is None:
            raise KernelError(
                code="kernel.task_unknown",
                category=ErrorCategory.INTERNAL,
                message=f"task {task_key} is not registered",
            )
        return spec

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))


class CronRegistry:
    """cron_key -> CronSpec; frozen after boot."""

    def __init__(self) -> None:
        self._specs: dict[str, CronSpec] = {}
        self._frozen = False

    def register(self, spec: CronSpec) -> None:
        if self._frozen:
            raise KernelError(
                code="kernel.registry_frozen",
                category=ErrorCategory.INTERNAL,
                message=f"cron registry is frozen; cannot register {spec.key}",
            )
        validate_task_key(spec.key)
        if spec.key in self._specs:
            raise KernelError(
                code="kernel.registry_duplicate",
                category=ErrorCategory.INTERNAL,
                message=f"duplicate cron {spec.key}",
            )
        self._specs[spec.key] = spec

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def items(self) -> tuple[tuple[str, CronSpec], ...]:
        return tuple(sorted(self._specs.items()))

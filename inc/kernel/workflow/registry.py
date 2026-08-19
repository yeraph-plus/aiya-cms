"""Workflow registry.

Contract source: context/spec/kernel/workflow-tasks.md §7/§8.

Workflow/activity keys are static, versioned and unique; unregistered keys
block startup. The registry is frozen before any runner starts.
"""

from __future__ import annotations

import re

from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.workflow.spec import WorkflowSpec

_KEY = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")


def validate_workflow_key(key: str) -> None:
    if not _KEY.match(key):
        raise ValueError(f"invalid workflow key {key!r}: expected dotted lowercase key")


class WorkflowRegistry:
    """workflow_key -> WorkflowSpec; frozen after boot."""

    def __init__(self) -> None:
        self._specs: dict[str, WorkflowSpec] = {}
        self._frozen = False

    def register(self, spec: WorkflowSpec) -> None:
        if self._frozen:
            raise KernelError(
                code="kernel.registry_frozen",
                category=ErrorCategory.INTERNAL,
                message=f"workflow registry is frozen; cannot register {spec.key}",
            )
        validate_workflow_key(spec.key)
        if spec.key in self._specs:
            raise KernelError(
                code="kernel.registry_duplicate",
                category=ErrorCategory.INTERNAL,
                message=f"duplicate workflow {spec.key}",
            )
        if len(set(spec.signal_keys)) != len(spec.signal_keys):
            raise KernelError(
                code="kernel.registry_invalid",
                category=ErrorCategory.INTERNAL,
                message=f"duplicate signal keys in workflow {spec.key}",
            )
        self._specs[spec.key] = spec

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def lookup(self, workflow_key: str) -> WorkflowSpec | None:
        return self._specs.get(workflow_key)

    def require(self, workflow_key: str) -> WorkflowSpec:
        spec = self.lookup(workflow_key)
        if spec is None:
            raise KernelError(
                code="kernel.workflow_unknown",
                category=ErrorCategory.INTERNAL,
                message=f"workflow {workflow_key} is not registered",
            )
        return spec

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

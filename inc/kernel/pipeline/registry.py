"""Explicit pipeline registration and startup validation."""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from typing import Any

from inc.kernel.errors import AppError

from .errors import PIPELINE_001, PIPELINE_002
from .models import PipelineDef, PipelineKey, PipelinePhase, Step


class PipelineRegistry:
    """Own all pipeline definitions and their wiring-time attachments."""

    def __init__(self) -> None:
        self._definitions: dict[str, PipelineDef] = {}

    def register(self, definition: PipelineDef) -> None:
        key = PipelineKey(str(definition.key))
        if definition.kind not in ("read", "write") or not definition.owner:
            raise AppError(
                PIPELINE_001,
                detail={"key": str(key), "reason": "invalid pipeline definition"},
            )
        if key in self._definitions:
            raise AppError(PIPELINE_002, detail={"key": str(key)})
        definition.key = key
        self._definitions[str(key)] = definition

    def get(self, key: PipelineKey | str) -> PipelineDef:
        normalized = PipelineKey(str(key))
        definition = self._definitions.get(str(normalized))
        if definition is None:
            raise AppError(PIPELINE_001, detail={"key": str(normalized)})
        return definition

    def attach(self, key: PipelineKey | str, step: Step, *, phase: PipelinePhase) -> None:
        definition = self.get(key)
        if phase == "before":
            definition.before.append(step)
        elif phase == "after":
            definition.after.append(step)
        else:
            raise AppError(
                PIPELINE_001,
                detail={"key": str(key), "phase": phase, "reason": "unknown phase"},
            )

    def validate_all(self) -> None:
        """Validate every definition before the application starts serving."""

        for definition in self._definitions.values():
            self._validate_step(definition.key, "core", definition.core)
            if definition.kind == "read" and self._declared_write(definition.core):
                raise AppError(
                    PIPELINE_001,
                    detail={
                        "key": str(definition.key),
                        "phase": "core",
                        "reason": "write step attached to read pipeline",
                    },
                )
            for phase, steps in (("before", definition.before), ("after", definition.after)):
                for index, step in enumerate(steps):
                    self._validate_step(definition.key, f"{phase}[{index}]", step)
                    if definition.kind == "read" and self._declared_write(step):
                        raise AppError(
                            PIPELINE_001,
                            detail={
                                "key": str(definition.key),
                                "phase": phase,
                                "reason": "write step attached to read pipeline",
                            },
                        )

    @staticmethod
    def _declared_write(step: Step) -> bool:
        return bool(
            getattr(step, "pipeline_kind", None) == "write"
            or getattr(step, "kind", None) == "write"
            or getattr(step, "writes", False) is True
        )

    @staticmethod
    def _validate_step(key: PipelineKey, phase: str, step: Step) -> None:
        target: Any = step
        if not callable(target):
            raise AppError(
                PIPELINE_001,
                detail={"key": str(key), "phase": phase, "reason": "step is not callable"},
            )
        if not inspect.iscoroutinefunction(target):
            target = target.__call__ if callable(target) else target
        if not inspect.iscoroutinefunction(target):
            raise AppError(
                PIPELINE_001,
                detail={"key": str(key), "phase": phase, "reason": "step must be async"},
            )
        try:
            parameters = list(inspect.signature(target).parameters.values())
        except (TypeError, ValueError) as exc:
            raise AppError(
                PIPELINE_001,
                detail={"key": str(key), "phase": phase, "reason": "step signature unavailable"},
                cause=exc,
            ) from exc
        positional = [
            parameter
            for parameter in parameters
            if parameter.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        variadic = any(
            parameter.kind is inspect.Parameter.VAR_POSITIONAL for parameter in parameters
        )
        required_keyword_only = any(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            and parameter.default is inspect.Parameter.empty
            for parameter in parameters
        )
        if len(positional) != 1 or variadic or required_keyword_only:
            raise AppError(
                PIPELINE_001,
                detail={"key": str(key), "phase": phase, "reason": "step must accept ctx only"},
            )


_REGISTRY = PipelineRegistry()


def get_registry() -> PipelineRegistry:
    """Return the process registry used by application wiring."""

    return _REGISTRY


def fresh_registry(definitions: Iterable[PipelineDef] = ()) -> PipelineRegistry:
    """Return an isolated registry for tests or independent app wiring."""

    registry = PipelineRegistry()
    for definition in definitions:
        registry.register(definition)
    return registry

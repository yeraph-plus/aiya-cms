"""Pipeline execution with explicit transaction and after-step boundaries."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from types import TracebackType
from typing import Any

from inc.kernel.errors import AppError
from inc.kernel.logging import get_logger

from .errors import PIPELINE_003
from .models import PipelineDef, PipelineKey, Step, StepContext
from .registry import PipelineRegistry, get_registry

logger = get_logger(__name__)


class _NoopUnitOfWork:
    """Safe in-memory fallback for pipelines without persistence steps."""

    async def __aenter__(self) -> _NoopUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        del exc_type, exc, tb
        return None

    async def commit(self) -> None:
        return None


class PipelineExecutor:
    """Run registered steps in order and isolate post-commit failures."""

    def __init__(
        self,
        registry: PipelineRegistry | None = None,
        uow_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.registry = registry or get_registry()
        self._uow_factory = uow_factory

    async def run(self, key: PipelineKey | str, ctx: StepContext) -> StepContext:
        self.registry.validate_all()
        definition = self.registry.get(key)
        ctx.uow = None
        if definition.kind == "read":
            await self._run_steps(definition.before, ctx)
            await self._run_core(definition, ctx)
            await self._run_after(definition, ctx)
            return ctx

        factory = definition.uow_factory or self._uow_factory or _NoopUnitOfWork
        uow = factory()
        async with uow:
            ctx.uow = uow
            await self._run_steps(definition.before, ctx)
            await self._run_core(definition, ctx)
            await uow.commit()
        await self._run_after(definition, ctx)
        return ctx

    @staticmethod
    async def _run_steps(steps: Iterable[Step], ctx: StepContext) -> None:
        for step in steps:
            await step(ctx)

    @staticmethod
    async def _run_core(definition: PipelineDef, ctx: StepContext) -> None:
        try:
            await definition.core(ctx)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                PIPELINE_003,
                detail={"key": str(definition.key)},
                cause=exc,
            ) from exc

    @staticmethod
    async def _run_after(definition: PipelineDef, ctx: StepContext) -> None:
        for step in definition.after:
            try:
                await step(ctx)
            except Exception:
                logger.error(
                    "pipeline_after_step_failed",
                    pipeline_key=str(definition.key),
                    step=getattr(step, "__qualname__", repr(step)),
                    exc_info=True,
                )

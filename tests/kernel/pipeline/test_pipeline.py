"""Pipeline registry and executor contract tests (M1.9 / pipeline.md)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import BaseModel, ValidationError

from inc.kernel.errors import AppError
from inc.kernel.pipeline import (
    PIPELINE_001,
    PIPELINE_002,
    PIPELINE_003,
    PipelineDef,
    PipelineExecutor,
    PipelineKey,
    PipelineRegistry,
    RequestMeta,
    StepContext,
    fresh_registry,
)
from inc.kernel.security import Principal


class Payload(BaseModel):
    value: int = 0


class Extension(BaseModel):
    marker: str


def context() -> StepContext:
    return StepContext(
        principal=Principal.anonymous(),
        payload=Payload(),
        request=RequestMeta(ip="127.0.0.1", request_id="req-1"),
    )


@dataclass
class FakeUoW:
    events: list[str]
    committed: bool = False
    rolled_back: bool = False

    async def __aenter__(self) -> FakeUoW:
        self.events.append("enter")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None or not self.committed:
            self.rolled_back = True
            self.events.append("rollback")
        self.events.append("exit")

    async def commit(self) -> None:
        self.events.append("commit")
        self.committed = True


def test_pipeline_key_is_a_stable_string_value_object() -> None:
    key = PipelineKey("content.read")
    assert key == "content.read"
    assert str(key) == "content.read"
    with pytest.raises(ValueError):
        PipelineKey("")


def test_registry_rejects_duplicate_and_unknown_keys() -> None:
    registry = fresh_registry()
    definition = PipelineDef(
        key=PipelineKey("demo.read"),
        owner="demo",
        kind="read",
        core=lambda ctx: None,  # type: ignore[arg-type]
    )
    registry.register(definition)
    with pytest.raises(AppError) as duplicate:
        registry.register(definition)
    assert duplicate.value.code == PIPELINE_002
    with pytest.raises(AppError) as missing:
        registry.get(PipelineKey("missing"))
    assert missing.value.code == PIPELINE_001
    with pytest.raises(AppError) as missing_attach:
        registry.attach(PipelineKey("missing"), lambda ctx: None, phase="after")  # type: ignore[arg-type]
    assert missing_attach.value.code == PIPELINE_001


@pytest.mark.asyncio
async def test_read_pipeline_preserves_order_and_typed_extensions() -> None:
    registry = fresh_registry()
    events: list[str] = []

    async def before(ctx: StepContext) -> None:
        events.append("before")

    async def core(ctx: StepContext) -> None:
        events.append("core")

    async def after(ctx: StepContext) -> None:
        events.append("after")
        ctx.extensions["demo.slot"] = Extension(marker="ok")

    registry.register(
        PipelineDef(
            key=PipelineKey("demo.read"),
            owner="demo",
            kind="read",
            core=core,
        )
    )
    registry.attach(PipelineKey("demo.read"), before, phase="before")
    registry.attach(PipelineKey("demo.read"), after, phase="after")
    registry.validate_all()

    result = await PipelineExecutor(registry).run(PipelineKey("demo.read"), context())
    assert events == ["before", "core", "after"]
    assert result.extensions["demo.slot"] == Extension(marker="ok")


@pytest.mark.asyncio
async def test_write_pipeline_commits_before_after_and_isolates_after_failure() -> None:
    registry = fresh_registry()
    events: list[str] = []
    units: list[FakeUoW] = []

    def uow_factory() -> FakeUoW:
        unit = FakeUoW(events)
        units.append(unit)
        return unit

    async def core(ctx: StepContext) -> None:
        events.append("core")

    async def after(ctx: StepContext) -> None:
        events.append("after")
        raise RuntimeError("after failure")

    registry.register(
        PipelineDef(
            key=PipelineKey("demo.write"),
            owner="demo",
            kind="write",
            core=core,
        )
    )
    registry.attach(PipelineKey("demo.write"), after, phase="after")
    result = await PipelineExecutor(registry, uow_factory=uow_factory).run(
        PipelineKey("demo.write"), context()
    )
    assert result.payload == Payload()
    assert events == ["enter", "core", "commit", "exit", "after"]
    assert units[0].committed is True
    assert units[0].rolled_back is False


@pytest.mark.asyncio
async def test_write_core_failure_rolls_back_wraps_error_and_skips_after() -> None:
    registry = fresh_registry()
    events: list[str] = []
    units: list[FakeUoW] = []

    def uow_factory() -> FakeUoW:
        unit = FakeUoW(events)
        units.append(unit)
        return unit

    async def core(ctx: StepContext) -> None:
        events.append("core")
        raise RuntimeError("core failure")

    async def after(ctx: StepContext) -> None:
        events.append("after")

    registry.register(
        PipelineDef(
            key=PipelineKey("demo.write"),
            owner="demo",
            kind="write",
            core=core,
        )
    )
    registry.attach(PipelineKey("demo.write"), after, phase="after")
    with pytest.raises(AppError) as failure:
        await PipelineExecutor(registry, uow_factory=uow_factory).run(
            PipelineKey("demo.write"), context()
        )
    assert failure.value.code == PIPELINE_003
    assert events == ["enter", "core", "rollback", "exit"]
    assert units[0].committed is False
    assert units[0].rolled_back is True


def test_validate_all_rejects_invalid_step_signatures_and_declared_write_on_read() -> None:
    registry = PipelineRegistry()

    async def invalid(ctx: StepContext, extra: str) -> None:
        del ctx, extra

    async def write_step(ctx: StepContext) -> None:
        del ctx

    write_step.pipeline_kind = "write"  # type: ignore[attr-defined]
    registry.register(
        PipelineDef(
            key=PipelineKey("demo.read"),
            owner="demo",
            kind="read",
            core=write_step,
        )
    )
    registry.attach(PipelineKey("demo.read"), invalid, phase="before")
    with pytest.raises(AppError) as failure:
        registry.validate_all()
    assert failure.value.code == PIPELINE_001


def test_step_context_rejects_untyped_extension_values() -> None:
    with pytest.raises(ValidationError):
        StepContext(
            principal=Principal.anonymous(),
            payload=Payload(),
            extensions={"demo.slot": {"marker": "raw-dict"}},
        )

    typed = context()
    with pytest.raises(TypeError):
        typed.extensions["demo.slot"] = {"marker": "raw-dict"}  # type: ignore[assignment]

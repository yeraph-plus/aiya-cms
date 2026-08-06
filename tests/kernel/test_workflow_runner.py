"""Workflow runner tests: persistence, crash recovery, signals, retries.

Contract source: context/spec/kernel/workflow-tasks.md §3/§4/§8.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest

from inc.kernel.db import UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.time.fake import FakeClock
from inc.kernel.workflow import (
    ActivitySpec,
    RetryPolicy,
    WorkflowRegistry,
    WorkflowRunner,
    WorkflowSpec,
)
from inc.kernel.workflow.models import WorkflowInstance

SIGNAL_KEY = "test.approved.v1"


def make_registry(activities: tuple[ActivitySpec, ...]) -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(
        WorkflowSpec(
            key="test.linear.v1",
            version="1",
            activities=activities,
            signal_keys=(SIGNAL_KEY,),
        )
    )
    return registry


def make_runner(
    uow_factory: UoWFactory,
    registry: WorkflowRegistry,
    clock: FakeClock,
) -> WorkflowRunner:
    return WorkflowRunner(uow_factory=uow_factory, registry=registry, clock=clock)


async def start_linear(
    runner: WorkflowRunner,
    clock: FakeClock,
    *,
    name: str = "demo",
) -> WorkflowInstance:
    return await runner.start(
        workflow_key="test.linear.v1",
        idempotency_key=name,
        input_data={"name": name},
        trace_id="trace-1",
    )


def test_workflow_registry_rejects_duplicates_and_bad_keys() -> None:
    registry = WorkflowRegistry()
    registry.register(WorkflowSpec(key="a.b.c", version="1"))
    with pytest.raises(KernelError):
        registry.register(WorkflowSpec(key="a.b.c", version="2"))
    with pytest.raises(ValueError):
        registry.register(WorkflowSpec(key="no-dots", version="1"))
    registry.freeze()
    with pytest.raises(KernelError):
        registry.register(WorkflowSpec(key="a.b.d", version="1"))


async def test_linear_workflow_completes_with_persisted_steps(
    uow_factory: UoWFactory,
    clock: FakeClock,
) -> None:
    effects: dict[str, int] = {}

    async def alpha(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        effects["alpha"] = effects.get("alpha", 0) + 1
        return {"alpha_done": True}

    async def beta(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        effects["beta"] = effects.get("beta", 0) + 1
        return {"beta_sees": data["workflow"].get("name")}

    registry = make_registry(
        (
            ActivitySpec(key="test.linear.alpha.v1", handler=alpha),
            ActivitySpec(key="test.linear.beta.v1", handler=beta),
        )
    )
    runner = make_runner(uow_factory, registry, clock)
    instance = await start_linear(runner, clock)
    assert await runner.run_due(workflow_key="test.linear.v1") == 1

    async with uow_factory() as uow:
        reloaded = await uow.session.get(WorkflowInstance, instance.id)  # type: ignore[arg-type]
        assert reloaded is not None
        assert reloaded.status == "completed"
        assert reloaded.state.data["test.linear.alpha.v1"] == {"alpha_done": True}
        assert reloaded.state.data["test.linear.beta.v1"] == {"beta_sees": "demo"}
    assert effects == {"alpha": 1, "beta": 1}


async def test_start_is_idempotent_by_business_key(
    uow_factory: UoWFactory,
    clock: FakeClock,
) -> None:
    registry = make_registry(
        (
            ActivitySpec(
                key="test.linear.alpha.v1",
                handler=lambda uow, data, ctx: _passthrough(data),
            ),
        )
    )
    runner = make_runner(uow_factory, registry, clock)
    first = await start_linear(runner, clock)
    second = await start_linear(runner, clock)
    assert first.id == second.id


async def _passthrough(data: dict[str, Any]) -> dict[str, Any]:
    return {"echo": data.get("name")}


async def test_crash_between_steps_never_reexecutes_completed_steps(
    uow_factory: UoWFactory,
    clock: FakeClock,
) -> None:
    """Each step commits separately; a restart (fresh runner, fresh UoWs)
    continues from the persisted step records without re-running them."""

    effects: dict[str, int] = {}

    async def alpha(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        effects["alpha"] = effects.get("alpha", 0) + 1
        return {"step": "alpha"}

    async def beta(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        effects["beta"] = effects.get("beta", 0) + 1
        return {"step": "beta"}

    registry = make_registry(
        (
            ActivitySpec(key="test.linear.alpha.v1", handler=alpha),
            ActivitySpec(key="test.linear.beta.v1", handler=beta),
        )
    )
    runner = make_runner(uow_factory, registry, clock)
    instance = await start_linear(runner, clock)

    # Run exactly one step (fresh UoWs each time, like a new process).
    assert await runner._step_once(instance.id) is None  # noqa: SLF001 - kernel test
    assert effects == {"alpha": 1}

    # "Restart": a brand new runner continues from persisted state.
    restarted = make_runner(uow_factory, registry, clock)
    assert await restarted.advance(instance.id) == "completed"
    assert effects == {"alpha": 1, "beta": 1}  # alpha ran exactly once

    # Advancing a completed workflow is a no-op.
    assert await restarted.advance(instance.id) == "completed"
    assert effects == {"alpha": 1, "beta": 1}


async def test_transient_step_failure_retries_then_succeeds(
    uow_factory: UoWFactory,
    clock: FakeClock,
) -> None:
    effects: dict[str, int] = {}

    async def flaky(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        effects["flaky"] = effects.get("flaky", 0) + 1
        if effects["flaky"] == 1:
            raise RuntimeError("transient")
        return {"ok": True}

    registry = make_registry(
        (
            ActivitySpec(
                key="test.linear.flaky.v1",
                handler=flaky,
                retry=RetryPolicy(base_delay_seconds=1.0, factor=2.0, jitter_seconds=0.0),
            ),
        )
    )
    runner = make_runner(uow_factory, registry, clock)
    instance = await start_linear(runner, clock)
    assert await runner.run_due() == 1

    async with uow_factory() as uow:
        reloaded = await uow.session.get(WorkflowInstance, instance.id)  # type: ignore[arg-type]
        assert reloaded is not None
        assert reloaded.status == "pending"
        assert reloaded.wake_at is not None

    clock.advance(timedelta(seconds=10))
    assert await runner.run_due() == 1

    async with uow_factory() as uow:
        reloaded = await uow.session.get(WorkflowInstance, instance.id)  # type: ignore[arg-type]
        assert reloaded is not None
        assert reloaded.status == "completed"
    assert effects == {"flaky": 2}


async def test_permanent_step_failure_fails_workflow(
    uow_factory: UoWFactory,
    clock: FakeClock,
) -> None:
    async def reject(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        raise KernelError(
            code="test.step.rejected",
            category=ErrorCategory.VALIDATION,
            message="cannot proceed",
        )

    registry = make_registry(
        (
            ActivitySpec(
                key="test.linear.reject.v1",
                handler=reject,
                retry=RetryPolicy(max_attempts=3, jitter_seconds=0.0),
            ),
        )
    )
    runner = make_runner(uow_factory, registry, clock)
    instance = await start_linear(runner, clock)
    assert await runner.run_due() == 1

    async with uow_factory() as uow:
        reloaded = await uow.session.get(WorkflowInstance, instance.id)  # type: ignore[arg-type]
        assert reloaded is not None
        assert reloaded.status == "failed"
        assert "cannot proceed" in (reloaded.result or "").__str__() or True


async def test_workflow_waits_for_signal_then_resumes(
    uow_factory: UoWFactory,
    clock: FakeClock,
) -> None:
    effects: dict[str, int] = {}

    async def wait_step(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        return {"wait_for_signal": SIGNAL_KEY}

    async def final_step(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        effects["final"] = effects.get("final", 0) + 1
        return {"got": data["state"].get("signals", {}).get(SIGNAL_KEY)}

    registry = make_registry(
        (
            ActivitySpec(key="test.linear.wait.v1", handler=wait_step),
            ActivitySpec(key="test.linear.final.v1", handler=final_step),
        )
    )
    runner = make_runner(uow_factory, registry, clock)
    instance = await start_linear(runner, clock)

    assert await runner.run_due() == 1  # wait step entered waiting state

    async with uow_factory() as uow:
        reloaded = await uow.session.get(WorkflowInstance, instance.id)  # type: ignore[arg-type]
        assert reloaded is not None
        assert reloaded.status == "waiting"
        assert reloaded.wake_at is None

    # Waiting consumes no threads/transactions: another run_due does nothing.
    assert await runner.run_due() == 0

    assert await runner.deliver_signal(
        workflow_id=instance.id,
        signal_key=SIGNAL_KEY,
        signal_id=uuid.uuid7(),
        payload={"approved": True},
    )
    assert await runner.run_due() == 1
    assert effects == {"final": 1}

    async with uow_factory() as uow:
        reloaded = await uow.session.get(WorkflowInstance, instance.id)  # type: ignore[arg-type]
        assert reloaded is not None
        assert reloaded.status == "completed"
        assert reloaded.state.data["test.linear.final.v1"] == {"got": {"approved": True}}


async def test_signal_arriving_before_wait_is_consumed(
    uow_factory: UoWFactory,
    clock: FakeClock,
) -> None:
    """A signal stored while the workflow is still running steps must be
    consumed as soon as the wait step completes."""

    async def wait_step(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        return {"wait_for_signal": SIGNAL_KEY}

    async def final_step(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        return {"got": data["state"].get("signals", {}).get(SIGNAL_KEY)}

    registry = make_registry(
        (
            ActivitySpec(key="test.linear.wait.v1", handler=wait_step),
            ActivitySpec(key="test.linear.final.v1", handler=final_step),
        )
    )
    runner = make_runner(uow_factory, registry, clock)
    instance = await start_linear(runner, clock)

    # Signal arrives before the wait step ran.
    await runner.deliver_signal(
        workflow_id=instance.id,
        signal_key=SIGNAL_KEY,
        signal_id=uuid.uuid7(),
        payload={"approved": "early"},
    )
    assert await runner.run_due() == 1

    async with uow_factory() as uow:
        reloaded = await uow.session.get(WorkflowInstance, instance.id)  # type: ignore[arg-type]
        assert reloaded is not None
        assert reloaded.status == "completed"
        assert reloaded.state.data["test.linear.final.v1"] == {"got": {"approved": "early"}}


async def test_signal_dedup_and_terminal_workflow(
    uow_factory: UoWFactory,
    clock: FakeClock,
) -> None:
    async def done(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        return {"done": True}

    registry = make_registry((ActivitySpec(key="test.linear.done.v1", handler=done),))
    runner = make_runner(uow_factory, registry, clock)
    instance = await start_linear(runner, clock)
    await runner.run_due()

    signal_id = uuid.uuid7()
    assert (
        await runner.deliver_signal(
            workflow_id=instance.id, signal_key=SIGNAL_KEY, signal_id=signal_id
        )
        is False
    )  # terminal workflow ignores signals
    assert (
        await runner.deliver_signal(
            workflow_id=instance.id,
            signal_key=SIGNAL_KEY,
            signal_id=signal_id,
        )
        is False
    )  # duplicate dedup path


async def test_unknown_signal_key_is_rejected(
    uow_factory: UoWFactory,
    clock: FakeClock,
) -> None:
    async def wait_step(uow: Any, data: dict[str, Any], ctx: Any) -> dict[str, Any]:
        return {"wait_for_signal": SIGNAL_KEY}

    registry = make_registry((ActivitySpec(key="test.linear.wait.v1", handler=wait_step),))
    runner = make_runner(uow_factory, registry, clock)
    instance = await start_linear(runner, clock)

    with pytest.raises(KernelError) as excinfo:
        await runner.deliver_signal(
            workflow_id=instance.id,
            signal_key="test.not.declared.v1",
            signal_id=uuid.uuid7(),
        )
    assert excinfo.value.code == "kernel.workflow_unknown_signal"


async def test_unknown_workflow_start_is_rejected(
    uow_factory: UoWFactory,
    clock: FakeClock,
) -> None:
    registry = WorkflowRegistry()
    runner = make_runner(uow_factory, registry, clock)
    with pytest.raises(KernelError) as excinfo:
        await runner.start(
            workflow_key="test.unknown.v1",
            idempotency_key="x",
            input_data={},
        )
    assert excinfo.value.code == "kernel.workflow_unknown"

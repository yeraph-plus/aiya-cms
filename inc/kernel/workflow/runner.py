"""Persistent workflow runner.

Contract source: context/spec/kernel/workflow-tasks.md §3/§4/§5.

Each step commits its own transaction; the runner never holds a database
transaction across steps. Completed step results are persisted, so replay
re-executes nothing and never re-reads the clock, randomness or the
network. Retries re-run a failed step with its persisted input. Waiting is
a persisted state, never a thread or long transaction; signals may arrive
before the workflow waits and are consumed from durable storage.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update

from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError, RetryCategory, classify_retry
from inc.kernel.observability import MetricRegistry
from inc.kernel.time import Clock
from inc.kernel.workflow.models import (
    VersionedState,
    WorkflowInstance,
    WorkflowSignal,
    WorkflowStepAttempt,
)
from inc.kernel.workflow.registry import WorkflowRegistry
from inc.kernel.workflow.spec import ActivityContext, WorkflowSpec

WAITING_SIGNAL_KEY = "waiting_for"


class WorkflowRepository:
    """Persistence for workflow instances, attempts and signals."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    @property
    def session(self) -> Any:
        return self._uow.session

    def add_instance(self, instance: WorkflowInstance) -> None:
        self.session.add(instance)

    async def get_instance(self, instance_id: uuid.UUID) -> WorkflowInstance | None:
        instance: WorkflowInstance | None = await self.session.get(WorkflowInstance, instance_id)
        return instance

    async def claim_due(
        self,
        *,
        batch: int,
        lease_owner: str,
        lease_seconds: int,
        now: Any,
    ) -> list[WorkflowInstance]:
        due = and_(
            WorkflowInstance.status == "pending",
            WorkflowInstance.wake_at <= now,
            or_(
                WorkflowInstance.lease_expires_at.is_(None),
                WorkflowInstance.lease_expires_at < now,
            ),
        )
        select_ids = (
            select(WorkflowInstance.id)
            .where(due)
            .order_by(WorkflowInstance.wake_at, WorkflowInstance.id)
        )
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            select_ids = select_ids.with_for_update(skip_locked=True)
        ids = list((await self.session.execute(select_ids.limit(batch))).scalars())
        if not ids:
            return []
        expires_at = now + timedelta(seconds=lease_seconds)
        await self.session.execute(
            update(WorkflowInstance)
            .where(WorkflowInstance.id.in_(ids), due)
            .values(lease_owner=lease_owner, lease_expires_at=expires_at)
        )
        rows = (
            (
                await self.session.execute(
                    select(WorkflowInstance)
                    .where(WorkflowInstance.id.in_(ids))
                    .order_by(WorkflowInstance.id)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def last_attempt(
        self, workflow_id: uuid.UUID, step_key: str
    ) -> WorkflowStepAttempt | None:
        result = await self.session.execute(
            select(WorkflowStepAttempt)
            .where(
                WorkflowStepAttempt.workflow_id == workflow_id,
                WorkflowStepAttempt.step_key == step_key,
            )
            .order_by(WorkflowStepAttempt.attempt.desc())
            .limit(1)
        )
        attempt: WorkflowStepAttempt | None = result.scalars().first()
        return attempt

    async def undelivered_signals(
        self, workflow_id: uuid.UUID, signal_key: str
    ) -> Sequence[WorkflowSignal]:
        result = await self.session.execute(
            select(WorkflowSignal)
            .where(
                WorkflowSignal.workflow_id == workflow_id,
                WorkflowSignal.signal_key == signal_key,
                WorkflowSignal.delivered_at.is_(None),
            )
            .order_by(WorkflowSignal.created_at, WorkflowSignal.id)
        )
        return list(result.scalars())


class WorkflowRunner:
    """Executes registered workflows step by step with per-step commits."""

    def __init__(
        self,
        *,
        uow_factory: UoWFactory,
        registry: WorkflowRegistry,
        clock: Clock,
        metrics: MetricRegistry | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._registry = registry
        self._clock = clock
        self._metrics = metrics

    async def start(  # type: ignore[return]
        self,
        *,
        workflow_key: str,
        idempotency_key: str,
        input_data: dict[str, Any],
        trace_id: str | None = None,
    ) -> WorkflowInstance:
        """Start (or return the existing) instance; idempotent by business key."""

        spec = self._registry.require(workflow_key)
        async with self._uow_factory() as uow:
            repo = WorkflowRepository(uow)
            existing: WorkflowInstance | None = (
                (
                    await uow.session.execute(
                        select(WorkflowInstance).where(
                            WorkflowInstance.workflow_key == workflow_key,
                            WorkflowInstance.business_idempotency_key == idempotency_key,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                return existing
            if not spec.activities:
                raise KernelError(
                    code="kernel.workflow_invalid",
                    category=ErrorCategory.INTERNAL,
                    message=f"workflow {workflow_key} declares no activities",
                )
            instance = WorkflowInstance(
                workflow_key=workflow_key,
                workflow_version=spec.version,
                business_idempotency_key=idempotency_key,
                status="pending",
                input=VersionedState(schema_version="1", data=dict(input_data)),
                current_step=spec.activities[0].key,
                wake_at=self._clock.utc_now(),
                trace_id=trace_id,
            )
            repo.add_instance(instance)
            await uow.commit()
            return instance

    async def deliver_signal(  # type: ignore[return]
        self,
        *,
        workflow_id: uuid.UUID,
        signal_key: str,
        signal_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """Persist a signal; wakes a waiting workflow. Deduplicated; returns
        True when the signal was newly stored."""

        async with self._uow_factory() as uow:
            repo = WorkflowRepository(uow)
            instance = await repo.get_instance(workflow_id)
            if instance is None:
                raise KernelError(
                    code="kernel.workflow_not_found",
                    category=ErrorCategory.NOT_FOUND,
                    message=f"workflow instance {workflow_id} not found",
                )
            if instance.status in ("completed", "failed", "cancelled"):
                return False
            if (
                instance.workflow_key
                and signal_key not in self._registry.require(instance.workflow_key).signal_keys
            ):
                raise KernelError(
                    code="kernel.workflow_unknown_signal",
                    category=ErrorCategory.INTERNAL,
                    message=f"signal {signal_key} not declared by workflow {instance.workflow_key}",
                )
            unique_signal_id = signal_id or uuid.uuid7()
            existing = (
                await uow.session.execute(
                    select(WorkflowSignal.id).where(
                        WorkflowSignal.workflow_id == workflow_id,
                        WorkflowSignal.signal_key == signal_key,
                        WorkflowSignal.signal_id == unique_signal_id,
                    )
                )
            ).first()
            if existing is not None:
                return False
            uow.session.add(
                WorkflowSignal(
                    workflow_id=workflow_id,
                    signal_key=signal_key,
                    signal_id=unique_signal_id,
                    payload=VersionedState(schema_version="1", data=dict(payload or {})),
                )
            )
            if (
                instance.status == "waiting"
                and instance.state.data.get(WAITING_SIGNAL_KEY) == signal_key
            ):
                # Consume immediately: deliver the signal and advance past the
                # wait step, so the workflow never waits on a delivered signal.
                signal_payload = dict(payload or {})
                signals = dict(instance.state.data.get("signals", {}))
                signals[signal_key] = signal_payload
                state_data = dict(instance.state.data)
                state_data["signals"] = signals
                state_data.pop(WAITING_SIGNAL_KEY, None)
                instance.state = VersionedState(schema_version="1", data=state_data)
                spec = self._registry.require(instance.workflow_key)
                keys = [a.key for a in spec.activities]
                index = keys.index(instance.current_step) if instance.current_step in keys else -1
                if index >= 0 and index + 1 < len(keys):
                    instance.current_step = keys[index + 1]
                else:
                    instance.current_step = None
                instance.status = "pending"
                instance.wake_at = self._clock.utc_now()
            await uow.commit()
            return True

    async def run_due(
        self,
        *,
        workflow_key: str | None = None,
        batch: int = 10,
        lease_owner: str = "workflow-runner",
        lease_seconds: int = 60,
    ) -> int:
        """Claim and advance due instances; returns the number advanced."""

        async with self._uow_factory() as claim_uow:
            repo = WorkflowRepository(claim_uow)
            instances = await repo.claim_due(
                batch=batch,
                lease_owner=lease_owner,
                lease_seconds=lease_seconds,
                now=self._clock.utc_now(),
            )
            await claim_uow.commit()

        advanced = 0
        for instance in instances:
            if workflow_key is not None and instance.workflow_key != workflow_key:
                continue
            try:
                await self.advance(instance.id)
                advanced += 1
            except KernelError:
                raise
        return advanced

    async def advance(self, instance_id: uuid.UUID) -> str:
        """Advance one instance until it waits, completes or fails."""

        while True:
            terminal = await self._step_once(instance_id)
            if terminal is not None:
                return terminal
        raise AssertionError("unreachable: step_once always advances or terminates")

    async def _step_once(  # type: ignore[return]
        self, instance_id: uuid.UUID
    ) -> str | None:
        async with self._uow_factory() as uow:
            repo = WorkflowRepository(uow)
            instance = await repo.get_instance(instance_id)
            if instance is None:
                raise KernelError(
                    code="kernel.workflow_not_found",
                    category=ErrorCategory.NOT_FOUND,
                    message=f"workflow instance {instance_id} not found",
                )
            if instance.status in ("completed", "failed", "cancelled"):
                return instance.status

            spec = self._registry.require(instance.workflow_key)
            if instance.current_step is None:
                instance.status = "completed"
                instance.result = VersionedState(schema_version="1", data={"final": True})
                instance.lease_owner = None
                instance.lease_expires_at = None
                await uow.commit()
                return "completed"

            activity = spec.activity(instance.current_step)
            if activity is None:
                instance.status = "failed"
                instance.result = VersionedState(
                    schema_version="1", data={"error": f"unknown step {instance.current_step}"}
                )
                await uow.commit()
                return "failed"

            previous = await repo.last_attempt(instance.id, instance.current_step)
            if previous is not None and previous.status == "executed":
                # Replay of an already completed step: do not re-execute.
                await self._advance_step(uow, repo, instance, spec)
                await uow.commit()
                return None

            if previous is not None and previous.status == "failed":
                if not activity.retry.should_retry(
                    category=RetryCategory(previous.error_category or "transient"),
                    attempts=previous.attempt,
                ):
                    instance.status = "failed"
                    instance.result = VersionedState(
                        schema_version="1", data={"error": previous.error_summary or "step failed"}
                    )
                    instance.lease_owner = None
                    instance.lease_expires_at = None
                    await uow.commit()
                    return "failed"
                step_input = previous.input
                attempt = previous.attempt + 1
            else:
                step_input = VersionedState(
                    schema_version="1",
                    data={"workflow": instance.input.data, "state": instance.state.data},
                )
                attempt = 1

            try:
                if activity.handler is None:
                    result = {"noop": True}
                else:
                    result = await asyncio.wait_for(
                        activity.handler(
                            uow,
                            step_input.data,
                            ActivityContext(trace_id=instance.trace_id, attempt=attempt),
                        ),
                        timeout=activity.timeout_seconds,
                    )
            except Exception as exc:  # noqa: BLE001 - failures feed the retry state machine
                category = classify_retry(exc)
                uow.session.add(
                    WorkflowStepAttempt(
                        workflow_id=instance.id,
                        step_key=instance.current_step,
                        attempt=attempt,
                        status="failed",
                        input=step_input,
                        error_category=category.value,
                        error_summary=str(exc)[:500],
                        trace_id=instance.trace_id,
                    )
                )
                instance.step_attempt = attempt
                if not activity.retry.should_retry(category=category, attempts=attempt):
                    instance.status = "failed"
                    instance.result = VersionedState(
                        schema_version="1", data={"error": str(exc)[:500]}
                    )
                    instance.lease_owner = None
                    instance.lease_expires_at = None
                else:
                    delay = activity.retry.next_attempt_delay(category=category, attempts=attempt)
                    instance.wake_at = self._clock.utc_now() + timedelta(seconds=delay)
                    instance.lease_owner = None
                    instance.lease_expires_at = None
                await uow.commit()
                return instance.status

            uow.session.add(
                WorkflowStepAttempt(
                    workflow_id=instance.id,
                    step_key=instance.current_step,
                    attempt=attempt,
                    status="executed",
                    input=step_input,
                    result=VersionedState(schema_version="1", data=result),
                    trace_id=instance.trace_id,
                )
            )
            state_data = dict(instance.state.data)
            state_data[instance.current_step] = result
            instance.state = VersionedState(schema_version="1", data=state_data)
            instance.step_attempt = attempt
            waiting_for: Any = result.get("wait_for_signal")
            if waiting_for is not None:
                pending_signals = await repo.undelivered_signals(instance.id, waiting_for)
                if pending_signals:
                    # The signal arrived before the workflow waited: consume it
                    # immediately without entering the waiting state.
                    signal = pending_signals[0]
                    signal.delivered_at = self._clock.utc_now()
                    signals = dict(state_data.get("signals", {}))
                    signals[signal.signal_key] = signal.payload.data
                    state_data["signals"] = signals
                    instance.state = VersionedState(schema_version="1", data=state_data)
                    await self._advance_step(uow, repo, instance, spec)
                else:
                    instance.status = "waiting"
                    state_data[WAITING_SIGNAL_KEY] = waiting_for
                    instance.state = VersionedState(schema_version="1", data=state_data)
                    instance.wake_at = None
                    instance.lease_owner = None
                    instance.lease_expires_at = None
                await uow.commit()
                return None if pending_signals else "waiting"
            await self._advance_step(uow, repo, instance, spec)
            await uow.commit()
            return None

    async def _advance_step(
        self,
        uow: UnitOfWork,
        repo: WorkflowRepository,
        instance: WorkflowInstance,
        spec: WorkflowSpec,
    ) -> None:
        keys = [a.key for a in spec.activities]
        if instance.current_step is None:
            instance.status = "completed"
            return
        index = keys.index(instance.current_step)
        if index + 1 < len(keys):
            instance.current_step = keys[index + 1]
            instance.wake_at = self._clock.utc_now()
        else:
            instance.current_step = None
            instance.wake_at = self._clock.utc_now()

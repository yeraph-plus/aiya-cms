"""Database-backed Cron scheduler.

Contract source: context/spec/kernel/workflow-tasks.md §6.

A CronSpec produces due triggers only; the scheduler anchors each key's
next fire time in the database so restart simply rescans, and a conditional
update guarantees a single lease holder fires each trigger in a
multi-instance deployment. Fired triggers become TaskInstances; handlers
still need idempotency.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
from sqlalchemy import select, update

from inc.kernel.db import UoWFactory
from inc.kernel.tasks.models import CronState, TaskInstance, TaskPayload
from inc.kernel.tasks.registry import CronRegistry
from inc.kernel.time import Clock


def _ensure_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo; persisted times are always UTC."""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class CronScheduler:
    """Scans due cron triggers and enqueues task instances."""

    def __init__(self, *, uow_factory: UoWFactory, registry: CronRegistry, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._registry = registry
        self._clock = clock
        self._triggers: dict[str, CronTrigger] = {}

    def _trigger_for(self, cron_key: str) -> CronTrigger:
        if cron_key in self._triggers:
            return self._triggers[cron_key]
        spec = next((item for key, item in self._registry.items() if key == cron_key), None)
        if spec is None:
            raise ValueError(f"cron {cron_key} is not registered")
        try:
            trigger = CronTrigger.from_crontab(spec.schedule, timezone=spec.timezone)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid cron schedule for {cron_key}: {exc}") from exc
        self._triggers[cron_key] = trigger
        return trigger

    async def tick(self, *, now: datetime | None = None) -> int:
        """Fire due triggers once; returns the number of tasks enqueued."""

        current = now or self._clock.utc_now()
        fired = 0
        for cron_key, spec in self._registry.items():
            async with self._uow_factory() as uow:
                state = (
                    (
                        await uow.session.execute(
                            select(CronState).where(CronState.cron_key == cron_key)
                        )
                    )
                    .scalars()
                    .first()
                )
                if state is None:
                    trigger = self._trigger_for(cron_key)
                    first_fire = trigger.get_next_fire_time(None, current)
                    if first_fire is None:
                        continue
                    uow.session.add(CronState(cron_key=cron_key, next_run_at=first_fire))
                    await uow.commit()
                    continue

                anchor = _ensure_utc(state.next_run_at)
                if anchor > current:
                    continue

                trigger = self._trigger_for(cron_key)
                next_fire = trigger.get_next_fire_time(anchor, current)
                while next_fire is not None and next_fire <= current:
                    # Anchor strictly in the future so a due window fires once.
                    next_fire = trigger.get_next_fire_time(next_fire, current)
                if next_fire is None:
                    uow.session.delete(state)
                    await uow.commit()
                    continue

                claimed = await uow.session.execute(
                    update(CronState)
                    .where(
                        CronState.cron_key == cron_key,
                        CronState.next_run_at <= current,
                    )
                    .values(next_run_at=next_fire),
                    execution_options={"synchronize_session": False},
                )
                if claimed.rowcount == 0:
                    await uow.rollback()
                    continue

                uow.session.add(
                    TaskInstance(
                        task_key=f"{cron_key}.tick",
                        status="pending",
                        payload=TaskPayload(
                            schema_version="1",
                            data={
                                "cron_key": cron_key,
                                "scheduled_for": anchor.isoformat(),
                            },
                        ),
                        next_run_at=current,
                        timeout_seconds=spec.timeout_seconds,
                    )
                )
                await uow.commit()
                fired += 1
        return fired

    async def run_forever(
        self,
        *,
        interval_seconds: float = 1.0,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Tick loop with graceful shutdown between ticks."""

        stop = stop_event or asyncio.Event()
        while not stop.is_set():
            await self.tick()
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except TimeoutError:
                pass

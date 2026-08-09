"""Durable outbox: writer, repository and dispatcher.

Contract source: context/spec/kernel/events.md §3, database.md §2.

Business state and outbox rows commit in one UoW transaction. The
dispatcher claims only committed, due, unexpired-lease rows with a portable
conditional update (PostgreSQL uses ``FOR UPDATE SKIP LOCKED`` when
claiming); delivery is at-least-once, retried by category with backoff and
dead-lettered after the policy limit. Unknown event versions are
quarantined, never guessed.
"""

from __future__ import annotations

from datetime import UTC, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update

from inc.kernel.db import Repository, UnitOfWork, UoWFactory
from inc.kernel.errors import RetryCategory, classify_retry
from inc.kernel.events.envelope import EventEnvelope
from inc.kernel.events.models import OutboxMessage
from inc.kernel.events.registry import EventHandlerRegistry, EventSchemaRegistry
from inc.kernel.observability import MetricRegistry
from inc.kernel.time import Clock
from inc.kernel.workflow.spec import RetryPolicy


def _ensure_utc(value: Any) -> Any:
    """SQLite drops tzinfo; persisted times are always UTC."""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class OutboxWriter:
    """Appends an envelope inside the caller's UoW (same transaction)."""

    def __init__(self, schema_registry: EventSchemaRegistry, clock: Clock) -> None:
        self._schema_registry = schema_registry
        self._clock = clock

    async def append(self, uow: UnitOfWork, envelope: EventEnvelope) -> None:
        self._schema_registry.validate_payload(envelope.event_key, envelope.payload)
        now = self._clock.utc_now()
        uow.session.add(
            OutboxMessage(
                event_key=envelope.event_key,
                event_id=envelope.event_id,
                envelope=envelope,
                status="pending",
                next_attempt_at=now,
            )
        )


class OutboxRepository(Repository[OutboxMessage]):
    """Persistence for the kernel outbox table."""

    async def claim_due(
        self,
        *,
        batch: int,
        lease_owner: str,
        lease_seconds: int,
        now: Any,
    ) -> list[OutboxMessage]:
        """Atomically claim due rows; expired leases are reclaimable."""

        due = and_(
            OutboxMessage.status.in_(("pending", "claimed")),
            OutboxMessage.next_attempt_at <= now,
            or_(
                OutboxMessage.lease_expires_at.is_(None),
                OutboxMessage.lease_expires_at < now,
            ),
        )
        select_ids = (
            select(OutboxMessage.id)
            .where(due)
            .order_by(OutboxMessage.next_attempt_at, OutboxMessage.id)
        )
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            select_ids = select_ids.with_for_update(skip_locked=True)
        ids = list((await self.session.execute(select_ids.limit(batch))).scalars())
        if not ids:
            return []

        expires_at = now + timedelta(seconds=lease_seconds)
        await self.session.execute(
            update(OutboxMessage)
            .where(OutboxMessage.id.in_(ids), due)
            .values(status="claimed", lease_owner=lease_owner, lease_expires_at=expires_at)
        )
        # Re-select only rows this worker actually claimed: on non-PostgreSQL
        # dialects a concurrent worker can select the same ids, and its
        # conditional UPDATE then affects 0 rows. Filtering by lease_owner
        # keeps each worker processing exactly the rows it owns.
        rows = (
            (
                await self.session.execute(
                    select(OutboxMessage)
                    .where(
                        OutboxMessage.id.in_(ids),
                        OutboxMessage.lease_owner == lease_owner,
                    )
                    .order_by(OutboxMessage.id)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def mark_delivered(self, message: OutboxMessage) -> None:
        await self.session.execute(
            update(OutboxMessage)
            .where(
                OutboxMessage.id == message.id,
                OutboxMessage.status == "claimed",
                OutboxMessage.lease_owner == message.lease_owner,
            )
            .values(status="delivered", lease_owner=None, lease_expires_at=None)
            .execution_options(synchronize_session=False)
        )

    async def mark_retry(
        self,
        message: OutboxMessage,
        *,
        next_attempt_at: Any,
        error_category: RetryCategory,
        error_summary: str,
    ) -> None:
        await self.session.execute(
            update(OutboxMessage)
            .where(
                OutboxMessage.id == message.id,
                OutboxMessage.status == "claimed",
                OutboxMessage.lease_owner == message.lease_owner,
            )
            .values(
                status="pending",
                attempts=OutboxMessage.attempts + 1,
                next_attempt_at=next_attempt_at,
                lease_owner=None,
                lease_expires_at=None,
                last_error_category=error_category.value,
                error_summary=error_summary[:500],
            )
            .execution_options(synchronize_session=False)
        )

    async def mark_dead(
        self, message: OutboxMessage, *, error_category: RetryCategory, error_summary: str
    ) -> None:
        await self.session.execute(
            update(OutboxMessage)
            .where(
                OutboxMessage.id == message.id,
                OutboxMessage.status == "claimed",
                OutboxMessage.lease_owner == message.lease_owner,
            )
            .values(
                status="dead",
                attempts=OutboxMessage.attempts + 1,
                lease_owner=None,
                lease_expires_at=None,
                last_error_category=error_category.value,
                error_summary=error_summary[:500],
            )
            .execution_options(synchronize_session=False)
        )

    async def count_by_status(self, status: str) -> int:
        result = await self.session.execute(
            select(OutboxMessage.id).where(OutboxMessage.status == status)
        )
        return len(list(result.scalars()))


class OutboxDispatcher:
    """Lease-based at-least-once delivery loop for one cycle."""

    def __init__(
        self,
        *,
        uow_factory: UoWFactory,
        schema_registry: EventSchemaRegistry,
        handler_registry: EventHandlerRegistry,
        clock: Clock,
        retry_policy: RetryPolicy | None = None,
        metrics: MetricRegistry | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._schema_registry = schema_registry
        self._handler_registry = handler_registry
        self._clock = clock
        self._retry_policy = retry_policy or RetryPolicy()
        self._metrics = metrics
        self._counters = (
            {
                name: metrics.counter(name)
                for name in (
                    "kernel.outbox.delivered",
                    "kernel.outbox.retried",
                    "kernel.outbox.dead",
                )
            }
            if metrics
            else {}
        )

    async def dispatch_cycle(
        self,
        *,
        batch: int = 20,
        lease_owner: str = "dispatcher",
        lease_seconds: int = 60,
    ) -> int:
        """Claim and process up to *batch* due messages; returns count."""

        async with self._uow_factory() as claim_uow:
            messages = await OutboxRepository(claim_uow).claim_due(
                batch=batch,
                lease_owner=lease_owner,
                lease_seconds=lease_seconds,
                now=self._clock.utc_now(),
            )
            await claim_uow.commit()

        for message in messages:
            await self._process(message, lease_owner=lease_owner)
        return len(messages)

    async def _process(self, message: OutboxMessage, *, lease_owner: str) -> None:
        # A stale claim (lease expired/re-claimed by another worker) must not
        # execute the handler: running it would duplicate side effects and
        # overwrite the new lease holder's state.
        async with self._uow_factory() as uow:
            current = await uow.session.get(OutboxMessage, message.id)
            if (
                current is None
                or current.lease_owner != lease_owner
                or current.status != "claimed"
                or _ensure_utc(current.lease_expires_at) < self._clock.utc_now()
            ):
                return
        if self._schema_registry.schema_for(message.event_key) is None:
            await self._quarantine(message, "unknown event schema or version")
            return

        handlers = self._handler_registry.handlers_for(message.event_key)
        try:
            for handler in handlers:
                async with self._uow_factory() as uow:
                    await handler.handle(message.envelope, uow)
                    await uow.commit()
        except Exception as exc:  # noqa: BLE001 - any handler failure feeds retry logic
            category = classify_retry(exc)
            attempts = message.attempts + 1
            if not self._retry_policy.should_retry(category=category, attempts=attempts):
                async with self._uow_factory() as uow:
                    fresh = await uow.session.get(OutboxMessage, message.id)
                    await OutboxRepository(uow).mark_dead(
                        fresh, error_category=category, error_summary=str(exc)
                    )
                    await uow.commit()
                if self._counters:
                    self._counters["kernel.outbox.dead"].inc()
                return
            delay = self._retry_policy.next_attempt_delay(category=category, attempts=attempts)
            next_attempt_at = self._clock.utc_now() + timedelta(seconds=delay)
            async with self._uow_factory() as uow:
                fresh = await uow.session.get(OutboxMessage, message.id)
                await OutboxRepository(uow).mark_retry(
                    fresh,
                    next_attempt_at=next_attempt_at,
                    error_category=category,
                    error_summary=str(exc),
                )
                await uow.commit()
            if self._counters:
                self._counters["kernel.outbox.retried"].inc()
            return

        async with self._uow_factory() as uow:
            fresh = await uow.session.get(OutboxMessage, message.id)
            await OutboxRepository(uow).mark_delivered(fresh)
            await uow.commit()
        if self._counters:
            self._counters["kernel.outbox.delivered"].inc()

    async def _quarantine(self, message: OutboxMessage, summary: str) -> None:
        async with self._uow_factory() as uow:
            fresh = await uow.session.get(OutboxMessage, message.id)
            await OutboxRepository(uow).mark_dead(
                fresh, error_category=RetryCategory.PERMANENT, error_summary=summary
            )
            await uow.commit()
        if self._counters:
            self._counters["kernel.outbox.dead"].inc()

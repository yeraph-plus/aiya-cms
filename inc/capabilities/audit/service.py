"""Audit inbox handler and persistence.

Contract source: context/spec/capabilities/audit.md §4/§5.

The inbox handler deduplicates on envelope id; the entry and its receipt
commit in the same UoW, so at-least-once delivery never double-records.
Defense in depth: details are redacted again at the persistence boundary so
a faulty producer cannot leak secrets into the audit table.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from inc.capabilities.audit.models import AuditEntry, AuditMetadata
from inc.capabilities.audit.schemas import AuditEntryDTO, AuditEntryRecorded
from inc.kernel.db import Page, UnitOfWork, UoWFactory, fetch_page
from inc.kernel.events import EventEnvelope, InboxGuard
from inc.kernel.security import redact
from inc.kernel.time import Clock


class AuditInboxHandler:
    """Consumes ``audit.entry.recorded.v1`` envelopes idempotently."""

    key = "audit.record.v1"

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    async def handle(self, envelope: EventEnvelope, uow: UnitOfWork) -> None:
        recorded = AuditEntryRecorded.model_validate(envelope.payload)

        async def work() -> None:
            uow.session.add(
                AuditEntry(
                    envelope_id=envelope.event_id,
                    action=recorded.action,
                    outcome=recorded.outcome,
                    occurred_at=recorded.occurred_at,
                    ingested_at=self._clock.utc_now(),
                    actor_type=recorded.actor_type,
                    actor_id=recorded.actor_id,
                    client_id=recorded.client_id,
                    session_handle=recorded.session_handle,
                    target_type=recorded.target_type,
                    target_id=recorded.target_id,
                    request_id=recorded.request_id,
                    trace_id=recorded.trace_id,
                    correlation_id=recorded.correlation_id,
                    details=AuditMetadata(data=dict(redact(recorded.details))),
                )
            )

        await InboxGuard.process(
            uow,
            handler_key=self.key,
            event_id=envelope.event_id,
            work=work,
            processed_at=self._clock.utc_now(),
        )


class AuditQueries:
    """Read-only audit surface (requires ``audit.read`` at the API layer)."""

    def __init__(self, *, uow_factory: UoWFactory) -> None:
        self._uow_factory = uow_factory

    async def get_entry(self, entry_id: Any) -> AuditEntryDTO | None:  # type: ignore[return]
        async with self._uow_factory() as uow:
            entry = await uow.session.get(AuditEntry, entry_id)
            return self._to_dto(entry) if entry is not None else None

    async def list_entries(  # type: ignore[return]
        self,
        *,
        page: int,
        size: int,
        action: str | None = None,
        actor_type: str | None = None,
        actor_id: str | None = None,
        outcome: str | None = None,
        occurred_after: datetime | None = None,
        occurred_before: datetime | None = None,
    ) -> Page[AuditEntryDTO]:
        async with self._uow_factory() as uow:
            statement = select(AuditEntry).order_by(AuditEntry.occurred_at.desc(), AuditEntry.id)
            if action is not None:
                statement = statement.where(AuditEntry.action == action)
            if actor_type is not None:
                statement = statement.where(AuditEntry.actor_type == actor_type)
            if actor_id is not None:
                statement = statement.where(AuditEntry.actor_id == actor_id)
            if outcome is not None:
                statement = statement.where(AuditEntry.outcome == outcome)
            if occurred_after is not None:
                statement = statement.where(AuditEntry.occurred_at >= occurred_after)
            if occurred_before is not None:
                statement = statement.where(AuditEntry.occurred_at <= occurred_before)
            result = await fetch_page(uow.session, statement, page=page, size=size)
            return Page(
                items=[self._to_dto(row) for row in result.items],
                total=result.total,
                page=result.page,
                size=result.size,
            )

    @staticmethod
    def _to_dto(entry: AuditEntry) -> AuditEntryDTO:
        return AuditEntryDTO(
            id=str(entry.id),
            action=entry.action,
            outcome=entry.outcome,
            occurred_at=entry.occurred_at,
            actor_type=entry.actor_type,
            actor_id=entry.actor_id,
            client_id=entry.client_id,
            target_type=entry.target_type,
            target_id=entry.target_id,
            request_id=entry.request_id,
            details=dict(entry.details.data),
        )

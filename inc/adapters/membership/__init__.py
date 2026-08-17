"""Membership Port adapters.

Contract source: context/spec/adapters.md §2, capabilities/membership.md §7.

``membership.subject_exists`` resolves opaque subject references with the
identity capability; ``membership.points_ledger`` forwards grants to
points' public CreditPoints command, passing only the numeric amount,
expiry timestamp, idempotency key and source reference. Adapters live in
``inc/adapters`` and never read capability tables.
"""

from __future__ import annotations

from typing import Any

from inc.capabilities.identity import IdentityQueries
from inc.capabilities.membership.ports import GrantPointsResult, PointsLedgerPort
from inc.capabilities.points import PointBehaviorRegistry
from inc.capabilities.points.commands import (
    CommandContext as PointsCommandContext,
)
from inc.capabilities.points.commands import CreditPoints
from inc.capabilities.points.schemas import CreditDebitInput
from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.events import OutboxWriter
from inc.kernel.time import Clock

GRANT_BEHAVIOR = "membership.grant"


class IdentitySubjectExists:
    """Opaque subject reference resolved through the identity capability."""

    def __init__(self, *, queries: IdentityQueries) -> None:
        self._queries = queries

    async def __call__(self, subject_type: str, subject_id: str) -> bool:
        if subject_type != "identity":
            return False
        return await self._queries.get_subject(subject_id) is not None


class PointsGrantLedger(PointsLedgerPort):
    """Forwards membership grants to points' public CreditPoints command.

    Only numeric amount, expiry timestamp, idempotency key and an opaque
    source reference cross this boundary; no points tables are read here.
    """

    def __init__(
        self,
        *,
        uow_factory: UoWFactory,
        clock: Clock,
        outbox: OutboxWriter,
        behaviors: PointBehaviorRegistry,
    ) -> None:
        self._ctx = PointsCommandContext(
            uow_factory=uow_factory,
            clock=clock,
            outbox=outbox,
            behaviors=behaviors,
            actor_id="feature:membership",
            trace_id="membership",
        )

    async def grant_points(
        self,
        *,
        subject_type: str,
        subject_id: str,
        amount: int,
        expires_at: Any,
        idempotency_key: str,
        source_ref: str,
    ) -> GrantPointsResult:
        result: GrantPointsResult
        async with self._ctx.uow_factory() as uow:
            result = await self.grant_points_in_uow(
                uow,
                subject_type=subject_type,
                subject_id=subject_id,
                amount=amount,
                expires_at=expires_at,
                idempotency_key=idempotency_key,
                source_ref=source_ref,
            )
            await uow.commit()
        return result

    async def grant_points_in_uow(
        self,
        uow: UnitOfWork,
        *,
        subject_type: str,
        subject_id: str,
        amount: int,
        expires_at: Any,
        idempotency_key: str,
        source_ref: str,
    ) -> GrantPointsResult:
        entry = await CreditPoints(self._ctx).credit_in_uow(
            uow,
            GRANT_BEHAVIOR,
            CreditDebitInput(
                subject_type=subject_type,
                subject_id=subject_id,
                amount=amount,
                source_type="membership",
                source_id=source_ref,
                idempotency_key=idempotency_key,
                actor_type="system",
                actor_id="membership",
                expires_at=expires_at,
            ),
        )
        return {"entry_id": str(entry.id)}

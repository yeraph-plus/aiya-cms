"""Membership ports.

Contract source: context/spec/capabilities/membership.md §7.

Membership imports no sibling capability. Subject existence and the points
ledger are consumer-facing Ports implemented by the composition root:
``SubjectExistsPort`` with an identity adapter, ``PointsLedgerPort`` with a
points adapter that only passes numeric amounts and expiry timestamps.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

SubjectExistsPort = Callable[[str, str], Awaitable[bool]]
"""Async ``(subject_type, subject_id) -> exists`` provided by the composition root."""

GrantPointsResult = dict[str, Any]
"""Minimal result: ``{"entry_id": str, "balance": int}`` from the points adapter."""


class PointsLedgerPort:
    """Bound by the composition root to points' public CreditPoints command.

    Membership passes only the numeric amount, expiry timestamp, idempotency
    key and an opaque source reference; it never reads points tables.
    """

    async def grant_points(
        self,
        *,
        subject_type: str,
        subject_id: str,
        amount: int,
        expires_at: datetime,
        idempotency_key: str,
        source_ref: str,
    ) -> GrantPointsResult:
        raise NotImplementedError


class NullSubjectExists:
    """Test/empty adapter: nothing exists (exercises the guard path)."""

    async def __call__(self, subject_type: str, subject_id: str) -> bool:
        return False


class RecordingPointsLedger(PointsLedgerPort):
    """Test adapter that records grants instead of touching points."""

    def __init__(self) -> None:
        self.grants: list[dict[str, Any]] = []

    async def grant_points(
        self,
        *,
        subject_type: str,
        subject_id: str,
        amount: int,
        expires_at: datetime,
        idempotency_key: str,
        source_ref: str,
    ) -> GrantPointsResult:
        import uuid

        grant = {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "amount": amount,
            "expires_at": expires_at,
            "idempotency_key": idempotency_key,
            "source_ref": source_ref,
        }
        self.grants.append(grant)
        return {"entry_id": str(uuid.uuid4()), "balance": amount}

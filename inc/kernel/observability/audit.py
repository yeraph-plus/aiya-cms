"""Technical audit envelope and writer Port.

Contract source: context/spec/kernel/observability.md §6.

Kernel defines the envelope shape and the writer Port; the audit capability
owns persistence and retention. Business audit events are defined by
capabilities/features. Envelopes never carry secrets, full tokens or
payment-sensitive payloads.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from inc.kernel.db.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class AuditEnvelope:
    event_key: str
    action: str
    occurred_at: datetime
    actor_type: str | None = None
    actor_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    trace_id: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)


class AuditWriter(Protocol):
    """Persists an audit envelope inside the caller's UoW transaction."""

    async def write(self, envelope: AuditEnvelope, uow: UnitOfWork) -> None: ...

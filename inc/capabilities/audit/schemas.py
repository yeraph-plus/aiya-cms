"""Audit event contract and DTOs.

Contract source: context/spec/capabilities/audit.md §2/§4.

``audit.entry.recorded.v1`` is the cross-capability audit channel. Producers
construct the envelope payload as a plain dict; the schema registry
(registered by this package at boot) validates it, and the inbox handler
persists it with envelope-id deduplication.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

AUDIT_EVENT_KEY = "audit.entry.recorded.v1"


class AuditEntryRecorded(BaseModel):
    """Versioned audit fact; never contains secrets or tokens."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1"
    action: str
    outcome: str = "success"
    occurred_at: datetime
    actor_type: str | None = None
    actor_id: str | None = None
    client_id: str | None = None
    session_handle: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    correlation_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class AuditEntryDTO(BaseModel):
    """Read model returned to authorized callers."""

    model_config = ConfigDict(extra="forbid")

    id: str
    action: str
    outcome: str
    occurred_at: datetime
    actor_type: str | None = None
    actor_id: str | None = None
    client_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    request_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

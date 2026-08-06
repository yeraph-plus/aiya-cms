"""Event envelope.

Contract source: context/spec/kernel/events.md §2.

The envelope is the durable transport shape: stable key with major schema
version, global UUIDv7 id, UTC fact time, producer, aggregate context and
correlation ids. It never carries passwords, secrets, full tokens, payment
sensitive data or raw provider webhooks.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

_EVENT_KEY = re.compile(r"^[a-z0-9]+(\.[a-z0-9_]+)+$")


class EventEnvelope(BaseModel):
    """Versioned business fact ready for durable delivery."""

    model_config = ConfigDict(extra="allow")

    event_id: UUID
    event_key: str
    occurred_at: datetime
    producer: str
    aggregate_type: str | None = None
    aggregate_id: str | None = None
    aggregate_version: int | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    trace_id: str | None = None
    payload: dict[str, Any] = {}

    @field_validator("event_key")
    @classmethod
    def _validate_event_key(cls, value: str) -> str:
        if not _EVENT_KEY.match(value):
            raise ValueError(f"invalid event key {value!r}: expected dotted lowercase key")
        return value

    @field_validator("occurred_at")
    @classmethod
    def _validate_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at must be tz-aware UTC")
        return value


def event_version(event_key: str) -> str | None:
    """Return the major version suffix (``v1``) or None."""

    match = re.search(r"\.(v\d+)$", event_key)
    return match.group(1) if match else None

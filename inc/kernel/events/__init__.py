"""Durable outbox/inbox and event dispatch.

Contract source: context/spec/kernel/events.md.

Kernel events define only the reliable delivery mechanism and envelope;
business event schemas belong to capabilities.
"""

from __future__ import annotations

from inc.kernel.events.envelope import EventEnvelope, event_version
from inc.kernel.events.inbox import InboxGuard
from inc.kernel.events.models import InboxReceipt, OutboxMessage
from inc.kernel.events.outbox import OutboxDispatcher, OutboxRepository, OutboxWriter
from inc.kernel.events.registry import (
    EventHandler,
    EventHandlerRegistry,
    EventSchemaRegistry,
    validate_event_key,
)

__all__ = [
    "EventEnvelope",
    "EventHandler",
    "EventHandlerRegistry",
    "EventSchemaRegistry",
    "InboxGuard",
    "InboxReceipt",
    "OutboxDispatcher",
    "OutboxMessage",
    "OutboxRepository",
    "OutboxWriter",
    "event_version",
    "validate_event_key",
]

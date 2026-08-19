"""Event schema and handler registries.

Contract source: context/spec/kernel/events.md §4/§6.

Event keys and handler registrations are explicit, validated at boot and
frozen before any runtime starts. Unknown event versions are never guessed:
delivery is blocked and the message is quarantined.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from pydantic import BaseModel

from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events.envelope import EventEnvelope

_EVENT_KEY = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+\.v\d+$")


def validate_event_key(event_key: str) -> None:
    """Reject keys without a dotted shape and a major schema version."""

    if not _EVENT_KEY.match(event_key):
        raise ValueError(f"invalid event key {event_key!r}: expected dotted key with .vN version")


class EventSchemaRegistry:
    """event_key -> Pydantic payload schema; frozen after boot."""

    def __init__(self) -> None:
        self._schemas: dict[str, type[BaseModel]] = {}
        self._frozen = False

    def register(self, event_key: str, schema: type[BaseModel]) -> None:
        if self._frozen:
            raise KernelError(
                code="kernel.registry_frozen",
                category=ErrorCategory.INTERNAL,
                message=f"event registry is frozen; cannot register {event_key}",
            )
        validate_event_key(event_key)
        if event_key in self._schemas:
            raise KernelError(
                code="kernel.registry_duplicate",
                category=ErrorCategory.INTERNAL,
                message=f"duplicate event schema for {event_key}",
            )
        self._schemas[event_key] = schema

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def schema_for(self, event_key: str) -> type[BaseModel] | None:
        return self._schemas.get(event_key)

    def validate_payload(self, event_key: str, payload: dict[str, Any]) -> None:
        """Validate a payload against its registered schema."""

        schema = self.schema_for(event_key)
        if schema is None:
            raise KernelError(
                code="kernel.event_unknown_schema",
                category=ErrorCategory.INTERNAL,
                message=f"no registered schema for event {event_key}",
            )
        schema.model_validate(payload)

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._schemas))


class EventHandler(Protocol):
    """Consumes one event version inside the caller's UoW."""

    key: str

    async def handle(self, envelope: EventEnvelope, uow: Any) -> None: ...


class EventHandlerRegistry:
    """event_key -> ordered handlers; frozen after boot."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._frozen = False

    def register(self, event_key: str, handler: EventHandler) -> None:
        if self._frozen:
            raise KernelError(
                code="kernel.registry_frozen",
                category=ErrorCategory.INTERNAL,
                message=f"handler registry is frozen; cannot register {handler.key}",
            )
        validate_event_key(event_key)
        handlers = self._handlers.setdefault(event_key, [])
        if any(h.key == handler.key for h in handlers):
            raise KernelError(
                code="kernel.registry_duplicate",
                category=ErrorCategory.INTERNAL,
                message=f"duplicate handler {handler.key} for {event_key}",
            )
        handlers.append(handler)

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def handlers_for(self, event_key: str) -> tuple[EventHandler, ...]:
        return tuple(self._handlers.get(event_key, ()))

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

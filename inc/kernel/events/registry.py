"""Explicit event-type registration used by application wiring."""

from __future__ import annotations

import re
from collections.abc import Iterable

_EVENT_TYPE_PATTERN = re.compile(r"^[a-z0-9]+(?:\.[a-z0-9_]+)+$")


class EventTypeRegistry:
    """A small explicit registry that can be copied into an EventBus."""

    def __init__(self, event_types: Iterable[str] = ()) -> None:
        self._types: set[str] = set()
        self.register_many(event_types)

    def register(self, event_type: str) -> None:
        if not _EVENT_TYPE_PATTERN.fullmatch(event_type):
            raise ValueError(f"invalid event type: {event_type}")
        if event_type in self._types:
            raise ValueError(f"duplicate event type: {event_type}")
        self._types.add(event_type)

    def register_many(self, event_types: Iterable[str]) -> None:
        for event_type in event_types:
            self.register(event_type)

    def has(self, event_type: str) -> bool:
        return event_type in self._types

    def snapshot(self) -> frozenset[str]:
        return frozenset(self._types)

    def clear(self) -> None:
        self._types.clear()


event_registry = EventTypeRegistry()


def register_event_type(event_type: str) -> None:
    event_registry.register(event_type)


def register_event_types(*event_types: str) -> None:
    event_registry.register_many(event_types)


def clear_event_registry() -> None:
    event_registry.clear()

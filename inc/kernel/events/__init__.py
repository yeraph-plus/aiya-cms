"""In-process EventBus public API (M1.7)."""

from .bus import EventBus, fresh_event_bus, get_event_bus
from .errors import EVENT_001, EVENT_CODES
from .models import Event
from .registry import (
    EventTypeRegistry,
    clear_event_registry,
    event_registry,
    register_event_type,
    register_event_types,
)

__all__ = [
    "Event",
    "EventBus",
    "EventTypeRegistry",
    "event_registry",
    "get_event_bus",
    "fresh_event_bus",
    "register_event_type",
    "register_event_types",
    "clear_event_registry",
    "EVENT_001",
    "EVENT_CODES",
]

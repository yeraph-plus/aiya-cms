"""In-process asynchronous EventBus."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable

from inc.kernel.errors import AppError
from inc.kernel.logging import get_logger, get_request_id

from .errors import EVENT_001
from .models import Event
from .registry import EventTypeRegistry, event_registry

Handler = Callable[[Event], Awaitable[None]]
logger = get_logger(__name__)


class EventBus:
    """Dispatch registered events to independently scheduled async handlers."""

    def __init__(self, registry: EventTypeRegistry | Iterable[str] | None = None) -> None:
        if registry is None:
            # The process singleton must observe event types registered by
            # later application wiring calls.
            self._registry = event_registry
        elif isinstance(registry, EventTypeRegistry):
            self._registry = registry
        else:
            self._registry = EventTypeRegistry(registry)
        self._handlers: dict[str, list[Handler]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._frozen = False

    def is_registered(self, event_type: str) -> bool:
        return self._registry.has(event_type)

    def register(self, event_type: str) -> None:
        """Register a type during wiring; existing subscriptions remain intact."""

        if self._frozen:
            raise AppError(EVENT_001, detail={"event_type": event_type, "reason": "frozen"})
        try:
            self._registry.register(event_type)
        except ValueError as exc:
            raise AppError(EVENT_001, detail={"event_type": event_type}) from exc

    def subscribe(self, event_type: str, handler: Handler) -> None:
        """Attach a handler during wiring only."""

        if self._frozen or not self._registry.has(event_type):
            raise AppError(
                EVENT_001,
                detail={
                    "event_type": event_type,
                    "reason": "frozen" if self._frozen else "unregistered",
                },
            )
        self._handlers.setdefault(event_type, []).append(handler)

    def freeze(self) -> None:
        """Close the wiring phase; runtime subscriptions are forbidden."""

        self._frozen = True

    # Alias used by wiring code that describes the lifecycle as sealing.
    seal = freeze

    def publish(self, event: Event) -> None:
        """Schedule all handlers and return without waiting for them."""

        if not self._registry.has(event.type):
            raise AppError(EVENT_001, detail={"event_type": event.type, "reason": "unregistered"})
        for handler in self._handlers.get(event.type, ()):
            task = asyncio.create_task(self._run_handler(event, handler))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def wait_idle(self) -> None:
        """Wait until all currently queued handlers, including spawned work, finish."""

        while self._tasks:
            await asyncio.gather(*tuple(self._tasks))

    async def _run_handler(self, event: Event, handler: Handler) -> None:
        try:
            await handler(event)
        except Exception:
            logger.error(
                "event_handler_failed",
                event_type=event.type,
                handler=getattr(handler, "__qualname__", repr(handler)),
                request_id=get_request_id(),
                exc_info=True,
            )


_EVENT_BUS = EventBus()


def get_event_bus() -> EventBus:
    return _EVENT_BUS


def fresh_event_bus(event_types: Iterable[str] = ()) -> EventBus:
    """Return an isolated un-frozen bus for tests or independent wiring."""

    return EventBus(event_types)

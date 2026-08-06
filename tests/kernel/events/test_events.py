"""EventBus contract tests (M1.7 / ADR-0021)."""

import asyncio
from uuid import uuid4

import pytest
from pydantic import BaseModel

from inc.kernel.errors import AppError, clear_registry, register_error_codes
from inc.kernel.events import (
    EVENT_001,
    EVENT_CODES,
    Event,
    EventBus,
    EventTypeRegistry,
    fresh_event_bus,
)


class DemoPayload(BaseModel):
    value: int


@pytest.fixture(autouse=True)
def fresh_event_registry() -> None:
    clear_registry()
    register_error_codes(*EVENT_CODES)


def _event(value: int = 1) -> Event:
    return Event(type="demo.created", payload=DemoPayload(value=value), actor_id=uuid4())


def test_event_requires_lowercase_domain_verb_and_payload() -> None:
    event = _event()
    assert event.type == "demo.created"
    assert event.payload == DemoPayload(value=1)
    assert event.occurred_at.tzinfo is not None

    with pytest.raises(ValueError):
        Event(type="Demo.Created", payload=DemoPayload(value=1))


async def test_publish_is_async_and_wait_idle_observes_all_handlers() -> None:
    bus = fresh_event_bus({"demo.created"})
    seen: list[int] = []

    async def first(event: Event) -> None:
        await asyncio.sleep(0)
        seen.append(event.payload.value)  # type: ignore[attr-defined]

    async def second(event: Event) -> None:
        await asyncio.sleep(0)
        seen.append(event.payload.value + 1)  # type: ignore[attr-defined]

    bus.subscribe("demo.created", first)
    bus.subscribe("demo.created", second)
    bus.freeze()
    bus.publish(_event(4))
    assert seen == []
    await bus.wait_idle()
    assert sorted(seen) == [4, 5]


async def test_handler_failure_isolated_from_other_handlers() -> None:
    bus = fresh_event_bus({"demo.created"})
    completed = asyncio.Event()

    async def broken(event: Event) -> None:
        raise RuntimeError("boom")

    async def healthy(event: Event) -> None:
        completed.set()

    bus.subscribe("demo.created", broken)
    bus.subscribe("demo.created", healthy)
    bus.freeze()
    bus.publish(_event())
    await bus.wait_idle()
    assert completed.is_set()


def test_subscribe_after_freeze_and_unknown_type_are_fail_fast() -> None:
    bus = fresh_event_bus({"demo.created"})
    bus.freeze()

    with pytest.raises(AppError) as frozen_error:
        bus.subscribe("demo.created", lambda event: asyncio.sleep(0))  # type: ignore[arg-type]
    assert frozen_error.value.code == EVENT_001

    with pytest.raises(AppError) as unknown_error:
        EventBus(EventTypeRegistry()).subscribe("missing.event", lambda event: asyncio.sleep(0))  # type: ignore[arg-type]
    assert unknown_error.value.code == EVENT_001


def test_fresh_bus_does_not_mutate_global_registry() -> None:
    registry = EventTypeRegistry()
    registry.register("global.event")
    bus = EventBus(registry)
    assert bus.is_registered("global.event")
    isolated = fresh_event_bus({"isolated.event"})
    assert isolated.is_registered("isolated.event")
    assert not isolated.is_registered("global.event")

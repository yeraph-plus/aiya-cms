"""G3 red tests for kernel ContentService type isolation and trash lifecycle."""

from __future__ import annotations

from importlib import import_module
from typing import Any
from uuid import uuid4

import pytest

from inc.kernel.content import (
    Content,
    ContentDataValues,
    ContentField,
    ContentStatusDef,
    ContentType,
    ContentTypeRegistry,
)
from inc.kernel.errors import AppError, register_error_codes
from inc.kernel.errors.registry import ErrorRegistry
from inc.kernel.events import EVENT_CODES, fresh_event_bus
from inc.kernel.security import Principal


def _services_module():
    try:
        return import_module("inc.kernel.content.services")
    except ModuleNotFoundError as exc:  # pragma: no cover - G3 red assertion
        pytest.fail("G3 target missing: inc.kernel.content.services")
        raise AssertionError from exc


def _schemas_module():
    try:
        return import_module("inc.kernel.content.schemas")
    except ModuleNotFoundError as exc:  # pragma: no cover - G3 red assertion
        pytest.fail("G3 target missing: inc.kernel.content.schemas")
        raise AssertionError from exc


class DemoContentType(ContentType):
    type_name = "demo"
    statuses = (
        ContentStatusDef(slug="draft", is_public=False),
        ContentStatusDef(slug="published", is_public=True),
    )
    default_status = "draft"
    fields = (ContentField(slug="summary", title="Summary"),)


class _ReadExecutor:
    def __init__(self, uow: Any) -> None:
        self.uow = uow

    async def read(self, operation: Any) -> Any:
        return await operation(self.uow)


class _Contents:
    def __init__(self) -> None:
        self.captured: dict[str, Any] = {}

    async def list_for_type(self, type_name: str, **kwargs: Any) -> Any:
        from inc.kernel.db import Page

        self.captured["type_name"] = type_name
        self.captured.update(kwargs)
        return Page(items=[], total=0, page=kwargs["page"], size=kwargs["size"])

    async def get_for_update_or_none(self, _content_id: Any) -> Content:
        return self.item

    async def delete(self, _item: Content) -> None:
        return None

    async def apply_comment_count_delta(
        self, content_id: Any, delta: int, *, content_type: str | None = None
    ) -> None:
        self.captured["comment_count_delta"] = (content_id, delta, content_type)

    async def list_ids_by_type(self) -> dict[str, list[Any]]:
        return {"demo": [uuid4()]}

    async def set_comment_count(self, content_type: str, content_id: Any, count: int) -> None:
        self.captured["recount"] = (content_type, content_id, count)


class _Uow:
    def __init__(self) -> None:
        self.contents = _Contents()


class _WriteExecutor(_ReadExecutor):
    async def write(self, operation: Any) -> Any:
        return await operation(self.uow)


def _ensure_content_codes() -> None:
    codes = (*import_module("inc.kernel.content.errors").CONTENT_CODES, *EVENT_CODES)
    missing = [code for code in codes if not ErrorRegistry.has(code.code)]
    if missing:
        register_error_codes(*missing)


@pytest.mark.asyncio
async def test_unknown_type_is_rejected_before_repository_access() -> None:
    _ensure_content_codes()
    services = _services_module()
    uow = _Uow()
    registry = ContentTypeRegistry([DemoContentType])
    service = services.ContentService(
        _ReadExecutor(uow), registry=registry, event_bus=fresh_event_bus()
    )

    with pytest.raises(AppError) as exc_info:
        await service.list("missing", _schemas_module().ContentListQuery())

    assert exc_info.value.code.code == "CONTENT_001"
    assert uow.contents.captured == {}


@pytest.mark.asyncio
async def test_list_forwards_q_status_and_comment_count_sort() -> None:
    _ensure_content_codes()
    services = _services_module()
    uow = _Uow()
    registry = ContentTypeRegistry([DemoContentType])
    service = services.ContentService(
        _ReadExecutor(uow), registry=registry, event_bus=fresh_event_bus()
    )

    result = await service.list(
        "demo",
        _schemas_module().ContentListQuery(
            q="seo", status="published", sort="comment_count", order="asc"
        ),
        Principal.anonymous(),
    )

    assert result.total == 0
    assert uow.contents.captured["q"] == "seo"
    assert uow.contents.captured["sort"] == "comment_count"
    assert uow.contents.captured["order"] == "asc"


@pytest.mark.asyncio
async def test_update_rejects_system_managed_fields_instead_of_silently_ignoring_them() -> None:
    _ensure_content_codes()
    services = _services_module()
    schemas = _schemas_module()
    uow = _Uow()
    registry = ContentTypeRegistry([DemoContentType])
    service = services.ContentService(
        _WriteExecutor(uow), registry=registry, event_bus=fresh_event_bus()
    )

    with pytest.raises(AppError) as exc_info:
        await service.update(
            "demo",
            uuid4(),
            schemas.ContentUpdate(comment_count=1),
            Principal.system_bot(),
        )

    assert exc_info.value.code.code == "CONTENT_005"


@pytest.mark.asyncio
async def test_trash_and_restore_set_trashed_at_and_publish_distinct_events() -> None:
    _ensure_content_codes()
    services = _services_module()
    uow = _Uow()
    item = Content(
        id=uuid4(),
        type="demo",
        title="Trash me",
        slug="trash-me",
        status="published",
        owner_id=uuid4(),
        content="body",
        excerpt="excerpt",
        data=ContentDataValues.model_validate({}),
    )
    uow.contents.item = item
    event_bus = fresh_event_bus()
    registry = ContentTypeRegistry([DemoContentType])
    service = services.ContentService(_WriteExecutor(uow), registry=registry, event_bus=event_bus)
    events: list[str] = []

    async def record(event: Any) -> None:
        events.append(event.type)

    event_bus.subscribe("content.trashed", record)
    event_bus.subscribe("content.restored", record)
    event_bus.subscribe("content.deleted", record)

    trashed = await service.transition("demo", item.id, "trash", Principal.system_bot())
    restored = await service.transition("demo", item.id, "restore", Principal.system_bot())
    await event_bus.wait_idle()

    assert trashed.status == "trash"
    assert trashed.trashed_at is not None
    assert restored.status == "draft"
    assert restored.trashed_at is None
    assert events == ["content.trashed", "content.restored"]


@pytest.mark.asyncio
async def test_comment_event_updates_count_with_type_scope() -> None:
    _ensure_content_codes()
    services = _services_module()
    uow = _Uow()
    registry = ContentTypeRegistry([DemoContentType])
    event_bus = fresh_event_bus(("comment.created",))
    _service = services.ContentService(_WriteExecutor(uow), registry=registry, event_bus=event_bus)
    from inc.kernel.comment.events import CommentEventPayload
    from inc.kernel.events import Event

    target_id = uuid4()
    event_bus.publish(
        Event(
            type="comment.created",
            payload=CommentEventPayload(
                comment_id=uuid4(),
                target_type="demo",
                target_id=target_id,
                count_delta=1,
            ),
        )
    )
    await event_bus.wait_idle()
    assert uow.contents.captured["comment_count_delta"] == (target_id, 1, "demo")


@pytest.mark.asyncio
async def test_recount_comments_writes_resolved_counts_by_type() -> None:
    _ensure_content_codes()
    services = _services_module()
    uow = _Uow()
    registry = ContentTypeRegistry([DemoContentType])
    service = services.ContentService(
        _WriteExecutor(uow),
        registry=registry,
        comment_stats=lambda _type_name, content_ids: {content_id: 4 for content_id in content_ids},
    )
    principal = Principal(
        id=uuid4(), username="admin", capabilities=frozenset({"content:update_any"})
    )
    assert await service.recount_comments(principal) == 1
    assert uow.contents.captured["recount"][0] == "demo"
    assert uow.contents.captured["recount"][2] == 4

"""G5 red tests for target validation, depth, and count-delta events."""

from __future__ import annotations

from importlib import import_module
from typing import Any
from uuid import uuid4

import pytest

from inc.kernel.cache import MemoryCache
from inc.kernel.comment.targets import CommentTargetPolicy
from inc.kernel.errors import AppError, register_error_codes
from inc.kernel.errors.registry import ErrorRegistry
from inc.kernel.events import EVENT_CODES, fresh_event_bus
from inc.kernel.security import Principal


def _services_module():
    try:
        return import_module("inc.kernel.comment.services")
    except ModuleNotFoundError as exc:  # pragma: no cover - G5 red assertion
        pytest.fail("G5 target missing: inc.kernel.comment.services")
        raise AssertionError from exc


def _schemas_module():
    try:
        return import_module("inc.kernel.comment.schemas")
    except ModuleNotFoundError as exc:  # pragma: no cover - G5 red assertion
        pytest.fail("G5 target missing: inc.kernel.comment.schemas")
        raise AssertionError from exc


def _post_policy(target_type: str) -> CommentTargetPolicy | None:
    return CommentTargetPolicy() if target_type == "post" else None


class _Comments:
    def __init__(self) -> None:
        self.captured: dict[str, Any] = {}

    async def count_roots(self, *args: Any, **kwargs: Any) -> int:
        self.captured["count_roots"] = (args, kwargs)
        return 0

    async def count_for_target(self, *args: Any, **kwargs: Any) -> int:
        self.captured["count_for_target"] = (args, kwargs)
        return 0

    async def add(self, item: Any) -> None:
        item.id = uuid4()

    async def list_roots(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    async def list_descendants(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []


class _Uow:
    def __init__(self) -> None:
        self.comments = _Comments()


class _ReadExecutor:
    def __init__(self, uow: _Uow) -> None:
        self.uow = uow

    async def read(self, operation: Any) -> Any:
        return await operation(self.uow)


class _WriteExecutor(_ReadExecutor):
    async def write(self, operation: Any) -> Any:
        return await operation(self.uow)


def _ensure_codes() -> None:
    codes = (*import_module("inc.kernel.comment.errors").COMMENT_CODES, *EVENT_CODES)
    missing = [code for code in codes if not ErrorRegistry.has(code.code)]
    if missing:
        register_error_codes(*missing)


@pytest.mark.asyncio
async def test_unknown_target_is_rejected_before_repository_or_cache() -> None:
    _ensure_codes()
    services = _services_module()
    service = services.CommentService(
        _ReadExecutor(_Uow()),
        MemoryCache(),
        target_policy=_post_policy,
        event_bus=fresh_event_bus(),
    )

    with pytest.raises(AppError) as exc_info:
        await service.list_threads("missing", uuid4(), query=_schemas_module().CommentThreadQuery())
    assert exc_info.value.code.code == "COMMENT_006"


@pytest.mark.asyncio
async def test_stats_use_all_approved_comments_not_only_roots() -> None:
    _ensure_codes()
    services = _services_module()
    uow = _Uow()
    service = services.CommentService(
        _ReadExecutor(uow),
        MemoryCache(),
        target_policy=_post_policy,
        event_bus=fresh_event_bus(),
    )
    await service.stats_for_targets("post", [uuid4()])
    assert "count_for_target" in uow.comments.captured


@pytest.mark.asyncio
async def test_target_exists_rejection_is_a_registered_error() -> None:
    _ensure_codes()
    services = _services_module()
    service = services.CommentService(
        _ReadExecutor(_Uow()),
        MemoryCache(),
        target_policy=_post_policy,
        target_exists=lambda _type_name, _target_id: False,
        event_bus=fresh_event_bus(),
    )
    principal = Principal(id=uuid4(), username="writer", capabilities=frozenset({"comment:create"}))

    with pytest.raises(AppError) as exc_info:
        await service.create(
            _schemas_module().CommentCreate(target_type="post", target_id=uuid4(), content="hello"),
            principal,
        )
    assert exc_info.value.code.code == "COMMENT_002"


def test_comment_service_accepts_policy_projection_without_content_import() -> None:
    targets = import_module("inc.kernel.comment.targets")
    policy = targets.CommentTargetPolicy(max_depth=4, auto_approve=False, rate_limit=8)
    assert policy.max_depth == 4
    assert policy.auto_approve is False


@pytest.mark.asyncio
async def test_approved_creation_publishes_positive_count_delta() -> None:
    _ensure_codes()
    services = _services_module()
    schemas = _schemas_module()
    uow = _Uow()
    event_bus = fresh_event_bus()
    service = services.CommentService(
        _WriteExecutor(uow),
        MemoryCache(),
        target_policy=lambda target_type: (
            CommentTargetPolicy(auto_approve=True) if target_type == "post" else None
        ),
        event_bus=event_bus,
    )
    captured: list[int] = []

    async def record(event: Any) -> None:
        captured.append(event.payload.count_delta)

    event_bus.subscribe("comment.created", record)
    principal = Principal(id=uuid4(), username="writer", capabilities=frozenset({"comment:create"}))
    await service.create(
        schemas.CommentCreate(target_type="post", target_id=uuid4(), content="hello"),
        principal,
    )
    await event_bus.wait_idle()
    assert captured == [1]


def test_comment_event_payload_carries_comment_count_delta() -> None:
    events = import_module("inc.kernel.comment.events")
    payload = events.CommentEventPayload(
        comment_id=uuid4(),
        target_type="post",
        target_id=uuid4(),
        count_delta=1,
    )
    moderated = events.CommentModeratedPayload(
        comment_id=payload.comment_id,
        target_type="post",
        target_id=payload.target_id,
        owner_id=uuid4(),
        action="approve",
        actor_id=uuid4(),
        count_delta=1,
    )
    assert payload.count_delta == 1
    assert moderated.count_delta == 1

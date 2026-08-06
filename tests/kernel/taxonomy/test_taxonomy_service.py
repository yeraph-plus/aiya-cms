"""G4 red tests for taxonomy type/group validation and list composition."""

from __future__ import annotations

from importlib import import_module
from typing import Any

import pytest

from inc.kernel.content import (
    ContentStatusDef,
    ContentType,
    ContentTypeRegistry,
    TaxonomyGroupDef,
)
from inc.kernel.errors import AppError, register_error_codes
from inc.kernel.errors.registry import ErrorRegistry
from inc.kernel.events import EVENT_CODES, fresh_event_bus


def _services_module():
    try:
        return import_module("inc.kernel.taxonomy.services")
    except ModuleNotFoundError as exc:  # pragma: no cover - G4 red assertion
        pytest.fail("G4 target missing: inc.kernel.taxonomy.services")
        raise AssertionError from exc


def _schemas_module():
    try:
        return import_module("inc.kernel.taxonomy.schemas")
    except ModuleNotFoundError as exc:  # pragma: no cover - G4 red assertion
        pytest.fail("G4 target missing: inc.kernel.taxonomy.schemas")
        raise AssertionError from exc


class PostContentType(ContentType):
    type_name = "post"
    statuses = (ContentStatusDef(slug="draft"),)
    default_status = "draft"
    fields = ()
    taxonomy_groups = (
        TaxonomyGroupDef(slug="category", title="Category"),
        TaxonomyGroupDef(slug="tag", title="Tag"),
    )


class _Terms:
    def __init__(self) -> None:
        self.captured: dict[str, Any] = {}

    async def list_filtered(self, type_name: str, **kwargs: Any) -> Any:
        from inc.kernel.db import Page

        self.captured["type_name"] = type_name
        self.captured.update(kwargs)
        return Page(items=[], total=0, page=kwargs["page"], size=kwargs["size"])


class _Uow:
    def __init__(self) -> None:
        self.terms = _Terms()


class _ReadExecutor:
    def __init__(self, uow: _Uow) -> None:
        self.uow = uow

    async def read(self, operation: Any) -> Any:
        return await operation(self.uow)


def _ensure_codes() -> None:
    codes = (*import_module("inc.kernel.taxonomy.errors").TERM_CODES, *EVENT_CODES)
    missing = [code for code in codes if not ErrorRegistry.has(code.code)]
    if missing:
        register_error_codes(*missing)


@pytest.mark.asyncio
async def test_unknown_type_and_group_fail_before_repository_access() -> None:
    _ensure_codes()
    services = _services_module()
    uow = _Uow()
    registry = ContentTypeRegistry([PostContentType])
    service = services.TermService(
        _ReadExecutor(uow), content_registry=registry, event_bus=fresh_event_bus()
    )

    with pytest.raises(AppError) as type_error:
        await service.list("missing", _schemas_module().TermListQuery())
    assert type_error.value.code.code == "TERM_005"
    assert uow.terms.captured == {}

    with pytest.raises(AppError) as group_error:
        await service.list("post", _schemas_module().TermListQuery(group="unknown"))
    assert group_error.value.code.code == "TERM_002"
    assert uow.terms.captured == {}


@pytest.mark.asyncio
async def test_term_list_forwards_q_group_slug_sort_and_order() -> None:
    _ensure_codes()
    services = _services_module()
    uow = _Uow()
    registry = ContentTypeRegistry([PostContentType])
    service = services.TermService(
        _ReadExecutor(uow), content_registry=registry, event_bus=fresh_event_bus()
    )

    result = await service.list(
        "post",
        _schemas_module().TermListQuery(
            q="news", group="category", slug="news", sort="name", order="desc"
        ),
    )

    assert result.total == 0
    assert uow.terms.captured == {
        "type_name": "post",
        "group": "category",
        "slug": "news",
        "q": "news",
        "created_from": None,
        "created_to": None,
        "updated_from": None,
        "updated_to": None,
        "page": 1,
        "size": 20,
        "sort": "name",
        "order": "desc",
    }

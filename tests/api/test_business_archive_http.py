from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, FastAPI

from inc.api.http.routers_archive_admin import build_router as build_archive_admin_router
from inc.api.http.routers_business_center import build_router as build_business_router


def _dependency(_: str | None = None) -> Any:
    async def dependency() -> None:
        return None

    return dependency


def _paths(router: APIRouter) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in router.routes
        for method in getattr(route, "methods", set())
    }


def test_business_router_exposes_only_subject_bound_contract() -> None:
    app = FastAPI()
    router = build_business_router(
        SimpleNamespace(),
        _dependency,
        _dependency,  # type: ignore[arg-type]
    )
    app.include_router(router)
    paths = _paths(router)
    assert {
        ("POST", "/api/v1/business/quotes"),
        ("POST", "/api/v1/business/consumptions"),
        ("GET", "/api/v1/business/consumptions/{workflow_id}"),
        ("GET", "/api/v1/me/downloads"),
        ("POST", "/api/v1/me/downloads/{grant_id}/links"),
    } <= paths

    schema = app.openapi()
    consumption = schema["paths"]["/api/v1/business/consumptions"]["post"]
    assert any(
        parameter["name"] == "Idempotency-Key" and parameter["required"]
        for parameter in consumption["parameters"]
    )


def test_archive_admin_router_has_crud_named_states_and_grants() -> None:
    app = FastAPI()
    router = build_archive_admin_router(
        SimpleNamespace(),
        _dependency,  # type: ignore[arg-type]
    )
    app.include_router(router)
    paths = _paths(router)
    assert {
        ("GET", "/api/v1/admin/archive/items"),
        ("POST", "/api/v1/admin/archive/items"),
        ("GET", "/api/v1/admin/archive/items/{item_id}"),
        ("PATCH", "/api/v1/admin/archive/items/{item_id}"),
        ("POST", "/api/v1/admin/archive/items/{item_id}/verify"),
        ("POST", "/api/v1/admin/archive/items/{item_id}/activate"),
        ("POST", "/api/v1/admin/archive/items/{item_id}/retire"),
        ("POST", "/api/v1/admin/archive/items/{item_id}/migrate-provider"),
        ("GET", "/api/v1/admin/archive/grants"),
        ("GET", "/api/v1/admin/archive/grants/{grant_id}"),
        ("POST", "/api/v1/admin/archive/grants/{grant_id}/revoke"),
    } <= paths

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from inc.api.http.context import AppContext
from inc.api.http.routers_user_center import build_router

SUBJECT = "subject-from-principal"


class FakeUserCenter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        async def call(**kwargs: Any) -> dict[str, Any]:
            self.calls.append((name, kwargs))
            return {"ok": True}

        return call


def _authenticated() -> Any:
    async def dependency() -> AppContext:
        return SimpleNamespace(principal=SimpleNamespace(subject_id=SUBJECT))  # type: ignore[return-value]

    return dependency


def _paths(router: APIRouter) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in router.routes
        for method in getattr(route, "methods", set())
    }


def _app() -> tuple[TestClient, FakeUserCenter]:
    user_center = FakeUserCenter()
    services = SimpleNamespace(user_center=user_center)
    app = FastAPI()
    app.include_router(build_router(services, lambda _: _authenticated(), _authenticated))
    return TestClient(app), user_center


def test_user_center_exposes_complete_contract() -> None:
    app = FastAPI()
    router = build_router(SimpleNamespace(), lambda _: _authenticated(), _authenticated)
    app.include_router(router)
    assert {
        ("GET", "/api/v1/me"),
        ("PATCH", "/api/v1/me"),
        ("POST", "/api/v1/me/avatar/upload-intents"),
        ("POST", "/api/v1/me/avatar/upload-intents/{intent_id}/finalize"),
        ("POST", "/api/v1/me/check-ins"),
        ("GET", "/api/v1/me/points"),
        ("GET", "/api/v1/me/points/ledger"),
        ("GET", "/api/v1/membership/levels"),
        ("GET", "/api/v1/me/membership"),
        ("POST", "/api/v1/me/membership/orders"),
        ("POST", "/api/v1/me/membership/cancel"),
        ("GET", "/api/v1/points/products"),
        ("POST", "/api/v1/me/points/orders"),
        ("GET", "/api/v1/me/payment-orders/{order_id}"),
        ("POST", "/api/v1/me/gift-cards/redemptions"),
        ("GET", "/api/v1/me/purchases"),
    } <= _paths(router)


def test_all_write_routes_require_idempotency_key() -> None:
    app = FastAPI()
    router = build_router(SimpleNamespace(), lambda _: _authenticated(), _authenticated)
    app.include_router(router)
    schema = app.openapi()
    for path, item in schema["paths"].items():
        for operation in item.values():
            if not isinstance(operation, dict) or operation.get("operationId") is None:
                continue
            operation_id = operation.get("operationId", "")
            has_write_body = operation.get("requestBody") is not None
            is_bodyless_write = operation_id.startswith(("check_in", "avatar_finalize"))
            if has_write_body or is_bodyless_write:
                assert any(
                    parameter["name"] == "Idempotency-Key" and parameter["required"]
                    for parameter in operation.get("parameters", [])
                ), path


def test_subject_is_taken_from_context_and_never_from_body() -> None:
    client, service = _app()
    response = client.post(
        "/api/v1/me/points/orders",
        headers={"Idempotency-Key": "order-1"},
        json={"product_key": "bundle.basic", "provider_key": "mock", "subject_id": "forged"},
    )
    assert response.status_code == 422

    response = client.post(
        "/api/v1/me/points/orders",
        headers={"Idempotency-Key": "order-1"},
        json={"product_key": "bundle.basic", "provider_key": "mock"},
    )
    assert response.status_code == 200
    assert service.calls[-1] == (
        "create_point_order",
        {
            "subject_id": SUBJECT,
            "product_key": "bundle.basic",
            "provider_key": "mock",
            "idempotency_key": "order-1",
        },
    )

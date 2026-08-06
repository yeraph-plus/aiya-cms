"""Red tests locking the errors component contract (M1.1).

Contract source: context/spec/kernel.md
"""

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator

from inc.kernel import logging as klogging
from inc.kernel.errors import (
    COMMON_001,
    COMMON_404,
    COMMON_500,
    AppError,
    ErrorCode,
    app_error_handler,
    clear_registry,
    register_error_codes,
    request_validation_handler,
    unhandled_exception_handler,
    validate_registry,
)

TEST_404 = ErrorCode("TEST_404", 404, "测试资源不存在")


@pytest.fixture(autouse=True)
def fresh_registry() -> None:
    clear_registry()
    register_error_codes(COMMON_001, COMMON_404, COMMON_500, TEST_404)
    yield


class Payload(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def reject_bad_name(cls, value: str) -> str:
        if value == "bad":
            raise ValueError("invalid name")
        return value


def make_client() -> TestClient:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)

    @app.middleware("http")
    async def inject_request_id(request, call_next):  # type: ignore[no-untyped-def]
        klogging.bind_context(request_id="test-rid-123")
        return await call_next(request)

    @app.get("/not-found")
    def not_found() -> None:
        raise AppError(TEST_404, detail={"resource": "demo"})

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret-internal")

    @app.post("/echo")
    def echo(body: Payload) -> Payload:
        return body

    return TestClient(app, raise_server_exceptions=False)


def test_duplicate_registration_raises() -> None:
    with pytest.raises(ValueError):
        register_error_codes(TEST_404)


def test_app_error_carries_code_detail_cause() -> None:
    err = AppError(TEST_404, detail={"x": 1})
    assert err.code.code == "TEST_404"
    assert err.detail == {"x": 1}


def test_app_error_with_unregistered_code_fails_fast() -> None:
    unregistered = ErrorCode("UNREG_001", 500, "未登记")

    with pytest.raises(ValueError):
        AppError(unregistered)


def test_validate_registry_rejects_unregistered() -> None:
    missing = ErrorCode("AUTH_999", 401, "未登记")

    with pytest.raises(RuntimeError):
        validate_registry([TEST_404, missing])


def test_registered_app_error_response_shape() -> None:
    client = make_client()

    resp = client.get("/not-found")

    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "TEST_404"
    assert body["message"] == "测试资源不存在"
    assert body["detail"] == {"resource": "demo"}
    assert body["request_id"] == "test-rid-123"


def test_unhandled_exception_maps_to_common_500_without_leak() -> None:
    client = make_client()

    resp = client.get("/boom")

    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == "COMMON_500"
    assert body["detail"] is None
    assert "secret-internal" not in resp.text
    assert body["request_id"] == "test-rid-123"


def test_request_validation_error_maps_to_common_001() -> None:
    client = make_client()

    resp = client.post("/echo", json={})

    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "COMMON_001"
    assert isinstance(body["detail"], list)
    assert body["detail"][0]["loc"]  # field error carries location


def test_request_validation_error_with_value_error_is_json_serializable() -> None:
    client = make_client()

    resp = client.post("/echo", json={"name": "bad"})

    assert resp.status_code == 422
    assert resp.json()["code"] == "COMMON_001"

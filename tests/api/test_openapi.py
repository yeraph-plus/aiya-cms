"""OpenAPI determinism and snapshot contract tests.

Contract source: context/spec/http-openapi.md §10.
"""

from __future__ import annotations

import json
from typing import Any


def test_schema_generation_is_deterministic() -> None:
    from inc.api.openapi import generate_schema

    first = json.dumps(generate_schema(), indent=2, sort_keys=True)
    second = json.dumps(generate_schema(), indent=2, sort_keys=True)
    assert first == second


def test_production_does_not_expose_complete_runtime_openapi(
    uow_factory: Any, clock: Any, tmp_path: Any
) -> None:
    from inc.api.app import create_app
    from inc.api.config import ApiSettings
    from inc.api.manifest import release

    app = create_app(
        manifest=release,
        uow_factory=uow_factory,
        clock=clock,
        settings=ApiSettings(
            environment="production",
            issuer="https://testserver.example",
            secure_cookies=True,
            admin_session_secret="test-production-session-secret-0123456789",
            oidc_signing_key_dir=str(tmp_path / "keys"),
        ),
        redis_url="redis://127.0.0.1:6379/0",
        start_workers=False,
    )
    assert "/openapi.json" not in {
        path for route in app.routes if (path := getattr(route, "path", None)) is not None
    }


def test_management_schema_contains_only_releasable_contract() -> None:
    from inc.api.openapi import generate_schema

    schema = generate_schema()
    paths = schema["paths"]
    for expected in (
        "/healthz",
        "/api/v1/health",
        "/api/v1/admin/points/ledger",
        "/api/v1/admin/content",
        "/api/v1/admin/content-bucket/upload-intents",
        "/api/v1/admin/users",
        "/api/v1/admin/taxonomy/dimensions",
        "/api/v1/admin/settings/groups/{group_key}",
        "/oidc/token",
        "/oidc/authorize",
        "/oidc/login",
        "/.well-known/openid-configuration",
        "/api/v1/auth/register",
        "/api/v1/auth/verify-email",
        "/api/v1/auth/password-reset/request",
        "/api/v1/auth/password-reset/confirm",
        "/api/v1/me",
        "/api/v1/me/purchases",
        "/api/v1/business/quotes",
        "/api/v1/business/consumptions",
        "/api/v1/admin/archive/items",
    ):
        assert expected in paths, expected
    assert "/api/v1/admin/notifications/deliveries" in paths
    assert "HTTPBearer" in schema.get("components", {}).get("securitySchemes", {})


def test_every_operation_is_tagged_and_admin_operations_are_grouped() -> None:
    from inc.api.openapi import generate_schema

    schema = generate_schema()
    declared = [tag["name"] for tag in schema.get("tags", [])]
    assert len(declared) == len(set(declared)), "tags must be unique"
    admin_paths = 0
    for path, methods in schema["paths"].items():
        for operation in methods.values():
            if not isinstance(operation, dict) or "tags" not in operation:
                raise AssertionError(f"operation missing tags: {path}")
            for tag in operation["tags"]:
                assert tag in declared, f"undeclared tag {tag!r} on {path}"
            if path.startswith("/api/v1/admin"):
                admin_paths += 1
                assert "admin" in operation["tags"], f"admin operation not grouped: {path}"
    assert admin_paths > 0


def test_dump_and_check_roundtrip(tmp_path: Any, monkeypatch: Any) -> None:
    import inc.api.openapi as openapi_module

    monkeypatch.setattr(openapi_module, "OPENAPI_PATH", tmp_path / "openapi.json")
    monkeypatch.setattr(openapi_module, "SHA256_PATH", tmp_path / "openapi.sha256")
    monkeypatch.setattr(openapi_module, "USER_OPENAPI_PATH", tmp_path / "openapi.user.json")
    monkeypatch.setattr(openapi_module, "USER_SHA256_PATH", tmp_path / "openapi.user.sha256")
    monkeypatch.setattr(openapi_module, "ADMIN_OPENAPI_PATH", tmp_path / "openapi.admin.json")
    monkeypatch.setattr(openapi_module, "ADMIN_SHA256_PATH", tmp_path / "openapi.admin.sha256")
    openapi_module.dump()
    assert openapi_module.check() is True
    # drift detection
    openapi_module.OPENAPI_PATH.write_text(
        openapi_module.OPENAPI_PATH.read_text(encoding="utf-8").replace('"title"', '"titleX"'),
        encoding="utf-8",
    )
    assert openapi_module.check() is False


def test_user_schema_is_a_closed_allowlisted_projection() -> None:
    from inc.api.openapi import USER_TAGS, generate_user_schema

    schema = generate_user_schema()
    assert schema["paths"], "the current auth surface must produce a non-empty user schema"
    assert "/api/v1/auth/register" in schema["paths"]
    assert "/api/v1/auth/verify-email" in schema["paths"]
    assert "/api/v1/auth/password-reset/request" in schema["paths"]
    assert "/api/v1/auth/password-reset/confirm" in schema["paths"]
    assert "/api/v1/me" in schema["paths"]
    for path, methods in schema["paths"].items():
        assert not path.startswith("/api/v1/admin"), path
        assert not path.startswith("/api/v1/webhooks"), path
        for method, operation in methods.items():
            if method not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                continue
            assert set(operation["tags"]) <= USER_TAGS

    serialized = json.dumps(schema, sort_keys=True)
    assert "#/components/schemas/" in serialized
    for category, entries in schema.get("components", {}).items():
        for name in entries:
            if category == "securitySchemes":
                assert any(
                    name in requirement
                    for methods in schema["paths"].values()
                    for operation in methods.values()
                    if isinstance(operation, dict)
                    for requirement in operation.get("security", [])
                )
            else:
                assert f"#/components/{category}/{name}" in serialized


def test_admin_schema_contains_all_admin_routes_and_excludes_user_routes() -> None:
    from inc.api.openapi import generate_admin_schema, generate_schema

    schema = generate_admin_schema()
    paths = schema["paths"]
    full_admin_paths = {
        path
        for path in generate_schema()["paths"]
        if path == "/api/v1/admin" or path.startswith("/api/v1/admin/")
    }
    assert full_admin_paths <= set(paths)
    assert "/api/v1/admin/session" in paths
    assert "/api/v1/admin/gift-cards/batches" in paths
    assert "/api/v1/admin/archive/items" in paths
    assert "/api/v1/me" not in paths
    assert "/api/v1/auth/register" not in paths
    assert "/api/v1/content/{type_name}" not in paths
    assert "/oidc/token" in paths
    assert "/.well-known/openid-configuration" in paths
    assert all(
        path.startswith("/api/v1/admin")
        or path.startswith(("/healthz", "/api/v1/health", "/oidc/", "/.well-known/"))
        for path in paths
    )

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


def test_management_schema_contains_only_releasable_contract() -> None:
    from inc.api.openapi import generate_schema

    schema = generate_schema()
    paths = schema["paths"]
    for expected in (
        "/healthz",
        "/api/v1/health",
        "/api/v1/admin/points/ledger",
        "/api/v1/auth/grants",
        "/api/v1/auth/grants/{client_id}",
        "/api/v1/admin/content",
        "/api/v1/admin/users",
        "/api/v1/admin/taxonomy/dimensions",
        "/api/v1/admin/settings/groups/{group_key}",
        "/oidc/token",
        "/oidc/authorize",
        "/.well-known/openid-configuration",
    ):
        assert expected in paths, expected
    assert "/api/v1/me" not in paths
    assert "/api/v1/me/points/ledger" not in paths
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

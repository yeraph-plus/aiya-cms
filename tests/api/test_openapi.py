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


def test_cms_schema_contains_expected_contract() -> None:
    from inc.api.openapi import generate_schema

    schema = generate_schema()
    paths = schema["paths"]
    for expected in (
        "/healthz",
        "/api/v1/health",
        "/api/v1/auth/me",
        "/api/v1/admin/content",
        "/api/v1/admin/users",
        "/api/v1/admin/taxonomy/dimensions",
        "/api/v1/admin/settings/groups/{group_key}",
        "/oidc/token",
        "/oidc/authorize",
        "/.well-known/openid-configuration",
    ):
        assert expected in paths, expected
    assert "HTTPBearer" in schema.get("components", {}).get("securitySchemes", {})


def test_dump_and_check_roundtrip(tmp_path: Any, monkeypatch: Any) -> None:
    import inc.api.openapi as openapi_module

    monkeypatch.setattr(openapi_module, "OPENAPI_PATH", tmp_path / "openapi.json")
    monkeypatch.setattr(openapi_module, "SHA256_PATH", tmp_path / "openapi.sha256")
    openapi_module.dump()
    assert openapi_module.check() is True
    # drift detection
    openapi_module.OPENAPI_PATH.write_text(
        openapi_module.OPENAPI_PATH.read_text(encoding="utf-8").replace('"title"', '"titleX"'),
        encoding="utf-8",
    )
    assert openapi_module.check() is False

"""Runtime environment configuration contracts."""

from __future__ import annotations

from typing import Any

import pytest

from inc.api.config import DEFAULT_ISSUER
from inc.main import _api_settings_from_env, _manifest_from_env, _parse_cors_origins


def test_cors_origins_accept_csv_and_json_array() -> None:
    assert _parse_cors_origins("http://localhost:5173, https://admin.example") == (
        "http://localhost:5173",
        "https://admin.example",
    )
    assert _parse_cors_origins('["http://localhost:5173"]') == ("http://localhost:5173",)


def test_cors_typo_is_rejected_instead_of_silently_ignored() -> None:
    with pytest.raises(ValueError, match="AIYA_CORS_ORIGINS"):
        _api_settings_from_env({"AIYA_CROS_ORIGINS": "http://localhost:5173"})


def test_api_settings_reads_issuer_and_cors_from_environment() -> None:
    settings = _api_settings_from_env(
        {
            "AIYA_ISSUER": "http://localhost:8000",
            "AIYA_CORS_ORIGINS": '["http://localhost:5173"]',
            "AIYA_ENVIRONMENT": "dev",
        }
    )

    assert settings.issuer == "http://localhost:8000"
    assert settings.cors_origins == ("http://localhost:5173",)


def test_default_issuer_matches_compose_backend_port() -> None:
    assert _api_settings_from_env({}).issuer == DEFAULT_ISSUER == "http://127.0.0.1:8000"


def test_runtime_manifest_selection_is_explicit_and_fail_closed() -> None:
    assert _manifest_from_env({}).name == "release"
    assert _manifest_from_env({"AIYA_APP_PROFILE": "release"}).name == "release"
    with pytest.raises(ValueError, match="must be release"):
        _manifest_from_env({"AIYA_APP_PROFILE": "management"})
    with pytest.raises(ValueError, match="must be release"):
        _manifest_from_env({"AIYA_APP_PROFILE": "legacy"})
    with pytest.raises(ValueError, match="AIYA_APP_PROFILE"):
        _manifest_from_env({"AIYA_APP_PROFILE": "unknown"})


def test_production_cors_must_be_an_exact_allowlist() -> None:
    with pytest.raises(ValueError, match="wildcard"):
        _api_settings_from_env(
            {
                "AIYA_ENVIRONMENT": "production",
                "AIYA_ISSUER": "https://cms.example",
                "AIYA_SECURE_COOKIES": "true",
                "AIYA_CORS_ORIGINS": "*",
            }
        )


async def test_cors_allows_cookie_auth_only_for_configured_origin(client: Any) -> None:
    response = await client.options(
        "/.well-known/openid-configuration",
        headers={
            "Origin": "http://admin.test",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://admin.test"
    assert response.headers["access-control-allow-credentials"] == "true"

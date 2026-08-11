"""SMTP2GO REST notification adapter contract tests (no network)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from inc.adapters.notification.smtp2go import (
    SMTP2GO_ENDPOINTS,
    Smtp2GoEmailAdapter,
    smtp2go_settings_from_group,
)
from inc.capabilities.notification.ports import RecipientTarget


class _SettingsReader:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values
        self.calls = 0

    async def get_group(self, group_key: str) -> Any:
        assert group_key == "notification"
        self.calls += 1
        return type("SettingGroup", (), {"values": dict(self.values)})()


@dataclass
class _Response:
    status_code: int
    payload: Any

    def json(self) -> Any:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def _target() -> RecipientTarget:
    return RecipientTarget(
        channel="email",
        address="recipient@example.com",
        masked_address="re***@example.com",
    )


def _enabled_values(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "email_enabled": True,
        "smtp2go_enabled": True,
        "smtp2go_api_key": "api-secret",
        "smtp2go_region": "global",
        "default_from_name": "Aiya",
        "smtp_from_address": "sender@example.com",
    }
    values.update(overrides)
    return values


def test_settings_reuse_existing_sender_fields_and_fixed_region_endpoints() -> None:
    settings = smtp2go_settings_from_group(_enabled_values(smtp2go_region="eu"))
    assert settings.enabled is True
    assert settings.api_key == "api-secret"
    assert settings.endpoint == SMTP2GO_ENDPOINTS["eu"]
    assert settings.from_name == "Aiya"
    assert settings.from_address == "sender@example.com"


async def test_disabled_adapter_returns_unavailable_without_http_call() -> None:
    calls: list[dict[str, Any]] = []

    def post(*args: Any, **kwargs: Any) -> _Response:
        calls.append(kwargs)
        return _Response(200, {})

    adapter = Smtp2GoEmailAdapter(settings_queries=_SettingsReader({}), post=post)
    result = await adapter.send(
        target=_target(), subject="subject", body="body", idempotency_key="delivery-1"
    )
    assert result.status == "unavailable"
    assert result.error_category == "disabled"
    assert calls == []


async def test_enabled_adapter_requires_api_key_without_http_call() -> None:
    calls: list[dict[str, Any]] = []

    def post(*args: Any, **kwargs: Any) -> _Response:
        calls.append(kwargs)
        return _Response(200, {})

    adapter = Smtp2GoEmailAdapter(
        settings_queries=_SettingsReader(_enabled_values(smtp2go_api_key=None)), post=post
    )
    result = await adapter.send(
        target=_target(), subject="subject", body="body", idempotency_key="delivery-1"
    )
    assert result.status == "unavailable"
    assert result.error_category == "configuration"
    assert calls == []


async def test_send_posts_off_event_loop_and_maps_success() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def post(url: str, **kwargs: Any) -> _Response:
        calls.append((url, kwargs))
        return _Response(
            200,
            {
                "email_response": {
                    "succeeded": 1,
                    "failed": 0,
                    "failures": [],
                    "email_id": "smtp2go-message-1",
                },
                "request_id": "request-1",
            },
        )

    adapter = Smtp2GoEmailAdapter(
        settings_queries=_SettingsReader(_enabled_values(smtp2go_region="us")), post=post
    )
    result = await adapter.send(
        target=_target(), subject="Hello", body="Plain body", idempotency_key="delivery-1"
    )

    assert result.status == "delivered"
    assert result.provider_ref == "smtp2go-message-1"
    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url == SMTP2GO_ENDPOINTS["us"]
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == (5.0, 15.0)
    assert kwargs["headers"]["Accept"] == "application/json"
    assert kwargs["headers"]["X-Smtp2go-Api-Key"] == "api-secret"
    assert kwargs["json"] == {
        "api_key": "api-secret",
        "sender": "Aiya <sender@example.com>",
        "to": ["recipient@example.com"],
        "subject": "Hello",
        "text_body": "Plain body",
        "custom_headers": [{"header": "X-Aiya-Idempotency-Key", "value": "delivery-1"}],
    }


async def test_connect_timeout_and_rate_limit_allow_fallback() -> None:
    def connect_timeout(*args: Any, **kwargs: Any) -> _Response:
        raise requests.ConnectTimeout("connect timed out")

    adapter = Smtp2GoEmailAdapter(
        settings_queries=_SettingsReader(_enabled_values()), post=connect_timeout
    )
    result = await adapter.send(
        target=_target(), subject="x", body="y", idempotency_key="delivery-1"
    )
    assert result.status == "failed"
    assert result.error_category == "transient"
    assert result.fallback_allowed is True

    adapter = Smtp2GoEmailAdapter(
        settings_queries=_SettingsReader(_enabled_values()),
        post=lambda *args, **kwargs: _Response(429, {"data": {"error": "limited"}}),
    )
    result = await adapter.send(
        target=_target(), subject="x", body="y", idempotency_key="delivery-1"
    )
    assert result.status == "failed"
    assert result.error_category == "rate_limited"
    assert result.fallback_allowed is True


async def test_ambiguous_http_outcomes_stop_fallback() -> None:
    def read_timeout(*args: Any, **kwargs: Any) -> _Response:
        raise requests.ReadTimeout("response timed out")

    adapter = Smtp2GoEmailAdapter(
        settings_queries=_SettingsReader(_enabled_values()), post=read_timeout
    )
    result = await adapter.send(
        target=_target(), subject="x", body="y", idempotency_key="delivery-1"
    )
    assert result.status == "unknown"
    assert result.fallback_allowed is False

    adapter = Smtp2GoEmailAdapter(
        settings_queries=_SettingsReader(_enabled_values()),
        post=lambda *args, **kwargs: _Response(200, ValueError("invalid JSON")),
    )
    result = await adapter.send(
        target=_target(), subject="x", body="y", idempotency_key="delivery-1"
    )
    assert result.status == "unknown"
    assert result.fallback_allowed is False


async def test_http_400_and_provider_recipient_failure_are_permanent() -> None:
    adapter = Smtp2GoEmailAdapter(
        settings_queries=_SettingsReader(_enabled_values()),
        post=lambda *args, **kwargs: _Response(
            400,
            {"data": {"error_code": "E_BAD_REQUEST", "error": "invalid request"}},
        ),
    )
    result = await adapter.send(
        target=_target(), subject="x", body="y", idempotency_key="delivery-1"
    )
    assert result.status == "failed"
    assert result.error_category == "permanent"
    assert result.fallback_allowed is False

    adapter = Smtp2GoEmailAdapter(
        settings_queries=_SettingsReader(_enabled_values()),
        post=lambda *args, **kwargs: _Response(
            200,
            {
                "email_response": {
                    "succeeded": 0,
                    "failed": 1,
                    "failures": ["recipient rejected"],
                }
            },
        ),
    )
    result = await adapter.send(
        target=_target(), subject="x", body="y", idempotency_key="delivery-1"
    )
    assert result.status == "failed"
    assert result.error_category == "permanent"
    assert "recipient rejected" not in (result.error_summary or "")

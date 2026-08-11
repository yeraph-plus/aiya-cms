"""SMTP adapter unit tests that need no SMTP endpoint.

Contract source: context/spec/capabilities/notification.md §8.

Covers header-safety guards, RFC 2047 subject encoding and error
classification that never touch the network.
"""

from __future__ import annotations

from typing import Any

import pytest

from inc.adapters.notification.email_smtp import (
    SmtpEmailAdapter,
    SmtpSettings,
    _encode_header,
    _validate_header_value,
)
from inc.capabilities.notification.ports import ProviderError, RecipientTarget


class _SettingsReader:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values
        self.calls = 0

    async def get_group(self, group_key: str) -> Any:
        assert group_key == "notification"
        self.calls += 1
        return type("SettingGroup", (), {"values": dict(self.values)})()


def _target(address: str = "recipient@example.com") -> RecipientTarget:
    return RecipientTarget(channel="email", address=address, masked_address="re***@example.com")


def test_header_value_rejects_crlf() -> None:
    with pytest.raises(ValueError):
        _validate_header_value("victim@example.com\r\nBcc: attacker@example.com", "to")
    with pytest.raises(ValueError):
        _validate_header_value("no-reply@aiya.local\nReply-To: evil@example.com", "from")


def test_encode_header_passes_ascii_through() -> None:
    assert _encode_header("plain subject") == "plain subject"


def test_encode_header_encodes_non_ascii() -> None:
    encoded = _encode_header("café 中文")
    assert encoded.startswith("=?utf-8?B?")
    assert encoded.endswith("?=")
    assert "é" not in encoded


def test_encode_header_strips_crlf() -> None:
    assert "\r" not in _encode_header("a\r\nb")
    assert "\n" not in _encode_header("a\r\nb")


async def test_recipients_refused_is_permanent(monkeypatch: Any) -> None:
    import aiosmtplib

    adapter = SmtpEmailAdapter(
        settings_queries=_SettingsReader(
            {
                "email_enabled": True,
                "smtp_enabled": True,
                "smtp_host": "127.0.0.1",
                "smtp_port": 2525,
            }
        )
    )

    async def _refuse(*args: Any, **kwargs: Any) -> str:
        refused = {"recipient@example.com": (550, b"mailbox unavailable")}
        raise aiosmtplib.SMTPRecipientsRefused(refused)

    monkeypatch.setattr(adapter, "_send_raw", _refuse)
    with pytest.raises(ProviderError) as excinfo:
        await adapter.send(target=_target(), subject="x", body="y", idempotency_key="u-1")
    assert excinfo.value.permanent is True
    assert excinfo.value.category.value == "validation"


async def test_send_reads_current_settings_for_each_execution(monkeypatch: Any) -> None:
    reader = _SettingsReader(
        {
            "email_enabled": True,
            "smtp_enabled": True,
            "smtp_host": "smtp-old.example.com",
            "smtp_port": 25,
        }
    )
    adapter = SmtpEmailAdapter(settings_queries=reader)
    hosts: list[str] = []

    async def _capture(settings: SmtpSettings, *args: Any) -> str:
        hosts.append(settings.host)
        return f"{settings.host}:{settings.port}"

    monkeypatch.setattr(adapter, "_send_raw", _capture)

    await adapter.send(target=_target(), subject="x", body="y", idempotency_key="u-1")
    reader.values["smtp_host"] = "smtp-new.example.com"
    await adapter.send(target=_target(), subject="x", body="y", idempotency_key="u-2")

    assert reader.calls == 2
    assert hosts == ["smtp-old.example.com", "smtp-new.example.com"]


async def test_send_returns_unavailable_without_network_when_disabled_or_unconfigured(
    monkeypatch: Any,
) -> None:
    adapter = SmtpEmailAdapter(settings_queries=_SettingsReader({}))

    async def _unexpected(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("disabled SMTP must not touch the network")

    monkeypatch.setattr(adapter, "_send_raw", _unexpected)
    disabled = await adapter.send(target=_target(), subject="x", body="y", idempotency_key="u-1")
    assert disabled.status == "unavailable"
    assert disabled.error_category == "disabled"

    adapter = SmtpEmailAdapter(
        settings_queries=_SettingsReader({"email_enabled": True, "smtp_enabled": True})
    )
    invalid = await adapter.send(target=_target(), subject="x", body="y", idempotency_key="u-2")
    assert invalid.status == "unavailable"
    assert invalid.error_category == "configuration"


async def test_smtp_settings_group_parses_boolean_strings() -> None:
    from inc.adapters.notification.email_smtp import smtp_settings_from_group

    settings = smtp_settings_from_group(
        {
            "email_enabled": True,
            "smtp_enabled": True,
            "smtp_host": "smtp.example.com",
            "smtp_use_tls": "false",
            "smtp_starttls": "0",
        }
    )
    assert settings.use_tls is False
    assert settings.starttls is False

    settings = smtp_settings_from_group(
        {
            "email_enabled": True,
            "smtp_enabled": True,
            "smtp_host": "smtp.example.com",
            "smtp_use_tls": "true",
            "smtp_starttls": "1",
        }
    )
    assert settings.use_tls is True
    assert settings.starttls is True

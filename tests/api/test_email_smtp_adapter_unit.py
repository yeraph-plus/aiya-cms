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

    adapter = SmtpEmailAdapter(settings=SmtpSettings(host="127.0.0.1", port=2525))

    async def _refuse(*args: Any, **kwargs: Any) -> str:
        refused = {"recipient@example.com": (550, b"mailbox unavailable")}
        raise aiosmtplib.SMTPRecipientsRefused(refused)

    monkeypatch.setattr(adapter, "_send_raw", _refuse)
    with pytest.raises(ProviderError) as excinfo:
        await adapter.send(target=_target(), subject="x", body="y", idempotency_key="u-1")
    assert excinfo.value.permanent is True
    assert excinfo.value.category.value == "validation"


async def test_smtp_settings_group_parses_boolean_strings() -> None:
    from inc.adapters.notification.email_smtp import smtp_settings_from_group

    settings = smtp_settings_from_group(
        {
            "smtp_host": "smtp.example.com",
            "smtp_use_tls": "false",
            "smtp_starttls": "0",
        }
    )
    assert settings.use_tls is False
    assert settings.starttls is False

    settings = smtp_settings_from_group(
        {
            "smtp_host": "smtp.example.com",
            "smtp_use_tls": "true",
            "smtp_starttls": "1",
        }
    )
    assert settings.use_tls is True
    assert settings.starttls is True

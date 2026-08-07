"""SMTP email adapter tests against a real mailpit SMTP endpoint.

Contract source: context/spec/capabilities/notification.md §8.

Requires a mailpit instance on localhost:1025 (started ad hoc for the
integration run, e.g. ``docker run --rm -p 1025:1025 -p 8025:8025
axllent/mailpit:v1.21``). Tests skip when no SMTP endpoint is reachable so
the default suite never depends on an external service.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest

from inc.api.adapters_email import SmtpEmailAdapter, SmtpSettings
from inc.capabilities.notification.ports import (
    ProviderError,
    ProviderResult,
    RecipientTarget,
)

MAILPIT_HOST = "127.0.0.1"
MAILPIT_PORT = 2525


def _mailpit_reachable() -> bool:
    try:
        with socket.create_connection((MAILPIT_HOST, MAILPIT_PORT), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _mailpit_reachable(),
    reason="mailpit SMTP endpoint not reachable; start it ad hoc to run adapter integration",
)


def _target(address: str = "recipient@example.com") -> RecipientTarget:
    return RecipientTarget(channel="email", address=address, masked_address="re***@example.com")


async def test_smtp_send_delivers() -> None:
    adapter = SmtpEmailAdapter(
        settings=SmtpSettings(
            host=MAILPIT_HOST, port=MAILPIT_PORT, from_address="sender@example.com"
        )
    )
    result = await adapter.send(
        target=_target(),
        subject="Integration hello",
        body="body line",
        idempotency_key="delivery-1:1",
    )
    assert isinstance(result, ProviderResult)
    assert result.status == "delivered", f"{result}"
    assert result.provider_ref


async def test_smtp_connection_error_classified_transient(monkeypatch: Any) -> None:
    adapter = SmtpEmailAdapter(settings=SmtpSettings(host="127.0.0.1", port=1, timeout_seconds=2.0))

    async def _boom(*args: Any, **kwargs: Any) -> str:
        raise OSError("connection refused")

    monkeypatch.setattr(adapter, "_send_raw", _boom)
    with pytest.raises(ProviderError) as excinfo:
        await adapter.send(target=_target(), subject="x", body="y", idempotency_key="delivery-2:1")
    assert excinfo.value.permanent is False
    assert excinfo.value.retry_category.value == "transient"


async def test_smtp_auth_error_classified_permanent(monkeypatch: Any) -> None:
    import aiosmtplib

    adapter = SmtpEmailAdapter(settings=SmtpSettings(host=MAILPIT_HOST, port=MAILPIT_PORT))

    async def _boom(*args: Any, **kwargs: Any) -> str:
        raise aiosmtplib.SMTPAuthenticationError(535, b"authentication failed")

    monkeypatch.setattr(adapter, "_send_raw", _boom)
    with pytest.raises(ProviderError) as excinfo:
        await adapter.send(target=_target(), subject="x", body="y", idempotency_key="delivery-3:1")
    assert excinfo.value.permanent is True
    assert excinfo.value.retry_category.value == "permanent"

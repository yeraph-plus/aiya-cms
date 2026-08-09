"""SMTP email adapter tests against a real mailpit SMTP endpoint.

Contract source: context/spec/capabilities/notification.md §8.

Requires the mailpit container from compose.infra (host SMTP port
``MAILPIT_SMTP_PORT``, default 2525, mapped to container 1025; web UI on
``MAILPIT_UI_PORT``, default 8025). Tests skip when the endpoint does not
serve the SMTP banner, so the default suite never depends on the container.
"""

from __future__ import annotations

import os
import socket
import urllib.request
from typing import Any

import pytest

from inc.adapters.notification.email_smtp import SmtpEmailAdapter, SmtpSettings
from inc.capabilities.notification.ports import (
    ProviderError,
    ProviderResult,
    RecipientTarget,
)

MAILPIT_HOST = "127.0.0.1"
MAILPIT_SMTP_PORT = int(os.environ.get("MAILPIT_SMTP_PORT", "2525"))
MAILPIT_UI_PORT = int(os.environ.get("MAILPIT_UI_PORT", "8025"))


def _mailpit_serving() -> bool:
    """True only when the SMTP port is mapped AND mailpit is actually ready.

    The SMTP listener alone is not enough: the Docker userland proxy on
    Windows can accept the connection and delay the 220 banner for tens of
    seconds, so the reliable service check is mailpit's own readiness
    endpoint (the same probe the compose healthcheck uses).
    """
    try:
        with socket.create_connection((MAILPIT_HOST, MAILPIT_SMTP_PORT), timeout=2):
            pass
    except OSError:
        return False
    try:
        with urllib.request.urlopen(
            f"http://{MAILPIT_HOST}:{MAILPIT_UI_PORT}/readyz", timeout=2
        ) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001 - probe failures just mean "not ready"
        return False


pytestmark = pytest.mark.skipif(
    not _mailpit_serving(),
    reason="mailpit SMTP endpoint not serving; start compose.infra to run adapter integration",
)


def _target(address: str = "recipient@example.com") -> RecipientTarget:
    return RecipientTarget(channel="email", address=address, masked_address="re***@example.com")


async def test_smtp_send_delivers() -> None:
    # The Docker userland proxy on Windows can delay the SMTP banner well past
    # the adapter's default 15s timeout, so use a generous per-test timeout.
    adapter = SmtpEmailAdapter(
        settings=SmtpSettings(
            host=MAILPIT_HOST,
            port=MAILPIT_SMTP_PORT,
            from_address="sender@example.com",
            timeout_seconds=30.0,
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

    adapter = SmtpEmailAdapter(settings=SmtpSettings(host=MAILPIT_HOST, port=MAILPIT_SMTP_PORT))

    async def _boom(*args: Any, **kwargs: Any) -> str:
        raise aiosmtplib.SMTPAuthenticationError(535, b"authentication failed")

    monkeypatch.setattr(adapter, "_send_raw", _boom)
    with pytest.raises(ProviderError) as excinfo:
        await adapter.send(target=_target(), subject="x", body="y", idempotency_key="delivery-3:1")
    assert excinfo.value.permanent is True
    assert excinfo.value.retry_category.value == "permanent"

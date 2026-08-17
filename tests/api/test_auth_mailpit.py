"""Full registration-to-SMTP integration through the local Mailpit sink."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import urllib.request
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from inc.capabilities.notification import ensure_auth_templates
from inc.capabilities.notification.models import NotificationDelivery, NotificationIntent
from inc.capabilities.settings import CommandContext, UpdateSettingGroup
from inc.capabilities.settings.schemas import UpdateSettingGroupInput

MAILPIT_HOST = os.environ.get("MAILPIT_HOST", "127.0.0.1")
MAILPIT_SMTP_PORT = int(os.environ.get("MAILPIT_SMTP_PORT", "2525"))
MAILPIT_UI_PORT = int(os.environ.get("MAILPIT_UI_PORT", "8025"))


def _mailpit_ready() -> bool:
    try:
        with socket.create_connection((MAILPIT_HOST, MAILPIT_SMTP_PORT), timeout=2):
            pass
        with urllib.request.urlopen(
            f"http://{MAILPIT_HOST}:{MAILPIT_UI_PORT}/readyz", timeout=2
        ) as response:
            return response.status == 200
    except OSError:
        return False


def _fetch_messages() -> list[dict[str, Any]]:
    with urllib.request.urlopen(
        f"http://{MAILPIT_HOST}:{MAILPIT_UI_PORT}/api/v1/messages?limit=100", timeout=5
    ) as raw:
        return json.load(raw).get("messages", [])


pytestmark = pytest.mark.skipif(
    not _mailpit_ready(), reason="Mailpit SMTP/UI endpoints are not available"
)


async def test_register_delivers_verification_email_via_mailpit(
    client: Any,
) -> None:
    services = client.app.state.services
    settings_context = CommandContext(
        uow_factory=services.uow_factory,
        clock=services.clock,
        outbox=services.outbox,
        groups=services.settings_groups,
        permissions=frozenset(services.permission_registry.keys()),
        actor_id="mailpit-test",
        trace_id="mailpit-test",
    )
    await UpdateSettingGroup(settings_context)(
        "notification",
        UpdateSettingGroupInput(
            expected_version=0,
            values={
                "email_enabled": True,
                "smtp_enabled": True,
                "smtp_host": MAILPIT_HOST,
                "smtp_port": MAILPIT_SMTP_PORT,
                "smtp_from_address": "no-reply@aiya.local",
            },
        ),
    )
    await ensure_auth_templates(services.uow_factory)

    email = f"mailpit-{uuid.uuid4().hex}@example.com"
    response = await client.post(
        "/api/v1/auth/register",
        json={"username": email.split("@", 1)[0], "email": email, "password": "password-123456"},
    )
    assert response.status_code == 200, response.text

    await services.runner.run_due(workflow_key="notification.deliver.v1")

    async with services.uow_factory() as uow:
        delivery = (
            (
                await uow.session.execute(
                    select(NotificationDelivery).order_by(NotificationDelivery.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
    assert delivery is not None
    assert delivery.status == "delivered", delivery.error_summary

    async with services.uow_factory() as uow:
        intent = (
            (
                await uow.session.execute(
                    select(NotificationIntent).where(NotificationIntent.id == delivery.intent_id)
                )
            )
            .scalars()
            .one()
        )
    assert "token" not in intent.variables.values
    assert email not in str(intent.variables.values)

    messages = await asyncio.to_thread(_fetch_messages)
    recipients = [
        recipient.get("Address", "")
        for message in messages
        if message.get("Subject") == "验证邮箱"
        for recipient in message.get("To", [])
    ]
    assert email in recipients

    reset = await client.post("/api/v1/auth/password-reset/request", json={"identifier": email})
    assert reset.status_code == 202, reset.text
    await services.runner.run_due(workflow_key="notification.deliver.v1")

    messages = await asyncio.to_thread(_fetch_messages)
    reset_recipients = [
        recipient.get("Address", "")
        for message in messages
        if message.get("Subject") == "重置密码"
        for recipient in message.get("To", [])
    ]
    assert email in reset_recipients

"""Administrator notification delivery workbench HTTP contract."""

from __future__ import annotations

import uuid
from typing import Any

from inc.capabilities.notification.models import (
    IntentVariables,
    NotificationDelivery,
    NotificationDeliveryAttempt,
    NotificationIntent,
    RecipientSnapshot,
)


async def _seed_delivery(client: Any, clock: Any) -> uuid.UUID:
    services = client.app.state.services
    now = clock.utc_now()
    async with services.uow_factory() as uow:
        intent = NotificationIntent(
            spec_key="identity.verify_email",
            idempotency_key="notification-admin-test",
            recipient_type="identity",
            recipient_id="subject-1",
            variables=IntentVariables(schema_version="1", values={"token": "redacted"}),
            requested_at=now,
            state="pending",
        )
        uow.session.add(intent)
        await uow.session.flush()
        delivery = NotificationDelivery(
            intent_id=intent.id,
            channel="email",
            provider_key="email.smtp",
            recipient=RecipientSnapshot(
                channel="email",
                recipient_type="identity",
                recipient_id="subject-1",
                address_digest="digest",
                masked_address="su***@example.com",
            ),
            status="pending",
        )
        uow.session.add(delivery)
        await uow.session.flush()
        uow.session.add(
            NotificationDeliveryAttempt(
                delivery_id=delivery.id,
                delivery_attempt=1,
                provider_sequence=0,
                provider_key="email.smtp",
                status="failed",
                error_category="transient",
                error_summary="safe summary",
                started_at=now,
                finished_at=now,
            )
        )
        await uow.commit()
        return delivery.id


async def test_admin_lists_reads_cancels_and_retries_deliveries(
    client: Any,
    admin_token: str,
    clock: Any,
) -> None:
    delivery_id = await _seed_delivery(client, clock)
    headers = {"Authorization": f"Bearer {admin_token}"}

    listed = await client.get(
        "/api/v1/admin/notifications/deliveries",
        params={"status": "pending", "recipient_id": "subject-1"},
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["id"] == str(delivery_id)
    assert "token" not in listed.text

    detail = await client.get(
        f"/api/v1/admin/notifications/deliveries/{delivery_id}", headers=headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["attempts"][0]["error_summary"] == "safe summary"

    cancelled = await client.post(
        f"/api/v1/admin/notifications/deliveries/{delivery_id}/cancel", headers=headers
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    retried = await client.post(
        f"/api/v1/admin/notifications/deliveries/{delivery_id}/retry", headers=headers
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "pending"


async def test_notification_admin_boundary_and_template_reservation(
    client: Any,
    admin_token: str,
) -> None:
    assert (await client.get("/api/v1/admin/notifications/deliveries")).status_code == 401
    headers = {"Authorization": f"Bearer {admin_token}"}
    assert (
        await client.get("/api/v1/admin/notifications/templates", headers=headers)
    ).status_code == 404

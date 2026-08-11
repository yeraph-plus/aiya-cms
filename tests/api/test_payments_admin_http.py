"""Administrator payments order workbench HTTP contract."""

from __future__ import annotations

from typing import Any

from inc.capabilities.payments.commands import CommandContext, CreatePaymentOrder
from inc.capabilities.payments.schemas import CreatePaymentOrderInput


async def _create_order(client: Any, clock: Any, *, key: str = "admin-order-1") -> Any:
    services = client.app.state.services
    ctx = CommandContext(
        uow_factory=services.uow_factory,
        clock=clock,
        outbox=services.outbox,
        providers=services.payment_providers,
        permissions=frozenset({"payments.create"}),
        actor_id="test",
        trace_id="payments-admin-test",
    )
    return await CreatePaymentOrder(ctx)(
        CreatePaymentOrderInput(
            subject_type="identity",
            subject_id="buyer-1",
            provider_key="dev_fake",
            offer_key="test-offer",
            offer_version="1",
            description="Admin payment test",
            amount=1500,
            currency="CNY",
            idempotency_key=key,
        )
    )


async def test_admin_can_list_read_and_cancel_payment_orders(
    client: Any, admin_token: str, clock: Any
) -> None:
    order = await _create_order(client, clock)
    headers = {"Authorization": f"Bearer {admin_token}"}

    listed = await client.get(
        "/api/v1/admin/payments/orders",
        params={"state": "created", "subject_id": "buyer-1", "page": 1, "size": 10},
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == order.id

    detail = await client.get(f"/api/v1/admin/payments/orders/{order.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["order"]["order_reference"] == order.order_reference
    assert detail.json()["attempts"] == []
    assert detail.json()["refunds"] == []

    cancelled = await client.post(
        f"/api/v1/admin/payments/orders/{order.id}/cancel", headers=headers
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["state"] == "cancelled"


async def test_admin_payment_read_surface_requires_authentication(client: Any) -> None:
    assert (await client.get("/api/v1/admin/payments/orders")).status_code == 401

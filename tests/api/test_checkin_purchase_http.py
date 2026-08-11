"""Check-in and point-purchase HTTP integration tests.

Contract source: context/spec/features.md §4.3/§4.4,
context/spec/capabilities/payments.md §6, http-openapi.md §6/§8.

The cms manifest assembles points/payments with the dev_fake provider;
workers are disabled in tests, so workflow progression is driven with
``runner.run_due()`` after the webhook bridge delivers signals.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest


@pytest.fixture
async def program(uow_factory: Any) -> None:
    from inc.capabilities.points.models import PointsProgram

    async with uow_factory() as uow:
        uow.session.add(
            PointsProgram(
                program_key="credit", display_name="Credit", unit="points", status="active"
            )
        )
        await uow.commit()


async def _register_and_token(client: Any, uow_factory: Any, clock: Any, username: str) -> str:
    from inc.capabilities.identity.commands import (
        CommandContext as IdentityCommandContext,
    )
    from inc.capabilities.identity.commands import (
        RegisterLocalUser,
    )
    from tests.api.conftest import _mint_token_for

    services = client.app.state.services
    identity_ctx = IdentityCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        hasher=services.hasher,
        outbox=services.outbox,
        audit_actor_id="system",
        audit_trace_id="test",
    )
    result = await RegisterLocalUser(identity_ctx)(
        username=username,
        email=f"{username}@example.com",
        password="password-123456",
    )
    return await _mint_token_for(services, result.subject.id)


async def _drive_workflows(client: Any, clock: Any, rounds: int = 4) -> None:
    runner = client.app.state.services.runner
    for _ in range(rounds):
        clock.advance(timedelta(seconds=1))
        await runner.run_due()


async def _balance(client: Any, token: str) -> int:
    response = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    return response.json()["points"]["balance"]


async def test_check_in_rewards_once_per_business_day(
    client: Any, uow_factory: Any, clock: Any, program: None
) -> None:
    token = await _register_and_token(client, uow_factory, clock, "checker")
    headers = {"Authorization": f"Bearer {token}"}

    first = await client.post("/api/v1/check-in", headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "rewarded"
    assert first.json()["balance"] == 10

    second = await client.post("/api/v1/check-in", headers=headers)
    assert second.status_code == 200
    assert second.json()["status"] == "already_rewarded"
    assert second.json()["balance"] == 10

    assert await _balance(client, token) == 10


async def test_check_in_requires_authentication(client: Any, program: None) -> None:
    assert (await client.post("/api/v1/check-in")).status_code == 401
    assert (await client.get("/api/v1/me")).status_code == 401


async def test_purchase_capture_credits_points_exactly_once(
    client: Any, uow_factory: Any, clock: Any, program: None
) -> None:
    from inc.adapters.payments.dev_fake import build_event, sign_webhook

    token = await _register_and_token(client, uow_factory, clock, "buyer")
    headers = {"Authorization": f"Bearer {token}"}

    offers = await client.get("/api/v1/point-purchase/offers", headers=headers)
    assert offers.status_code == 200
    offer = next(o for o in offers.json()["items"] if o["offer_key"] == "points_pack_100")
    assert offer["amount"] == 1000 and offer["currency"] == "CNY"
    assert offer["points_amount"] == 100

    created = await client.post(
        "/api/v1/point-purchase/orders",
        json={"offer_key": "points_pack_100"},
        headers={**headers, "Idempotency-Key": "order-1"},
    )
    assert created.status_code == 200, created.text
    purchase = created.json()
    assert purchase["order_reference"]
    assert purchase["checkout_url"]
    assert purchase["state"] == "pending"

    # same idempotency key replays the original result
    replay = await client.post(
        "/api/v1/point-purchase/orders",
        json={"offer_key": "points_pack_100"},
        headers={**headers, "Idempotency-Key": "order-1"},
    )
    assert replay.status_code == 200
    assert replay.json()["order_reference"] == purchase["order_reference"]

    body = build_event(
        event_id="evt-cap-1",
        event_type="capture",
        order_reference=purchase["order_reference"],
        amount=1000,
    )
    webhook = await client.post(
        "/api/v1/webhooks/payments/dev_fake",
        content=body,
        headers={"X-Signature": sign_webhook(body)},
    )
    assert webhook.status_code == 200, webhook.text
    assert webhook.json()["received"] is True
    assert webhook.json()["duplicate"] is False

    await _drive_workflows(client, clock)
    assert await _balance(client, token) == 100

    # provider retry: same event id is a deduped duplicate, no double credit
    again = await client.post(
        "/api/v1/webhooks/payments/dev_fake",
        content=body,
        headers={"X-Signature": sign_webhook(body)},
    )
    assert again.status_code == 200
    assert again.json()["duplicate"] is True
    await _drive_workflows(client, clock)
    assert await _balance(client, token) == 100


async def test_purchase_refund_reverses_points(
    client: Any, admin_token: str, uow_factory: Any, clock: Any, program: None
) -> None:
    from inc.adapters.payments.dev_fake import build_event, sign_webhook

    token = await _register_and_token(client, uow_factory, clock, "refundee")
    headers = {"Authorization": f"Bearer {token}"}
    created = await client.post(
        "/api/v1/point-purchase/orders",
        json={"offer_key": "points_pack_100"},
        headers={**headers, "Idempotency-Key": "order-refund-1"},
    )
    purchase = created.json()
    body = build_event(
        event_id="evt-cap-refund",
        event_type="capture",
        order_reference=purchase["order_reference"],
        amount=1000,
    )
    await client.post(
        "/api/v1/webhooks/payments/dev_fake",
        content=body,
        headers={"X-Signature": sign_webhook(body)},
    )
    await _drive_workflows(client, clock)
    assert await _balance(client, token) == 100

    services = client.app.state.services
    order = await services.payments_queries.get_order_by_reference(purchase["order_reference"])
    refund = await client.post(
        f"/api/v1/admin/payments/orders/{order.id}/refund",
        json={"amount": 1000, "reason": "user request", "idempotency_key": "refund-1"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert refund.status_code == 200, refund.text
    assert refund.json()["state"] == "pending"

    refund_event = build_event(
        event_id="evt-ref-1",
        event_type="refund",
        order_reference=purchase["order_reference"],
        amount=1000,
    )
    completed = await client.post(
        "/api/v1/webhooks/payments/dev_fake",
        content=refund_event,
        headers={"X-Signature": sign_webhook(refund_event)},
    )
    assert completed.status_code == 200, completed.text
    await _drive_workflows(client, clock)
    assert await _balance(client, token) == 0

    state = await services.payments_queries.get_order_by_reference(purchase["order_reference"])
    assert state is not None and state.state == "refunded"


async def test_webhook_bad_signature_and_unknown_provider_rejected(
    client: Any, program: None
) -> None:
    from inc.adapters.payments.dev_fake import build_event

    body = build_event(
        event_id="evt-bad", event_type="capture", order_reference="whatever", amount=1
    )
    bad = await client.post(
        "/api/v1/webhooks/payments/dev_fake",
        content=body,
        headers={"X-Signature": "0" * 64},
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "payments.webhook_invalid"

    unknown = await client.post(
        "/api/v1/webhooks/payments/ghost",
        content=body,
        headers={"X-Signature": "0" * 64},
    )
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "payments.unknown_provider"


async def test_purchase_requires_auth_idempotency_and_known_offer(
    client: Any, uow_factory: Any, clock: Any, program: None
) -> None:
    token = await _register_and_token(client, uow_factory, clock, "buyer2")
    headers = {"Authorization": f"Bearer {token}"}

    assert (
        await client.post(
            "/api/v1/point-purchase/orders",
            json={"offer_key": "points_pack_100"},
            headers={"Idempotency-Key": "k1"},
        )
    ).status_code == 401

    missing_key = await client.post(
        "/api/v1/point-purchase/orders",
        json={"offer_key": "points_pack_100"},
        headers=headers,
    )
    assert missing_key.status_code == 422

    unknown_offer = await client.post(
        "/api/v1/point-purchase/orders",
        json={"offer_key": "nope"},
        headers={**headers, "Idempotency-Key": "k2"},
    )
    assert unknown_offer.status_code == 422
    assert unknown_offer.json()["code"] == "pointpurchase.unknown_offer"

    me = await client.get("/api/v1/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["points"]["balance"] == 0


async def test_payments_capability_requires_provider_port(uow_factory: Any, clock: Any) -> None:
    from inc.api.config import ApiSettings
    from inc.api.container import build_container
    from inc.kernel.boot import AppManifest
    from inc.kernel.errors import KernelError

    manifest = AppManifest(name="bad", capabilities=("payments",))
    with pytest.raises(KernelError) as excinfo:
        build_container(
            manifest=manifest, uow_factory=uow_factory, clock=clock, settings=ApiSettings()
        )
    assert excinfo.value.code == "kernel.port_unbound"


async def test_dev_fake_provider_denied_in_production(uow_factory: Any, clock: Any) -> None:
    from inc.api.config import ApiSettings
    from inc.api.container import build_container
    from inc.api.manifest import cms
    from inc.kernel.errors import KernelError

    settings = ApiSettings(
        issuer="https://testserver",
        environment="production",
        secure_cookies=True,
    )
    with pytest.raises(KernelError) as excinfo:
        build_container(manifest=cms, uow_factory=uow_factory, clock=clock, settings=settings)
    assert excinfo.value.code == "kernel.adapter_production_denied"

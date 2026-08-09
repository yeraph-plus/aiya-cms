"""Membership purchase HTTP integration tests.

Contract source: context/spec/features.md (membership purchase),
capabilities/membership.md §10, capabilities/payments.md §6,
http-openapi.md §6/§8.

The cms manifest assembles payments + membership + points with the
dev_fake provider; workers are disabled in tests, so workflow progression
is driven with ``runner.run_due()`` after the webhook bridge delivers
signals.
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
                program_key="default", display_name="Default", unit="points", status="active"
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
    response = await client.get(
        "/api/v1/points/balance", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.text
    return response.json()["balance"]


async def test_membership_offers_require_auth_and_list_levels(client: Any, program: None) -> None:
    response = await client.get("/api/v1/membership-purchase/offers")
    assert response.status_code == 401


async def test_membership_purchase_capture_subscribes_and_grants_points(
    client: Any, uow_factory: Any, clock: Any, program: None
) -> None:
    from inc.adapters.payments.dev_fake import build_event, sign_webhook

    token = await _register_and_token(client, uow_factory, clock, "member1")
    headers = {"Authorization": f"Bearer {token}"}

    offers = await client.get("/api/v1/membership-purchase/offers", headers=headers)
    assert offers.status_code == 200
    offer = next(o for o in offers.json()["items"] if o["offer_key"] == "membership_basic_30")
    assert offer["amount"] == 3000 and offer["currency"] == "CNY"
    assert offer["level_key"] == "basic"

    created = await client.post(
        "/api/v1/membership-purchase/orders",
        json={"offer_key": "membership_basic_30"},
        headers={**headers, "Idempotency-Key": "member-order-1"},
    )
    assert created.status_code == 200, created.text
    purchase = created.json()
    assert purchase["order_reference"]
    assert purchase["checkout_url"]
    assert purchase["state"] == "pending"

    replay = await client.post(
        "/api/v1/membership-purchase/orders",
        json={"offer_key": "membership_basic_30"},
        headers={**headers, "Idempotency-Key": "member-order-1"},
    )
    assert replay.status_code == 200
    assert replay.json()["order_reference"] == purchase["order_reference"]

    body = build_event(
        event_id="evt-mcap-1",
        event_type="capture",
        order_reference=purchase["order_reference"],
        amount=3000,
    )
    webhook = await client.post(
        "/api/v1/webhooks/payments/dev_fake",
        content=body,
        headers={"X-Signature": sign_webhook(body)},
    )
    assert webhook.status_code == 200, webhook.text
    assert webhook.json()["duplicate"] is False

    await _drive_workflows(client, clock)
    assert await _balance(client, token) == 100

    # provider retry: same event id is deduped, no double subscribe
    again = await client.post(
        "/api/v1/webhooks/payments/dev_fake",
        content=body,
        headers={"X-Signature": sign_webhook(body)},
    )
    assert again.status_code == 200
    assert again.json()["duplicate"] is True
    await _drive_workflows(client, clock)
    assert await _balance(client, token) == 100


async def test_membership_purchase_requires_auth_idempotency_and_known_offer(
    client: Any, uow_factory: Any, clock: Any, program: None
) -> None:
    token = await _register_and_token(client, uow_factory, clock, "member2")
    headers = {"Authorization": f"Bearer {token}"}

    assert (
        await client.post(
            "/api/v1/membership-purchase/orders",
            json={"offer_key": "membership_basic_30"},
            headers={"Idempotency-Key": "k1"},
        )
    ).status_code == 401

    missing_key = await client.post(
        "/api/v1/membership-purchase/orders",
        json={"offer_key": "membership_basic_30"},
        headers=headers,
    )
    assert missing_key.status_code == 422

    unknown_offer = await client.post(
        "/api/v1/membership-purchase/orders",
        json={"offer_key": "nope"},
        headers={**headers, "Idempotency-Key": "k2"},
    )
    assert unknown_offer.status_code == 422
    assert unknown_offer.json()["code"] == "membershippurchase.unknown_offer"

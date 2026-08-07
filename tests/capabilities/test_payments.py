"""Payments capability tests.

Contract source: context/spec/capabilities/payments.md §10.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import select

from inc.capabilities.payments.commands import (
    CancelPaymentOrder,
    CommandContext,
    CreatePaymentOrder,
    ProcessVerifiedWebhook,
    ReconcilePaymentOrder,
    RequestRefund,
    StartPaymentAttempt,
)
from inc.capabilities.payments.diagnostics import PaymentsDiagnostics
from inc.capabilities.payments.models import PaymentOrder, PaymentWebhookReceipt
from inc.capabilities.payments.ports import (
    PaymentStatus,
    ProviderRefund,
    ProviderSession,
    WebhookEvent,
    WebhookVerificationError,
)
from inc.capabilities.payments.schemas import (
    PAYMENT_EVENT_SCHEMAS,
    CreatePaymentOrderInput,
    RequestRefundInput,
)
from inc.kernel.db import UoWFactory
from inc.kernel.errors import KernelError
from inc.kernel.events import EventSchemaRegistry, OutboxMessage, OutboxWriter

SECRET = "test-webhook-secret"


@dataclass
class FakePaymentProvider:
    key: str = "fake"
    statuses: dict[str, PaymentStatus] = field(default_factory=dict)
    refund_states: dict[str, str] = field(default_factory=dict)
    captured_ref: str | None = None

    def _sign(self, body: bytes) -> str:
        return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()

    def webhook(
        self, *, event_id: str, event_type: str, order_reference: str, amount: int = 1000
    ) -> bytes:
        payload = {
            "id": event_id,
            "type": event_type,
            "order_reference": order_reference,
            "amount": amount,
            "currency": "USD",
        }
        return json.dumps(payload).encode()

    def webhook_headers(self, body: bytes) -> dict[str, str]:
        return {"X-Signature": self._sign(body)}

    async def create_payment(self, **kwargs: Any) -> ProviderSession:
        return ProviderSession(
            provider_ref=f"pay_{kwargs['order_reference'][-8:]}", url="https://pay.example/checkout"
        )

    async def get_payment(self, *, provider_ref: str) -> PaymentStatus:
        return self.statuses.get(provider_ref, PaymentStatus(state="pending"))

    async def verify_webhook(
        self, *, raw_body: bytes, headers: dict[str, str], secret: str
    ) -> WebhookEvent:
        signature = headers.get("X-Signature", "")
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise WebhookVerificationError("bad signature")
        payload = json.loads(raw_body)
        return WebhookEvent(
            event_id=payload["id"],
            event_type=payload["type"],
            order_reference=payload["order_reference"],
            amount=payload["amount"],
            currency=payload["currency"],
        )

    async def create_refund(self, **kwargs: Any) -> ProviderRefund:
        return ProviderRefund(refund_ref=f"ref_{kwargs['idempotency_key'][-8:]}", state="completed")

    async def get_refund(self, *, refund_ref: str) -> ProviderRefund:
        return ProviderRefund(
            refund_ref=refund_ref, state=self.refund_states.get(refund_ref, "completed")
        )


@pytest.fixture
def provider() -> FakePaymentProvider:
    return FakePaymentProvider()


@pytest.fixture
def schema_registry() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    for key, schema in PAYMENT_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    return registry


@pytest.fixture
def ctx(
    uow_factory: UoWFactory,
    clock: Any,
    provider: FakePaymentProvider,
    schema_registry: EventSchemaRegistry,
) -> CommandContext:
    return CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        providers={"fake": provider},
        permissions=frozenset(
            {"payments.create", "payments.cancel", "payments.refund", "payments.reconcile"}
        ),
        actor_id="admin-1",
        trace_id="trace-1",
    )


def order_input(**overrides: Any) -> CreatePaymentOrderInput:
    base = {
        "subject_type": "identity",
        "subject_id": "user-1",
        "provider_key": "fake",
        "offer_key": "points_pack_100",
        "offer_version": "1",
        "description": "100 points",
        "amount": 1000,
        "currency": "USD",
        "idempotency_key": "order-key-1",
    }
    base.update(overrides)
    return CreatePaymentOrderInput(**base)


async def create_order(ctx: CommandContext, **overrides: Any) -> Any:
    return await CreatePaymentOrder(ctx)(order_input(**overrides))


# --- order creation -------------------------------------------------------


async def test_create_order_is_idempotent_and_unguessable(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    first = await create_order(ctx)
    second = await create_order(ctx)
    assert first.id == second.id
    assert first.order_reference.startswith("ord_")
    assert len(first.order_reference) > 12
    async with uow_factory() as uow:
        rows = (await uow.session.execute(select(PaymentOrder))).scalars().all()
    assert len(rows) == 1


async def test_unknown_provider_is_validation_error(ctx: CommandContext) -> None:
    with pytest.raises(KernelError) as excinfo:
        await create_order(ctx, provider_key="nope")
    assert excinfo.value.code == "payments.unknown_provider"


# --- attempt --------------------------------------------------------------


async def test_start_attempt_moves_order_to_pending(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    order = await create_order(ctx)
    result = await StartPaymentAttempt(ctx)(uuid.UUID(order.id))
    assert result.checkout_url.startswith("https://")
    assert result.order.state == "pending"
    async with uow_factory() as uow:
        row = await uow.session.get(PaymentOrder, uuid.UUID(order.id))
        assert row is not None and row.provider_ref is not None


async def test_cancel_created_order(ctx: CommandContext) -> None:
    order = await create_order(ctx)
    cancelled = await CancelPaymentOrder(ctx)(uuid.UUID(order.id))
    assert cancelled.state == "cancelled"


# --- webhook --------------------------------------------------------------


async def test_capture_via_verified_webhook(
    ctx: CommandContext, uow_factory: UoWFactory, provider: FakePaymentProvider
) -> None:
    order = await create_order(ctx)
    await StartPaymentAttempt(ctx)(uuid.UUID(order.id))
    body = provider.webhook(
        event_id="evt-1", event_type="capture", order_reference=order.order_reference
    )
    result = await ProcessVerifiedWebhook(ctx)(
        provider_key="fake", raw_body=body, headers=provider.webhook_headers(body), secret=SECRET
    )
    assert result["duplicate"] is False
    async with uow_factory() as uow:
        row = await uow.session.get(PaymentOrder, uuid.UUID(order.id))
        assert row is not None and row.state == "captured"
        assert row.captured_amount == 1000
        events = (
            (
                await uow.session.execute(
                    select(OutboxMessage).where(OutboxMessage.event_key == "payment.captured.v1")
                )
            )
            .scalars()
            .all()
        )
    assert len(events) == 1  # captured event committed atomically


async def test_forged_signature_rejected(
    ctx: CommandContext, provider: FakePaymentProvider
) -> None:
    body = provider.webhook(event_id="evt-x", event_type="capture", order_reference="ord_whatever")
    headers = {"X-Signature": "forged"}
    with pytest.raises(WebhookVerificationError):
        await ProcessVerifiedWebhook(ctx)(
            provider_key="fake", raw_body=body, headers=headers, secret=SECRET
        )


async def test_webhook_replay_is_idempotent(
    ctx: CommandContext, uow_factory: UoWFactory, provider: FakePaymentProvider
) -> None:
    order = await create_order(ctx)
    await StartPaymentAttempt(ctx)(uuid.UUID(order.id))
    body = provider.webhook(
        event_id="evt-2", event_type="capture", order_reference=order.order_reference
    )
    headers = provider.webhook_headers(body)
    await ProcessVerifiedWebhook(ctx)(
        provider_key="fake", raw_body=body, headers=headers, secret=SECRET
    )
    replay = await ProcessVerifiedWebhook(ctx)(
        provider_key="fake", raw_body=body, headers=headers, secret=SECRET
    )
    assert replay["duplicate"] is True
    async with uow_factory() as uow:
        receipts = (await uow.session.execute(select(PaymentWebhookReceipt))).scalars().all()
        orders = (await uow.session.execute(select(PaymentOrder))).scalars().all()
        captured_events = (
            (
                await uow.session.execute(
                    select(OutboxMessage).where(OutboxMessage.event_key == "payment.captured.v1")
                )
            )
            .scalars()
            .all()
        )
    assert len(receipts) == 1
    assert len(orders) == 1
    assert len(captured_events) == 1  # single fact


async def test_amount_mismatch_webhook_rejected(
    ctx: CommandContext, provider: FakePaymentProvider
) -> None:
    order = await create_order(ctx)
    body = provider.webhook(
        event_id="evt-3", event_type="capture", order_reference=order.order_reference, amount=999
    )
    with pytest.raises(KernelError) as excinfo:
        await ProcessVerifiedWebhook(ctx)(
            provider_key="fake",
            raw_body=body,
            headers=provider.webhook_headers(body),
            secret=SECRET,
        )
    assert excinfo.value.code == "payments.amount_mismatch"


async def test_out_of_order_failure_after_capture_rejected(
    ctx: CommandContext, uow_factory: UoWFactory, provider: FakePaymentProvider
) -> None:
    order = await create_order(ctx)
    await StartPaymentAttempt(ctx)(uuid.UUID(order.id))
    body = provider.webhook(
        event_id="evt-4", event_type="capture", order_reference=order.order_reference
    )
    await ProcessVerifiedWebhook(ctx)(
        provider_key="fake", raw_body=body, headers=provider.webhook_headers(body), secret=SECRET
    )
    failure = provider.webhook(
        event_id="evt-5", event_type="failure", order_reference=order.order_reference
    )
    with pytest.raises(KernelError) as excinfo:
        await ProcessVerifiedWebhook(ctx)(
            provider_key="fake",
            raw_body=failure,
            headers=provider.webhook_headers(failure),
            secret=SECRET,
        )
    assert excinfo.value.code == "payments.invalid_transition"


async def test_reconcile_unknown_never_guesses_captured(
    ctx: CommandContext, provider: FakePaymentProvider
) -> None:
    order = await create_order(ctx)
    await StartPaymentAttempt(ctx)(uuid.UUID(order.id))
    provider.statuses[order.order_reference and f"pay_{order.order_reference[-8:]}"] = (
        PaymentStatus(state="unknown")
    )
    reconciled = await ReconcilePaymentOrder(ctx)(uuid.UUID(order.id))
    assert reconciled.state == "pending"  # stays; no guessing
    provider.statuses[f"pay_{order.order_reference[-8:]}"] = PaymentStatus(
        state="captured", captured_amount=1000, currency="USD"
    )
    reconciled = await ReconcilePaymentOrder(ctx)(uuid.UUID(order.id))
    assert reconciled.state == "captured"


# --- refunds --------------------------------------------------------------


async def test_refund_flow_and_partial_state(
    ctx: CommandContext, provider: FakePaymentProvider
) -> None:
    order = await create_order(ctx)
    await StartPaymentAttempt(ctx)(uuid.UUID(order.id))
    body = provider.webhook(
        event_id="evt-6", event_type="capture", order_reference=order.order_reference
    )
    await ProcessVerifiedWebhook(ctx)(
        provider_key="fake", raw_body=body, headers=provider.webhook_headers(body), secret=SECRET
    )
    partial = await RequestRefund(ctx)(
        uuid.UUID(order.id),
        RequestRefundInput(amount=400, reason="partial", idempotency_key="ref-1"),
    )
    assert partial.state == "completed"
    order_dto = await ReconcilePaymentOrder(ctx)(uuid.UUID(order.id))
    assert order_dto.state == "partially_refunded"
    # refund above captured amount is refused
    with pytest.raises(KernelError) as excinfo:
        await RequestRefund(ctx)(
            uuid.UUID(order.id),
            RequestRefundInput(amount=700, reason="too much", idempotency_key="ref-2"),
        )
    assert excinfo.value.code == "payments.refund_exceeds_captured"


async def test_refund_is_idempotent(ctx: CommandContext, provider: FakePaymentProvider) -> None:
    order = await create_order(ctx)
    await StartPaymentAttempt(ctx)(uuid.UUID(order.id))
    body = provider.webhook(
        event_id="evt-7", event_type="capture", order_reference=order.order_reference
    )
    await ProcessVerifiedWebhook(ctx)(
        provider_key="fake", raw_body=body, headers=provider.webhook_headers(body), secret=SECRET
    )
    first = await RequestRefund(ctx)(
        uuid.UUID(order.id), RequestRefundInput(amount=1000, reason="full", idempotency_key="ref-3")
    )
    second = await RequestRefund(ctx)(
        uuid.UUID(order.id), RequestRefundInput(amount=1000, reason="full", idempotency_key="ref-3")
    )
    assert first.id == second.id
    assert first.state == "completed"
    order_dto = await ReconcilePaymentOrder(ctx)(uuid.UUID(order.id))
    assert order_dto.state == "refunded"


# --- diagnostics ----------------------------------------------------------


async def test_diagnostics_report_only(
    ctx: CommandContext, uow_factory: UoWFactory, clock: Any
) -> None:
    diagnostics = PaymentsDiagnostics(uow_factory=uow_factory, clock=clock)
    results = await diagnostics.run()
    codes = {r.code: r.status.value for r in results}
    assert codes["payments.stale_orders"] == "ok"
    assert codes["payments.captured_amount_mismatch"] == "ok"
    assert codes["payments.stale_refunds"] == "ok"
    assert codes["payments.orphan_webhooks"] == "ok"

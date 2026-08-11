"""Point purchase and check-in feature workflow tests.

Contract source: context/spec/features.md §4.3/§4.4, payments.md §10,
points.md §8.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from inc.capabilities.payments.commands import (
    CommandContext as PaymentsCommandContext,
)
from inc.capabilities.payments.commands import (
    ProcessVerifiedWebhook,
)
from inc.capabilities.payments.models import PaymentOrder
from inc.capabilities.payments.ports import (
    PaymentStatus,
    ProviderRefund,
    ProviderSession,
    WebhookEvent,
    WebhookVerificationError,
)
from inc.capabilities.payments.queries import PaymentsQueries
from inc.capabilities.payments.schemas import PAYMENT_EVENT_SCHEMAS
from inc.capabilities.points.behaviors import PointBehaviorRegistry
from inc.capabilities.points.commands import CommandContext as PointsCommandContext
from inc.capabilities.points.commands import OpenPointsAccount
from inc.capabilities.points.events import POINTS_EVENT_SCHEMAS
from inc.capabilities.points.models import PointsProgram
from inc.capabilities.points.queries import PointsQueries
from inc.features.check_in.workflows import (
    CHECK_IN_WORKFLOW_KEY,
    CheckInContext,
    build_check_in_workflow_spec,
)
from inc.features.point_purchase.workflows import (
    CAPTURE_SIGNAL,
    PURCHASE_WORKFLOW_KEY,
    REFUND_SIGNAL,
    REFUND_WORKFLOW_KEY,
    PointPurchaseContext,
    build_purchase_workflow_spec,
    build_refund_workflow_spec,
)
from inc.kernel.db import UoWFactory
from inc.kernel.events import EventSchemaRegistry, OutboxWriter
from inc.kernel.workflow import WorkflowRegistry, WorkflowRunner


@dataclass
class FakePayProvider:
    key: str = "fake"
    statuses: dict[str, PaymentStatus] = field(default_factory=dict)

    def sign(self, body: bytes) -> str:
        return hmac.new(b"secret", body, hashlib.sha256).hexdigest()

    def webhook(
        self, event_id: str, order_reference: str, *, amount: int = 1000, currency: str = "CNY"
    ) -> bytes:
        return json.dumps(
            {
                "id": event_id,
                "type": "capture",
                "order_reference": order_reference,
                "amount": amount,
                "currency": currency,
            }
        ).encode()

    async def create_payment(self, **kwargs: Any) -> ProviderSession:
        return ProviderSession(
            provider_ref=f"pay_{uuid.uuid4().hex[:8]}", url="https://pay.example/x"
        )

    async def get_payment(self, *, provider_ref: str) -> PaymentStatus:
        return self.statuses.get(provider_ref, PaymentStatus(state="pending"))

    async def verify_webhook(
        self, *, raw_body: bytes, headers: dict[str, str], secret: str
    ) -> WebhookEvent:
        if not hmac.compare_digest(headers.get("X-Signature", ""), self.sign(raw_body)):
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
        return ProviderRefund(refund_ref=f"ref_{uuid.uuid4().hex[:8]}", state="completed")

    async def get_refund(self, *, refund_ref: str) -> ProviderRefund:
        return ProviderRefund(refund_ref=refund_ref, state="completed")


@pytest.fixture
def behaviors() -> PointBehaviorRegistry:
    from inc.features.check_in.definition import behavior_specs as check_in_specs
    from inc.features.point_purchase.definition import behavior_specs as purchase_specs

    registry = PointBehaviorRegistry()
    for spec in (*check_in_specs, *purchase_specs):
        registry.register(spec)
    return registry


@pytest.fixture
def schema_registry() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    for key, schema in POINTS_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    for key, schema in PAYMENT_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    return registry


@pytest.fixture
async def harness(
    uow_factory: UoWFactory,
    clock: Any,
    behaviors: PointBehaviorRegistry,
    schema_registry: EventSchemaRegistry,
) -> dict[str, Any]:
    async with uow_factory() as uow:
        uow.session.add(
            PointsProgram(
                program_key="credit", display_name="Credit", unit="points", status="active"
            )
        )
        await uow.commit()

    outbox = OutboxWriter(schema_registry, clock)
    provider = FakePayProvider()
    registry = WorkflowRegistry()
    runner = WorkflowRunner(uow_factory=uow_factory, registry=registry, clock=clock)

    payments_ctx = PaymentsCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=outbox,
        providers={"fake": provider},
        permissions=frozenset(
            {"payments.create", "payments.cancel", "payments.refund", "payments.reconcile"}
        ),
        actor_id="feature",
        trace_id="point-purchase",
    )
    points_ctx = PointsCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=outbox,
        behaviors=behaviors,
        permissions=frozenset(),
        actor_id="feature",
        trace_id="point-purchase",
    )
    points_queries = PointsQueries(uow_factory=uow_factory, behaviors=behaviors)
    payments_queries = PaymentsQueries(uow_factory=uow_factory)
    purchase_ctx = PointPurchaseContext(
        payments_ctx=payments_ctx,
        points_ctx=points_ctx,
        points_queries=points_queries,
        payments_queries=payments_queries,
    )
    registry.register(build_purchase_workflow_spec(ctx=purchase_ctx))
    registry.register(build_refund_workflow_spec(ctx=purchase_ctx))
    registry.register(
        build_check_in_workflow_spec(ctx=CheckInContext(points_ctx=points_ctx, clock=clock))
    )
    return {
        "runner": runner,
        "provider": provider,
        "points_ctx": points_ctx,
        "payments_ctx": payments_ctx,
        "registry": registry,
        "clock": clock,
        "uow_factory": uow_factory,
    }


async def open_account(harness: dict[str, Any]) -> None:
    await OpenPointsAccount(harness["points_ctx"])(
        program_key="credit", subject_type="identity", subject_id="user-1"
    )


async def _balance(harness: dict[str, Any]) -> int:
    queries = PointsQueries(
        uow_factory=harness["uow_factory"], behaviors=harness["points_ctx"].behaviors
    )
    result = await queries.get_balance(
        program_key="credit", subject_type="identity", subject_id="user-1"
    )
    return result.balance


# --- check-in -------------------------------------------------------------


async def test_check_in_rewards_once_per_business_day(harness: dict[str, Any], clock: Any) -> None:
    await open_account(harness)
    instance = await harness["runner"].start(
        workflow_key=CHECK_IN_WORKFLOW_KEY,
        idempotency_key="checkin:user-1:credit:2026-01-01",
        input_data={
            "subject_type": "identity",
            "subject_id": "user-1",
            "source_id": "check-in-ui",
            "program_key": "credit",
            "business_date": "2026-01-01",
        },
        trace_id="check-in",
    )
    await harness["runner"].run_due()
    assert await _balance(harness) == 10

    # concurrent duplicate check-in with the same idempotency key
    duplicate = await harness["runner"].start(
        workflow_key=CHECK_IN_WORKFLOW_KEY,
        idempotency_key="checkin:user-1:credit:2026-01-01",
        input_data={
            "subject_type": "identity",
            "subject_id": "user-1",
            "source_id": "check-in-ui",
            "program_key": "credit",
            "business_date": "2026-01-01",
        },
        trace_id="check-in",
    )
    assert duplicate.id == instance.id
    await harness["runner"].run_due()
    assert await _balance(harness) == 10  # exactly one reward

    # a new business day allows the next reward
    clock.advance(timedelta(days=1))
    await harness["runner"].start(
        workflow_key=CHECK_IN_WORKFLOW_KEY,
        idempotency_key="checkin:user-1:credit:2026-01-02",
        input_data={
            "subject_type": "identity",
            "subject_id": "user-1",
            "source_id": "check-in-ui",
            "program_key": "credit",
            "business_date": "2026-01-02",
        },
        trace_id="check-in",
    )
    await harness["runner"].run_due()
    assert await _balance(harness) == 20


# --- point purchase -------------------------------------------------------


async def _start_purchase(harness: dict[str, Any]) -> Any:
    return await harness["runner"].start(
        workflow_key=PURCHASE_WORKFLOW_KEY,
        idempotency_key="purchase:order-1",
        input_data={
            "subject_type": "identity",
            "subject_id": "user-1",
            "provider_key": "fake",
            "offer_key": "points_pack_100",
            "idempotency_key": "order-1",
        },
        trace_id="point-purchase",
    )


async def test_purchase_credits_points_after_capture_signal(
    harness: dict[str, Any], clock: Any
) -> None:
    await open_account(harness)
    instance = await _start_purchase(harness)
    await harness["runner"].run_due()
    # drive until waiting
    clock.advance(timedelta(seconds=1))
    await harness["runner"].run_due()
    clock.advance(timedelta(seconds=1))
    await harness["runner"].run_due()
    from inc.kernel.workflow.models import WorkflowInstance

    async with harness["uow_factory"]() as uow:
        fresh = (
            (
                await uow.session.execute(
                    select(WorkflowInstance).where(WorkflowInstance.id == instance.id)
                )
            )
            .scalars()
            .first()
        )
    assert fresh is not None and fresh.status == "waiting"

    # resolve the order created by the workflow, then deliver the capture signal
    async with harness["uow_factory"]() as uow:
        order = (await uow.session.execute(select(PaymentOrder))).scalars().first()
    assert order is not None and order.state == "pending"

    provider = harness["provider"]
    body = provider.webhook("evt-capture-1", order.order_reference)
    await ProcessVerifiedWebhook(harness["payments_ctx"])(
        provider_key="fake",
        raw_body=body,
        headers={"X-Signature": provider.sign(body)},
        secret="secret",
    )
    await harness["runner"].deliver_signal(
        workflow_id=instance.id, signal_key=CAPTURE_SIGNAL, payload={"approved": True}
    )
    clock.advance(timedelta(seconds=1))
    await harness["runner"].run_due()
    clock.advance(timedelta(seconds=1))
    await harness["runner"].run_due()
    async with harness["uow_factory"]() as uow:
        order = (await uow.session.execute(select(PaymentOrder))).scalars().first()
        assert order is not None and order.state == "captured"
    assert await _balance(harness) == 100


async def test_duplicate_capture_signal_credits_once(harness: dict[str, Any], clock: Any) -> None:
    await open_account(harness)
    instance = await _start_purchase(harness)
    for _ in range(4):
        clock.advance(timedelta(seconds=1))
        await harness["runner"].run_due()
    from inc.kernel.workflow.models import WorkflowInstance

    async with harness["uow_factory"]() as uow:
        fresh = (
            (
                await uow.session.execute(
                    select(WorkflowInstance).where(WorkflowInstance.id == instance.id)
                )
            )
            .scalars()
            .first()
        )
    order = None
    async with harness["uow_factory"]() as uow:
        order = (await uow.session.execute(select(PaymentOrder))).scalars().first()
    provider = harness["provider"]
    body = provider.webhook("evt-capture-2", order.order_reference)
    await ProcessVerifiedWebhook(harness["payments_ctx"])(
        provider_key="fake",
        raw_body=body,
        headers={"X-Signature": provider.sign(body)},
        secret="secret",
    )
    await harness["runner"].deliver_signal(
        workflow_id=fresh.id, signal_key=CAPTURE_SIGNAL, payload={}
    )
    await harness["runner"].run_due()
    first = await _balance(harness)
    # a replay of the same signal on a completed workflow is a no-op; the
    # production inbox must dedupe by the stable event id before delivery
    delivered = await harness["runner"].deliver_signal(
        workflow_id=fresh.id, signal_key=CAPTURE_SIGNAL, payload={}
    )
    assert delivered is False
    await harness["runner"].run_due()
    assert await _balance(harness) == first == 100


async def test_refund_workflow_reverses_credit_once(harness: dict[str, Any], clock: Any) -> None:
    await open_account(harness)
    purchase = await _start_purchase(harness)
    for _ in range(4):
        clock.advance(timedelta(seconds=1))
        await harness["runner"].run_due()
    from inc.kernel.workflow.models import WorkflowInstance

    async with harness["uow_factory"]() as uow:
        fresh = (
            (
                await uow.session.execute(
                    select(WorkflowInstance).where(WorkflowInstance.id == purchase.id)
                )
            )
            .scalars()
            .first()
        )
    order = None
    async with harness["uow_factory"]() as uow:
        order = (await uow.session.execute(select(PaymentOrder))).scalars().first()
    provider = harness["provider"]
    body = provider.webhook("evt-capture-3", order.order_reference)
    await ProcessVerifiedWebhook(harness["payments_ctx"])(
        provider_key="fake",
        raw_body=body,
        headers={"X-Signature": provider.sign(body)},
        secret="secret",
    )
    await harness["runner"].deliver_signal(
        workflow_id=fresh.id, signal_key=CAPTURE_SIGNAL, payload={}
    )
    await harness["runner"].run_due()
    assert await _balance(harness) == 100

    refund = await harness["runner"].start(
        workflow_key=REFUND_WORKFLOW_KEY,
        idempotency_key=f"refund:{order.order_reference}",
        input_data={"order_reference": order.order_reference},
        trace_id="point-purchase",
    )
    clock.advance(timedelta(seconds=1))
    await harness["runner"].run_due()
    await harness["runner"].deliver_signal(
        workflow_id=refund.id, signal_key=REFUND_SIGNAL, payload={}
    )
    await harness["runner"].run_due()
    assert await _balance(harness) == 0

    # a second refund signal cannot double-reverse
    await harness["runner"].deliver_signal(
        workflow_id=refund.id, signal_key=REFUND_SIGNAL, payload={}
    )
    await harness["runner"].run_due()
    assert await _balance(harness) == 0

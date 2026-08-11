"""Membership purchase workflow tests: payment -> capture -> subscribe.

Contract source: context/spec/capabilities/membership.md §10,
capabilities/payments.md §10, features.md (membership purchase).

Exercises the assembled workflow with a fake payment provider and the
real membership + points commands: a captured payment opens a
subscription and grants the cycle quota into an expiring points bucket.
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

from inc.capabilities.membership.commands import (
    CommandContext as MembershipCommandContext,
)
from inc.capabilities.membership.events import MEMBERSHIP_EVENT_SCHEMAS
from inc.capabilities.membership.levels import MembershipLevelRegistry
from inc.capabilities.membership.models import MembershipSubscription
from inc.capabilities.payments.commands import (
    CommandContext as PaymentsCommandContext,
)
from inc.capabilities.payments.commands import ProcessVerifiedWebhook
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
from inc.capabilities.points import (
    CommandContext as PointsCommandContext,
)
from inc.capabilities.points import (
    PointBehaviorRegistry,
    PointBehaviorSpec,
)
from inc.capabilities.points.commands import CreditPoints, OpenPointsAccount
from inc.capabilities.points.events import POINTS_EVENT_SCHEMAS
from inc.capabilities.points.models import PointsProgram
from inc.capabilities.points.queries import PointsQueries
from inc.capabilities.points.schemas import CreditDebitInput
from inc.features.membership_purchase.definition import level_specs
from inc.features.membership_purchase.workflows import (
    CAPTURE_SIGNAL,
    PURCHASE_WORKFLOW_KEY,
    MembershipPurchaseContext,
    build_purchase_workflow_spec,
)
from inc.kernel.db import UoWFactory
from inc.kernel.events import EventSchemaRegistry, OutboxWriter
from inc.kernel.workflow import WorkflowRegistry, WorkflowRunner

GRANT_BEHAVIOR = "membership.grant"


@dataclass
class FakePayProvider:
    key: str = "fake"
    statuses: dict[str, PaymentStatus] = field(default_factory=dict)

    def sign(self, body: bytes) -> str:
        return hmac.new(b"secret", body, hashlib.sha256).hexdigest()

    def webhook(
        self, event_id: str, order_reference: str, *, amount: int = 3000, currency: str = "CNY"
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


class _RealPointsLedger:
    """Composition-root binding: points CreditPoints with the grant behavior."""

    def __init__(self, points_ctx: PointsCommandContext, behaviors: PointBehaviorRegistry) -> None:
        self._ctx = points_ctx
        self._behaviors = behaviors

    async def grant_points(
        self,
        *,
        subject_type: str,
        subject_id: str,
        amount: int,
        expires_at: Any,
        idempotency_key: str,
        source_ref: str,
    ) -> dict[str, Any]:
        entry = await CreditPoints(self._ctx)(
            GRANT_BEHAVIOR,
            CreditDebitInput(
                subject_type=subject_type,
                subject_id=subject_id,
                amount=amount,
                source_type="membership",
                source_id=source_ref,
                idempotency_key=idempotency_key,
                actor_type="system",
                actor_id="membership",
                expires_at=expires_at,
            ),
        )
        return {"entry_id": entry.id}


async def _exists(subject_type: str, subject_id: str) -> bool:
    return True


@pytest.fixture
def behaviors() -> PointBehaviorRegistry:
    registry = PointBehaviorRegistry()
    registry.register(
        PointBehaviorSpec(
            key=GRANT_BEHAVIOR,
            version="1",
            program_key="credit",
            direction="credit",
            min_amount=1,
            max_amount=1_000_000,
            allowed_source_types=("membership",),
        )
    )
    return registry


@pytest.fixture
def levels() -> MembershipLevelRegistry:
    registry = MembershipLevelRegistry()
    for spec in level_specs:
        registry.register(spec)
    return registry


@pytest.fixture
def schema_registry() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    for key, schema in POINTS_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    for key, schema in PAYMENT_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    for key, schema in MEMBERSHIP_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    return registry


@pytest.fixture
async def harness(
    uow_factory: UoWFactory,
    clock: Any,
    behaviors: PointBehaviorRegistry,
    levels: MembershipLevelRegistry,
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
        trace_id="membership-purchase",
    )
    points_ctx = PointsCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=outbox,
        behaviors=behaviors,
        permissions=frozenset(),
        actor_id="feature",
        trace_id="membership-purchase",
    )
    membership_ctx = MembershipCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=outbox,
        levels=levels,
        subject_exists=_exists,
        points_ledger=_RealPointsLedger(points_ctx, behaviors),
        permissions=frozenset(),
        actor_id="feature",
        trace_id="membership-purchase",
    )
    purchase_ctx = MembershipPurchaseContext(
        payments_ctx=payments_ctx,
        membership_ctx=membership_ctx,
        payments_queries=PaymentsQueries(uow_factory=uow_factory),
    )
    registry.register(build_purchase_workflow_spec(ctx=purchase_ctx))
    return {
        "runner": runner,
        "provider": provider,
        "points_ctx": points_ctx,
        "membership_ctx": membership_ctx,
        "payments_ctx": payments_ctx,
        "registry": registry,
        "clock": clock,
        "uow_factory": uow_factory,
        "levels": levels,
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


async def _subscription(harness: dict[str, Any]) -> MembershipSubscription:
    async with harness["uow_factory"]() as uow:
        row = (await uow.session.execute(select(MembershipSubscription))).scalars().first()
    assert row is not None
    return row


async def _drive_until_waiting(harness: dict[str, Any], instance: Any) -> None:
    for _ in range(4):
        harness["clock"].advance(timedelta(seconds=1))
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


async def test_capture_opens_subscription_and_grants_points(
    harness: dict[str, Any], clock: Any
) -> None:
    await open_account(harness)
    instance = await harness["runner"].start(
        workflow_key=PURCHASE_WORKFLOW_KEY,
        idempotency_key="membership:order-1",
        input_data={
            "subject_type": "identity",
            "subject_id": "user-1",
            "provider_key": "fake",
            "offer_key": "membership_basic_30",
            "idempotency_key": "order-1",
        },
        trace_id="membership-purchase",
    )
    await _drive_until_waiting(harness, instance)

    async with harness["uow_factory"]() as uow:
        order = (await uow.session.execute(select(PaymentOrder))).scalars().first()
    assert order is not None and order.state == "pending"
    assert order.offer.offer_key == "membership_basic_30"

    provider = harness["provider"]
    body = provider.webhook("evt-capture-m1", order.order_reference)
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

    sub = await _subscription(harness)
    assert sub.status == "active"
    assert sub.level_key == "basic"
    assert sub.granted_points == 100
    assert sub.cycle_start < sub.cycle_end
    assert await _balance(harness) == 100


async def test_replayed_capture_does_not_double_subscribe(
    harness: dict[str, Any], clock: Any
) -> None:
    await open_account(harness)
    instance = await harness["runner"].start(
        workflow_key=PURCHASE_WORKFLOW_KEY,
        idempotency_key="membership:order-2",
        input_data={
            "subject_type": "identity",
            "subject_id": "user-1",
            "provider_key": "fake",
            "offer_key": "membership_basic_30",
            "idempotency_key": "order-2",
        },
        trace_id="membership-purchase",
    )
    await _drive_until_waiting(harness, instance)
    async with harness["uow_factory"]() as uow:
        order = (await uow.session.execute(select(PaymentOrder))).scalars().first()
    provider = harness["provider"]
    body = provider.webhook("evt-capture-m2", order.order_reference)
    await ProcessVerifiedWebhook(harness["payments_ctx"])(
        provider_key="fake",
        raw_body=body,
        headers={"X-Signature": provider.sign(body)},
        secret="secret",
    )
    await harness["runner"].deliver_signal(
        workflow_id=instance.id, signal_key=CAPTURE_SIGNAL, payload={}
    )
    await harness["runner"].run_due()
    first = await _balance(harness)
    assert first == 100
    # a replayed signal on a completed workflow is a no-op
    delivered = await harness["runner"].deliver_signal(
        workflow_id=instance.id, signal_key=CAPTURE_SIGNAL, payload={}
    )
    assert delivered is False
    await harness["runner"].run_due()
    assert await _balance(harness) == first == 100
    async with harness["uow_factory"]() as uow:
        rows = (await uow.session.execute(select(MembershipSubscription))).scalars().all()
    assert len(rows) == 1


async def test_unknown_offer_fails_workflow(harness: dict[str, Any]) -> None:
    await open_account(harness)
    instance = await harness["runner"].start(
        workflow_key=PURCHASE_WORKFLOW_KEY,
        idempotency_key="membership:order-3",
        input_data={
            "subject_type": "identity",
            "subject_id": "user-1",
            "provider_key": "fake",
            "offer_key": "nope",
            "idempotency_key": "order-3",
        },
        trace_id="membership-purchase",
    )
    for _ in range(8):  # retry policy (5 attempts) exhausted -> failed
        harness["clock"].advance(timedelta(minutes=5))
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
    assert fresh is not None and fresh.status == "failed"
    error = (fresh.result.data or {}).get("error", "") if fresh.result is not None else ""
    assert "unknown membership offer" in error

"""Point purchase workflows: order -> capture signal -> credit.

Contract source: context/spec/features.md §4.4.

Purchase workflow: create order, start attempt, wait on the capture
signal, credit points (idempotency domain = order reference). Refund
workflow: wait on the refund signal, then reverse the original credit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from inc.capabilities.payments.commands import (
    CommandContext as PaymentsCommandContext,
)
from inc.capabilities.payments.commands import (
    CreatePaymentOrder,
    StartPaymentAttempt,
)
from inc.capabilities.payments.queries import PaymentsQueries
from inc.capabilities.payments.schemas import CreatePaymentOrderInput
from inc.capabilities.points.commands import CommandContext as PointsCommandContext
from inc.capabilities.points.commands import CreditPoints, ReverseLedgerEntry
from inc.capabilities.points.queries import PointsQueries
from inc.capabilities.points.schemas import CreditDebitInput, ReverseInput
from inc.features.point_purchase.definition import require_offer
from inc.kernel.db import UnitOfWork
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.workflow import ActivitySpec, WorkflowRunner, WorkflowSpec

PURCHASE_WORKFLOW_KEY = "pointpurchase.purchase.v1"
REFUND_WORKFLOW_KEY = "pointpurchase.refund.v1"
CAPTURE_SIGNAL = "pointpurchase.captured.v1"
REFUND_SIGNAL = "pointpurchase.refunded.v1"
CREDIT_BEHAVIOR = "purchase.completed.credit"

CREDITABLE_ORDER_STATES = ("captured", "partially_refunded")


@dataclass(frozen=True, slots=True)
class PointPurchaseContext:
    payments_ctx: PaymentsCommandContext
    points_ctx: PointsCommandContext
    points_queries: PointsQueries
    payments_queries: PaymentsQueries


def build_purchase_workflow_spec(*, ctx: PointPurchaseContext) -> WorkflowSpec:
    async def create_order_step(
        uow: UnitOfWork, data: dict[str, Any], activity_ctx: Any
    ) -> dict[str, Any]:
        workflow = data.get("workflow", {})
        offer = require_offer(workflow["offer_key"])
        order = await CreatePaymentOrder(ctx.payments_ctx)(
            CreatePaymentOrderInput(
                subject_type=workflow["subject_type"],
                subject_id=workflow["subject_id"],
                provider_key=workflow["provider_key"],
                offer_key=offer.offer_key,
                offer_version=offer.version,
                description=offer.description,
                amount=offer.amount,
                currency=offer.currency,
                idempotency_key=f"purchase:{workflow['idempotency_key']}",
            )
        )
        return {"order_id": order.id, "order_reference": order.order_reference}

    async def start_attempt_step(
        uow: UnitOfWork, data: dict[str, Any], activity_ctx: Any
    ) -> dict[str, Any]:
        order_id = data["state"].get("pointpurchase.create.order.v1", {}).get("order_id")
        if order_id is None:
            order_id = data["workflow"]["order_id"]
        result = await StartPaymentAttempt(ctx.payments_ctx)(uuid.UUID(str(order_id)))
        return {"checkout_url": result.checkout_url, "order_id": result.order.id}

    async def wait_capture_step(
        uow: UnitOfWork, data: dict[str, Any], activity_ctx: Any
    ) -> dict[str, Any]:
        return {"wait_for_signal": CAPTURE_SIGNAL}

    async def credit_step(
        uow: UnitOfWork, data: dict[str, Any], activity_ctx: Any
    ) -> dict[str, Any]:
        workflow = data.get("workflow", {})
        order_info = data["state"].get("pointpurchase.create.order.v1", {})
        order_reference = order_info.get("order_reference") or workflow.get("order_reference")
        if order_reference is None:
            raise KernelError(
                code="pointpurchase.missing_order_reference",
                category=ErrorCategory.INTERNAL,
                message="credit step requires an order reference",
            )
        order = await ctx.payments_queries.get_order_by_reference(order_reference)
        if order is None:
            raise KernelError(
                code="pointpurchase.order_missing",
                category=ErrorCategory.INTERNAL,
                message="order vanished between capture and credit",
            )
        if order.state not in CREDITABLE_ORDER_STATES:
            raise KernelError(
                code="pointpurchase.order_not_creditable",
                category=ErrorCategory.VALIDATION,
                message=f"order {order_reference} is {order.state}; credit requires manual review",
            )
        subject_type = workflow["subject_type"]
        subject_id = workflow["subject_id"]
        offer = require_offer(workflow["offer_key"])
        entry = await CreditPoints(ctx.points_ctx)(
            CREDIT_BEHAVIOR,
            CreditDebitInput(
                subject_type=subject_type,
                subject_id=subject_id,
                amount=offer.points_amount,
                source_type="payment",
                source_id=order_reference,
                idempotency_key=f"purchase:{order_reference}",
                actor_type="system",
                actor_id="point-purchase",
            ),
        )
        return {"entry_id": entry.id}

    return WorkflowSpec(
        key=PURCHASE_WORKFLOW_KEY,
        version="1",
        activities=(
            ActivitySpec(
                key="pointpurchase.create.order.v1",
                timeout_seconds=30.0,
                handler=create_order_step,
            ),
            ActivitySpec(
                key="pointpurchase.start.attempt.v1",
                timeout_seconds=30.0,
                handler=start_attempt_step,
            ),
            ActivitySpec(
                key="pointpurchase.wait.capture.v1",
                timeout_seconds=30.0,
                handler=wait_capture_step,
            ),
            ActivitySpec(
                key="pointpurchase.credit.v1",
                timeout_seconds=30.0,
                handler=credit_step,
            ),
        ),
        signal_keys=(CAPTURE_SIGNAL,),
    )


def build_refund_workflow_spec(*, ctx: PointPurchaseContext) -> WorkflowSpec:
    async def wait_refund_step(
        uow: UnitOfWork, data: dict[str, Any], activity_ctx: Any
    ) -> dict[str, Any]:
        return {"wait_for_signal": REFUND_SIGNAL}

    async def reverse_step(
        uow: UnitOfWork, data: dict[str, Any], activity_ctx: Any
    ) -> dict[str, Any]:
        order_reference = data["workflow"]["order_reference"]
        credit = await ctx.points_queries.find_credit_by_source(
            behavior_key=CREDIT_BEHAVIOR, source_id=order_reference
        )
        if credit is None:
            # The refund event may arrive before the purchase workflow's credit
            # step ran. Skipping here would let the credit land afterwards and
            # never be reversed (permanent over-credit); retry instead until
            # the credit is recorded or the workflow fails loudly.
            raise KernelError(
                code="pointpurchase.credit_not_found",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message=f"credit for {order_reference} not recorded yet; retrying",
            )
        reversal = await ReverseLedgerEntry(ctx.points_ctx)(
            uuid.UUID(credit.id),
            ReverseInput(reason="purchase refunded", idempotency_key=f"refund:{order_reference}"),
        )
        return {"reversal_id": reversal.id}

    return WorkflowSpec(
        key=REFUND_WORKFLOW_KEY,
        version="1",
        activities=(
            ActivitySpec(
                key="pointpurchase.wait.refund.v1",
                timeout_seconds=30.0,
                handler=wait_refund_step,
            ),
            ActivitySpec(
                key="pointpurchase.reverse.v1",
                timeout_seconds=30.0,
                handler=reverse_step,
            ),
        ),
        signal_keys=(REFUND_SIGNAL,),
    )


@dataclass(frozen=True, slots=True)
class BridgeContext:
    """What the webhook bridge needs: workflow runner + payments reads."""

    runner: WorkflowRunner
    payments_queries: PaymentsQueries


def purchase_workflow_idempotency_key(idempotency_key: str) -> str:
    """One convention shared by the orders endpoint and the webhook bridge.

    The purchase workflow and the payment order share the same business
    idempotency key, so a verified capture event can locate the waiting
    workflow instance via the runner's read-only lookup.
    """

    return f"purchase:{idempotency_key}"


def checkout_view(instance: Any) -> dict[str, Any] | None:
    """Project persisted workflow state into the purchase HTTP view."""

    state = instance.state.data
    order = state.get("pointpurchase.create.order.v1") or {}
    attempt = state.get("pointpurchase.start.attempt.v1") or {}
    order_reference = order.get("order_reference")
    checkout_url = attempt.get("checkout_url")
    if not order_reference or not checkout_url:
        return None
    return {"order_reference": order_reference, "checkout_url": checkout_url}


async def bridge_payment_event(ctx: BridgeContext, *, order_id: str) -> str:
    """Bridge one verified payment fact into workflow signals.

    Contract source: context/spec/features.md §4.4. Duplicate receipts are
    filtered by the payments command before this runs; a captured order
    wakes the waiting purchase workflow, a completed refund starts and
    signals the refund workflow. Anything else is ignored on purpose.
    """

    order = await ctx.payments_queries.get_order(uuid.UUID(order_id))
    if order is None:
        return "order_missing"
    if order.state == "captured":
        instance = await ctx.runner.find_by_business_key(
            workflow_key=PURCHASE_WORKFLOW_KEY,
            idempotency_key=order.idempotency_key,
        )
        if instance is None:
            return "no_workflow"
        # deliver_signal durably persists the signal for any non-terminal
        # instance and the runner consumes pre-wait signals when the workflow
        # reaches its wait step; requiring "waiting" here would drop a capture
        # that lands while the workflow is still in create-order/start-attempt.
        await ctx.runner.deliver_signal(
            workflow_id=instance.id, signal_key=CAPTURE_SIGNAL, payload={"order_id": order_id}
        )
        return "capture_signaled"
    if order.state in ("partially_refunded", "refunded"):
        instance = await ctx.runner.start(
            workflow_key=REFUND_WORKFLOW_KEY,
            idempotency_key=f"refund:{order.order_reference}",
            input_data={"order_reference": order.order_reference},
            trace_id="payment-webhook",
        )
        await ctx.runner.deliver_signal(
            workflow_id=instance.id, signal_key=REFUND_SIGNAL, payload={"order_id": order_id}
        )
        return "refund_signaled"
    return "ignored"

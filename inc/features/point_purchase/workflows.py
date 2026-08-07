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
from inc.kernel.workflow import ActivitySpec, WorkflowSpec

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
            return {"skipped": True, "reason": "no_credit_entry"}
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

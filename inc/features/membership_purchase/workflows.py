"""Membership purchase workflows: order -> capture signal -> subscribe.

Contract source: context/spec/features.md (membership purchase),
capabilities/membership.md §10, capabilities/payments.md §5/§6.

Purchase workflow: create order, start attempt, wait on the capture
signal, then SubscribeLevel (which grants the cycle quota through the
PointsLedger Port). The workflow idempotency key is shared with the payment
order so a verified capture event can locate the waiting workflow. Credits
never change the payment fact: a failed subscribe retries and the order
stays captured.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from inc.capabilities.membership.commands import (
    CommandContext as MembershipCommandContext,
)
from inc.capabilities.membership.commands import SubscribeLevel
from inc.capabilities.membership.schemas import SubscribeInput
from inc.capabilities.payments.commands import (
    CommandContext as PaymentsCommandContext,
)
from inc.capabilities.payments.commands import (
    CreatePaymentOrder,
    StartPaymentAttempt,
)
from inc.capabilities.payments.queries import PaymentsQueries
from inc.capabilities.payments.schemas import CreatePaymentOrderInput
from inc.features.membership_purchase.definition import require_offer
from inc.kernel.db import UnitOfWork
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.workflow import ActivitySpec, WorkflowRunner, WorkflowSpec

PURCHASE_WORKFLOW_KEY = "membershippurchase.purchase.v1"
CAPTURE_SIGNAL = "membershippurchase.captured.v1"


@dataclass(frozen=True, slots=True)
class MembershipPurchaseContext:
    payments_ctx: PaymentsCommandContext
    membership_ctx: MembershipCommandContext
    payments_queries: PaymentsQueries


def build_purchase_workflow_spec(*, ctx: MembershipPurchaseContext) -> WorkflowSpec:
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
                idempotency_key=f"membership:{workflow['idempotency_key']}",
            )
        )
        return {"order_id": order.id, "order_reference": order.order_reference}

    async def start_attempt_step(
        uow: UnitOfWork, data: dict[str, Any], activity_ctx: Any
    ) -> dict[str, Any]:
        order_id = data["state"].get("membershippurchase.create.order.v1", {}).get("order_id")
        if order_id is None:
            order_id = data["workflow"]["order_id"]
        result = await StartPaymentAttempt(ctx.payments_ctx)(uuid.UUID(str(order_id)))
        return {"checkout_url": result.checkout_url, "order_id": result.order.id}

    async def wait_capture_step(
        uow: UnitOfWork, data: dict[str, Any], activity_ctx: Any
    ) -> dict[str, Any]:
        return {"wait_for_signal": CAPTURE_SIGNAL}

    async def subscribe_step(
        uow: UnitOfWork, data: dict[str, Any], activity_ctx: Any
    ) -> dict[str, Any]:
        workflow = data.get("workflow", {})
        order_info = data["state"].get("membershippurchase.create.order.v1", {})
        order_reference = order_info.get("order_reference") or workflow.get("order_reference")
        if order_reference is None:
            raise KernelError(
                code="membershippurchase.missing_order_reference",
                category=ErrorCategory.INTERNAL,
                message="subscribe step requires an order reference",
            )
        order = await ctx.payments_queries.get_order_by_reference(order_reference)
        if order is None:
            raise KernelError(
                code="membershippurchase.order_missing",
                category=ErrorCategory.INTERNAL,
                message="order vanished between capture and subscribe",
            )
        if order.state != "captured":
            raise KernelError(
                code="membershippurchase.order_not_captured",
                category=ErrorCategory.VALIDATION,
                message=f"order {order_reference} is {order.state}; subscribe requires captured",
            )
        offer = require_offer(workflow["offer_key"])
        if order.offer_version != offer.version:
            # The order was priced against a specific offer version; granting a
            # level from a different (later) catalog version would silently
            # upgrade/downgrade what the customer paid for.
            raise KernelError(
                code="membershippurchase.offer_version_mismatch",
                category=ErrorCategory.INTERNAL,
                message=(
                    f"order {order_reference} paid offer v{order.offer_version} "
                    f"but catalog now resolves {offer.offer_key} v{offer.version}"
                ),
            )
        subject_type = workflow["subject_type"]
        subject_id = workflow["subject_id"]
        subscription = await SubscribeLevel(ctx.membership_ctx)(
            SubscribeInput(
                subject_type=subject_type,
                subject_id=subject_id,
                level_key=offer.level_key,
                idempotency_key=f"membership:{order_reference}",
            )
        )
        return {"subscription_id": subscription.id, "level_key": subscription.level_key}

    return WorkflowSpec(
        key=PURCHASE_WORKFLOW_KEY,
        version="1",
        activities=(
            ActivitySpec(
                key="membershippurchase.create.order.v1",
                timeout_seconds=30.0,
                handler=create_order_step,
            ),
            ActivitySpec(
                key="membershippurchase.start.attempt.v1",
                timeout_seconds=30.0,
                handler=start_attempt_step,
            ),
            ActivitySpec(
                key="membershippurchase.wait.capture.v1",
                timeout_seconds=30.0,
                handler=wait_capture_step,
            ),
            ActivitySpec(
                key="membershippurchase.subscribe.v1",
                timeout_seconds=30.0,
                handler=subscribe_step,
            ),
        ),
        signal_keys=(CAPTURE_SIGNAL,),
    )


@dataclass(frozen=True, slots=True)
class BridgeContext:
    """What the webhook bridge needs: workflow runner + payments reads."""

    runner: WorkflowRunner
    payments_queries: PaymentsQueries


def purchase_workflow_idempotency_key(idempotency_key: str) -> str:
    """One convention shared by the orders endpoint and the webhook bridge."""

    return f"membership:{idempotency_key}"


def checkout_view(instance: Any) -> dict[str, Any] | None:
    """Project persisted workflow state into the purchase HTTP view."""

    state = instance.state.data
    order = state.get("membershippurchase.create.order.v1") or {}
    attempt = state.get("membershippurchase.start.attempt.v1") or {}
    order_reference = order.get("order_reference")
    checkout_url = attempt.get("checkout_url")
    if not order_reference or not checkout_url:
        return None
    return {"order_reference": order_reference, "checkout_url": checkout_url}


async def bridge_payment_event(ctx: BridgeContext, *, order_id: str) -> str:
    """Bridge one verified capture fact into the waiting purchase workflow.

    Only captured orders wake a workflow; anything else is ignored. The
    payments command already deduped the webhook receipt before this runs.
    """

    order = await ctx.payments_queries.get_order(uuid.UUID(order_id))
    if order is None:
        return "order_missing"
    if order.state != "captured":
        return "ignored"
    instance = await ctx.runner.find_by_business_key(
        workflow_key=PURCHASE_WORKFLOW_KEY,
        idempotency_key=order.idempotency_key,
    )
    if instance is None:
        return "no_workflow"
    # deliver_signal durably persists the signal for any non-terminal instance
    # and the runner consumes pre-wait signals when the workflow reaches its
    # wait step; requiring "waiting" here would drop a capture that lands while
    # the workflow is still in the create-order/start-attempt activities.
    await ctx.runner.deliver_signal(
        workflow_id=instance.id, signal_key=CAPTURE_SIGNAL, payload={"order_id": order_id}
    )
    return "capture_signaled"

"""Persistent user-center workflows built only from capability public APIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from inc.capabilities.gift_cards import (
    CommandContext as GiftCardCommandContext,
)
from inc.capabilities.gift_cards import (
    CommitGiftCardRedemption,
    CommitGiftCardRedemptionInput,
    GiftCardQueries,
)
from inc.capabilities.membership import (
    AttachPointsGrant,
    AttachPointsGrantInput,
    MembershipQueries,
    PrepareSubscriptionCycle,
    PrepareSubscriptionCycleInput,
    TerminateInput,
    TerminateSubscription,
)
from inc.capabilities.membership import (
    CommandContext as MembershipCommandContext,
)
from inc.capabilities.notification import (
    CommandContext as NotificationCommandContext,
)
from inc.capabilities.notification import (
    RequestNotification,
    RequestNotificationInput,
)
from inc.capabilities.payments import PaymentsQueries
from inc.capabilities.points import (
    CommandContext as PointsCommandContext,
)
from inc.capabilities.points import (
    CreditDebitInput,
    CreditPoints,
    PointsQueries,
    ReverseInput,
    ReverseLedgerEntry,
)
from inc.features.user_center.catalog import (
    GiftCardFulfillmentRegistry,
    MembershipOfferRegistry,
    PointBundleRegistry,
)
from inc.kernel.db import UnitOfWork
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.workflow import ActivitySpec, WorkflowSpec

CHECK_IN_WORKFLOW_KEY: Final = "user_center.check_in.v1"
POINT_PURCHASE_WORKFLOW_KEY: Final = "user_center.point_purchase.fulfill.v1"
MEMBERSHIP_PURCHASE_WORKFLOW_KEY: Final = "user_center.membership_purchase.fulfill.v1"
GIFT_CARD_POINTS_WORKFLOW_KEY: Final = "user_center.gift_card.points.v1"
GIFT_CARD_MEMBERSHIP_WORKFLOW_KEY: Final = "user_center.gift_card.membership.v1"
REFUND_WORKFLOW_KEY: Final = "user_center.refund.compensate.v1"

CHECK_IN_BEHAVIOR_KEY: Final = "user_center.check_in.credit.v1"
POINT_PURCHASE_BEHAVIOR_KEY: Final = "user_center.point_purchase.credit.v1"
MEMBERSHIP_CYCLE_BEHAVIOR_KEY: Final = "user_center.membership_cycle.credit.v1"


@dataclass(frozen=True, slots=True)
class UserCenterWorkflowContext:
    points_ctx: PointsCommandContext
    membership_ctx: MembershipCommandContext
    payments: PaymentsQueries
    points: PointsQueries
    membership: MembershipQueries
    gift_cards_ctx: GiftCardCommandContext | None
    gift_cards: GiftCardQueries | None
    point_bundles: PointBundleRegistry
    membership_offers: MembershipOfferRegistry
    gift_card_fulfillments: GiftCardFulfillmentRegistry
    notification_ctx: NotificationCommandContext | None = None


def build_user_center_workflow_specs(*, ctx: UserCenterWorkflowContext) -> tuple[WorkflowSpec, ...]:
    """Build every durable workflow owned by the single user_center feature."""

    return (
        build_check_in_workflow_spec(ctx=ctx),
        build_point_purchase_workflow_spec(ctx=ctx),
        build_membership_purchase_workflow_spec(ctx=ctx),
        build_gift_card_points_workflow_spec(ctx=ctx),
        build_gift_card_membership_workflow_spec(ctx=ctx),
        build_refund_workflow_spec(ctx=ctx),
    )


def build_check_in_workflow_spec(*, ctx: UserCenterWorkflowContext) -> WorkflowSpec:
    async def credit(_uow: UnitOfWork, data: dict[str, Any], _activity: Any) -> dict[str, Any]:
        workflow = data["workflow"]
        entry = await CreditPoints(ctx.points_ctx)(
            CHECK_IN_BEHAVIOR_KEY,
            CreditDebitInput(
                subject_type="identity",
                subject_id=workflow["subject_id"],
                amount=ctx.points_ctx.behaviors.require(CHECK_IN_BEHAVIOR_KEY).fixed_amount or 10,
                source_type="user_center",
                source_id=workflow["business_date"],
                idempotency_key=(
                    f"check-in:{workflow['subject_id']}:credit:{workflow['business_date']}:v1"
                ),
                actor_id=workflow["subject_id"],
            ),
        )
        return {"entry_id": entry.id, "business_date": workflow["business_date"]}

    return _workflow(
        CHECK_IN_WORKFLOW_KEY,
        ActivitySpec(key="user_center.check_in.credit.v1", handler=credit),
    )


def build_point_purchase_workflow_spec(*, ctx: UserCenterWorkflowContext) -> WorkflowSpec:
    async def validate(_uow: UnitOfWork, data: dict[str, Any], _activity: Any) -> dict[str, Any]:
        workflow = data["workflow"]
        order = await _captured_order(ctx, workflow)
        bundle = ctx.point_bundles.require(order.offer_key)
        _match_order(order, bundle.version, bundle.price_cents)
        return {"product_key": bundle.product_key, "points_amount": bundle.points_amount}

    async def credit(_uow: UnitOfWork, data: dict[str, Any], _activity: Any) -> dict[str, Any]:
        workflow = data["workflow"]
        validated = _result(data, "user_center.point_purchase.validate_captured.v1")
        entry = await CreditPoints(ctx.points_ctx)(
            POINT_PURCHASE_BEHAVIOR_KEY,
            CreditDebitInput(
                subject_type="identity",
                subject_id=workflow["subject_id"],
                amount=validated["points_amount"],
                source_type="payment",
                source_id=workflow["order_id"],
                idempotency_key=f"payment-order:{workflow['order_id']}:points",
                actor_type="system",
                metadata={"product_key": validated["product_key"]},
            ),
        )
        return {"entry_id": entry.id}

    return _workflow(
        POINT_PURCHASE_WORKFLOW_KEY,
        ActivitySpec(key="user_center.point_purchase.validate_captured.v1", handler=validate),
        ActivitySpec(key="user_center.point_purchase.credit.v1", handler=credit),
        ActivitySpec(
            key="user_center.point_purchase.notify.v1",
            handler=_notification_handler(ctx, kind="point_purchase"),
        ),
    )


def build_membership_purchase_workflow_spec(*, ctx: UserCenterWorkflowContext) -> WorkflowSpec:
    async def validate(_uow: UnitOfWork, data: dict[str, Any], _activity: Any) -> dict[str, Any]:
        workflow = data["workflow"]
        order = await _captured_order(ctx, workflow)
        offer = ctx.membership_offers.require(order.offer_key)
        _match_order(order, offer.version, offer.price_cents)
        return {"offer_key": offer.offer_key, "level_key": offer.level_key}

    return _membership_workflow(
        key=MEMBERSHIP_PURCHASE_WORKFLOW_KEY,
        ctx=ctx,
        prefix="user_center.membership_purchase",
        validate=validate,
        source_type="payment",
        source_ref_field="order_id",
        include_notification=True,
    )


def build_gift_card_points_workflow_spec(*, ctx: UserCenterWorkflowContext) -> WorkflowSpec:
    async def validate(_uow: UnitOfWork, data: dict[str, Any], _activity: Any) -> dict[str, Any]:
        redemption = await _redemption(ctx, data["workflow"])
        fulfillment = _validate_redemption(ctx, redemption)
        if fulfillment.fulfillment_type != "points_bundle":
            raise _redemption_error("gift card does not fulfill points")
        bundle = ctx.point_bundles.require(fulfillment.target_key)
        return {"product_key": bundle.product_key, "points_amount": bundle.points_amount}

    async def credit(_uow: UnitOfWork, data: dict[str, Any], _activity: Any) -> dict[str, Any]:
        workflow = data["workflow"]
        validated = _result(data, "user_center.gift_card.points.validate.v1")
        entry = await CreditPoints(ctx.points_ctx)(
            POINT_PURCHASE_BEHAVIOR_KEY,
            CreditDebitInput(
                subject_type="identity",
                subject_id=workflow["subject_id"],
                amount=validated["points_amount"],
                source_type="gift_card",
                source_id=workflow["redemption_id"],
                idempotency_key=f"gift-card:{workflow['redemption_id']}:points",
                actor_type="system",
                metadata={"product_key": validated["product_key"]},
            ),
        )
        return {"entry_id": entry.id}

    return _workflow(
        GIFT_CARD_POINTS_WORKFLOW_KEY,
        ActivitySpec(key="user_center.gift_card.points.validate.v1", handler=validate),
        ActivitySpec(key="user_center.gift_card.points.credit.v1", handler=credit),
        ActivitySpec(key="user_center.gift_card.points.commit.v1", handler=_commit_handler(ctx)),
        ActivitySpec(
            key="user_center.gift_card.points.notify.v1",
            handler=_notification_handler(ctx, kind="gift_card_points"),
        ),
    )


def build_gift_card_membership_workflow_spec(*, ctx: UserCenterWorkflowContext) -> WorkflowSpec:
    async def validate(_uow: UnitOfWork, data: dict[str, Any], _activity: Any) -> dict[str, Any]:
        redemption = await _redemption(ctx, data["workflow"])
        fulfillment = _validate_redemption(ctx, redemption)
        if fulfillment.fulfillment_type != "membership_offer":
            raise _redemption_error("gift card does not fulfill membership")
        offer = ctx.membership_offers.require(fulfillment.target_key)
        return {"offer_key": offer.offer_key, "level_key": offer.level_key}

    base = _membership_workflow(
        key=GIFT_CARD_MEMBERSHIP_WORKFLOW_KEY,
        ctx=ctx,
        prefix="user_center.gift_card.membership",
        validate=validate,
        source_type="gift_card",
        source_ref_field="redemption_id",
        include_notification=False,
    )
    return WorkflowSpec(
        key=base.key,
        version=base.version,
        activities=base.activities
        + (
            ActivitySpec(
                key="user_center.gift_card.membership.commit.v1", handler=_commit_handler(ctx)
            ),
            ActivitySpec(
                key="user_center.gift_card.membership.notify.v1",
                handler=_notification_handler(ctx, kind="gift_card_membership"),
            ),
        ),
    )


def build_refund_workflow_spec(*, ctx: UserCenterWorkflowContext) -> WorkflowSpec:
    async def resolve(_uow: UnitOfWork, data: dict[str, Any], _activity: Any) -> dict[str, Any]:
        workflow = data["workflow"]
        detail = await ctx.payments.get_order_detail(workflow["order_id"])
        if detail is None or not any(
            (refund.id == workflow["refund_id"] or refund.refund_ref == workflow["refund_id"])
            and refund.state == "completed"
            for refund in detail.refunds
        ):
            raise _error("user_center.refund_fact_missing", "trusted refund fact was not found")
        order = detail.order
        if order.offer_key in {item.product_key for item in ctx.point_bundles.specs()}:
            entry = await ctx.points.find_credit_by_source(
                behavior_key=POINT_PURCHASE_BEHAVIOR_KEY, source_id=order.id
            )
            return {"kind": "points", "entry_id": entry.id if entry else None}
        if order.offer_key in {item.offer_key for item in ctx.membership_offers.specs()}:
            cycles = await ctx.membership.list_membership_cycles(
                page=1, size=2, source_type="payment", source_ref=order.id
            )
            cycle = cycles.items[0] if cycles.items else None
            return {
                "kind": "membership",
                "subscription_id": cycle.subscription_id if cycle else None,
                "entry_id": cycle.points_entry_ref if cycle else None,
            }
        raise _error("user_center.version_conflict", "order references an unknown offer")

    async def terminate(_uow: UnitOfWork, data: dict[str, Any], _activity: Any) -> dict[str, Any]:
        resolved = _result(data, "user_center.refund.resolve_fact.v1")
        subscription_id = resolved.get("subscription_id")
        if resolved["kind"] == "membership" and subscription_id:
            await TerminateSubscription(ctx.membership_ctx)(
                TerminateInput(subscription_id=subscription_id, reason="payment refunded")
            )
            return {"terminated": True}
        return {"terminated": False}

    async def reverse(_uow: UnitOfWork, data: dict[str, Any], _activity: Any) -> dict[str, Any]:
        workflow = data["workflow"]
        resolved = _result(data, "user_center.refund.resolve_fact.v1")
        entry_id = resolved.get("entry_id")
        if not entry_id:
            raise _error("user_center.fulfillment_pending", "refundable entitlement is pending")
        reversal = await ReverseLedgerEntry(ctx.points_ctx)(
            entry_id,
            ReverseInput(
                reason="payment refunded",
                idempotency_key=f"payment-refund:{workflow['refund_id']}:reverse",
            ),
        )
        return {"reversal_entry_id": reversal.id}

    return _workflow(
        REFUND_WORKFLOW_KEY,
        ActivitySpec(key="user_center.refund.resolve_fact.v1", handler=resolve),
        ActivitySpec(key="user_center.refund.terminate_membership.v1", handler=terminate),
        ActivitySpec(key="user_center.refund.reverse_points.v1", handler=reverse),
    )


def _membership_workflow(
    *,
    key: str,
    ctx: UserCenterWorkflowContext,
    prefix: str,
    validate: Any,
    source_type: str,
    source_ref_field: str,
    include_notification: bool,
) -> WorkflowSpec:
    validate_key = f"{prefix}.validate.v1"
    prepare_key = f"{prefix}.prepare_cycle.v1"
    credit_key = f"{prefix}.credit_cycle.v1"

    async def prepare(_uow: UnitOfWork, data: dict[str, Any], _activity: Any) -> dict[str, Any]:
        workflow = data["workflow"]
        validated = _result(data, validate_key)
        source_ref = workflow[source_ref_field]
        cycle = await PrepareSubscriptionCycle(ctx.membership_ctx)(
            PrepareSubscriptionCycleInput(
                subject_type="identity",
                subject_id=workflow["subject_id"],
                level_key=validated["level_key"],
                source_type=source_type,
                source_ref=source_ref,
                idempotency_key=f"{source_type}:{source_ref}:prepare-cycle",
                auto_renew=bool(workflow.get("auto_renew", False)),
            )
        )
        return {
            "cycle_id": cycle.cycle_id,
            "subscription_id": cycle.subscription_id,
            "cycle_points_amount": cycle.cycle_points_amount,
            "cycle_end": cycle.cycle_end.isoformat(),
        }

    async def credit(_uow: UnitOfWork, data: dict[str, Any], _activity: Any) -> dict[str, Any]:
        from datetime import datetime

        workflow = data["workflow"]
        prepared = _result(data, prepare_key)
        entry = await CreditPoints(ctx.points_ctx)(
            MEMBERSHIP_CYCLE_BEHAVIOR_KEY,
            CreditDebitInput(
                subject_type="identity",
                subject_id=workflow["subject_id"],
                amount=prepared["cycle_points_amount"],
                source_type="membership",
                source_id=prepared["cycle_id"],
                idempotency_key=f"membership-cycle:{prepared['cycle_id']}",
                actor_type="system",
                expires_at=datetime.fromisoformat(prepared["cycle_end"]),
            ),
        )
        return {"entry_id": entry.id}

    async def attach(_uow: UnitOfWork, data: dict[str, Any], _activity: Any) -> dict[str, Any]:
        prepared = _result(data, prepare_key)
        credited = _result(data, credit_key)
        cycle = await AttachPointsGrant(ctx.membership_ctx)(
            AttachPointsGrantInput(
                cycle_id=prepared["cycle_id"],
                points_entry_ref=credited["entry_id"],
                idempotency_key=f"membership-cycle:{prepared['cycle_id']}:attach",
            )
        )
        return {"cycle_id": cycle.cycle_id, "subscription_id": cycle.subscription_id}

    activities = [
        ActivitySpec(key=validate_key, handler=validate),
        ActivitySpec(key=prepare_key, handler=prepare),
        ActivitySpec(key=credit_key, handler=credit),
        ActivitySpec(key=f"{prefix}.attach_cycle.v1", handler=attach),
    ]
    if include_notification:
        activities.append(
            ActivitySpec(
                key=f"{prefix}.notify.v1",
                handler=_notification_handler(ctx, kind="membership_purchase"),
            )
        )
    return WorkflowSpec(key=key, version="1", activities=tuple(activities))


async def _captured_order(ctx: UserCenterWorkflowContext, workflow: dict[str, Any]) -> Any:
    order = await ctx.payments.get_order(workflow["order_id"])
    if (
        order is None
        or order.subject_type != "identity"
        or order.subject_id != workflow["subject_id"]
    ):
        raise _error("user_center.order_not_found", "payment order was not found for subject")
    if order.state not in {"captured", "partially_refunded", "refunded"}:
        raise _error("user_center.order_not_captured", "payment order is not captured")
    return order


def _match_order(order: Any, version: str, price_cents: int) -> None:
    if order.offer_version != version or order.amount != price_cents or order.currency != "CNY":
        raise _error("user_center.version_conflict", "payment snapshot does not match catalog")


async def _redemption(ctx: UserCenterWorkflowContext, workflow: dict[str, Any]) -> Any:
    if ctx.gift_cards is None:
        raise _redemption_error("gift cards capability is unavailable")
    redemption = await ctx.gift_cards.get_redemption(workflow["redemption_id"])
    if (
        redemption is None
        or redemption.subject_type != "identity"
        or redemption.subject_id != workflow["subject_id"]
        or redemption.status not in {"reserved", "committed"}
    ):
        raise _redemption_error("gift card reservation is unavailable")
    return redemption


def _validate_redemption(ctx: UserCenterWorkflowContext, redemption: Any) -> Any:
    spec = ctx.gift_card_fulfillments.require(redemption.fulfillment_key)
    if (
        redemption.fulfillment_schema_version != spec.payload_version
        or redemption.platform_key not in spec.allowed_platforms
    ):
        raise _error("user_center.version_conflict", "gift-card fulfillment version mismatches")
    return spec


def _commit_handler(ctx: UserCenterWorkflowContext) -> Any:
    async def commit(_uow: UnitOfWork, data: dict[str, Any], _activity: Any) -> dict[str, Any]:
        if ctx.gift_cards_ctx is None:
            raise _redemption_error("gift cards capability is unavailable")
        workflow = data["workflow"]
        redemption = await CommitGiftCardRedemption(ctx.gift_cards_ctx)(
            CommitGiftCardRedemptionInput(
                redemption_id=workflow["redemption_id"],
                idempotency_key=workflow["redemption_key"],
            )
        )
        return {"redemption_id": redemption.id, "status": redemption.status}

    return commit


def _notification_handler(ctx: UserCenterWorkflowContext, *, kind: str) -> Any:
    async def notify(_uow: UnitOfWork, data: dict[str, Any], _activity: Any) -> dict[str, Any]:
        if ctx.notification_ctx is None:
            return {"requested": False}
        workflow = data["workflow"]
        source_ref = workflow.get("order_id") or workflow.get("redemption_id")
        result = await RequestNotification(ctx.notification_ctx)(
            RequestNotificationInput(
                trigger_name="usercenter.fulfillment_completed.v1",
                recipient_type="identity",
                recipient_id=workflow["subject_id"],
                variables={"kind": kind, "source_ref": source_ref},
                idempotency_key=f"user-center:{kind}:{source_ref}",
            )
        )
        return {"requested": True, "intent_id": result.intent.id}

    return notify


def _result(data: dict[str, Any], key: str) -> dict[str, Any]:
    result = data["state"].get(key)
    if not isinstance(result, dict):
        raise _error("user_center.fulfillment_pending", f"workflow prerequisite {key} is missing")
    return result


def _workflow(key: str, *activities: ActivitySpec) -> WorkflowSpec:
    return WorkflowSpec(key=key, version="1", activities=activities)


def _redemption_error(message: str) -> KernelError:
    return _error("user_center.redemption_unavailable", message)


def _error(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.CONFLICT, message=message)


__all__ = [
    "CHECK_IN_BEHAVIOR_KEY",
    "CHECK_IN_WORKFLOW_KEY",
    "GIFT_CARD_MEMBERSHIP_WORKFLOW_KEY",
    "GIFT_CARD_POINTS_WORKFLOW_KEY",
    "MEMBERSHIP_CYCLE_BEHAVIOR_KEY",
    "MEMBERSHIP_PURCHASE_WORKFLOW_KEY",
    "POINT_PURCHASE_BEHAVIOR_KEY",
    "POINT_PURCHASE_WORKFLOW_KEY",
    "REFUND_WORKFLOW_KEY",
    "UserCenterWorkflowContext",
    "build_check_in_workflow_spec",
    "build_gift_card_membership_workflow_spec",
    "build_gift_card_points_workflow_spec",
    "build_membership_purchase_workflow_spec",
    "build_point_purchase_workflow_spec",
    "build_refund_workflow_spec",
    "build_user_center_workflow_specs",
]

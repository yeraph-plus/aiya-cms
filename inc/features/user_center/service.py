"""Authenticated self-service gateway for the user-center feature."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from inc.capabilities.assets import (
    AssetQueries,
    CreateUploadIntent,
    CreateUploadIntentInput,
    CreateUploadIntentResult,
    FinalizeAsset,
)
from inc.capabilities.gift_cards import (
    CommandContext as GiftCardCommandContext,
)
from inc.capabilities.gift_cards import (
    ReserveGiftCardRedemption,
    ReserveGiftCardRedemptionInput,
)
from inc.capabilities.identity import (
    CommandContext as IdentityCommandContext,
)
from inc.capabilities.identity import (
    IdentityQueries,
    UpdateProfile,
    UpdateProfileInput,
)
from inc.capabilities.membership import CancelInput, CancelSubscription, MembershipQueries
from inc.capabilities.payments import (
    CommandContext as PaymentCommandContext,
)
from inc.capabilities.payments import (
    CreatePaymentOrder,
    CreatePaymentOrderInput,
    OrderDTO,
    PaymentsQueries,
)
from inc.capabilities.points import DEFAULT_PROGRAM_KEY, PointsQueries
from inc.features.user_center.catalog import (
    GiftCardFulfillmentRegistry,
    MembershipOfferRegistry,
    PointBundleRegistry,
)
from inc.features.user_center.workflows import (
    CHECK_IN_WORKFLOW_KEY,
    GIFT_CARD_MEMBERSHIP_WORKFLOW_KEY,
    GIFT_CARD_POINTS_WORKFLOW_KEY,
    MEMBERSHIP_PURCHASE_WORKFLOW_KEY,
    POINT_PURCHASE_WORKFLOW_KEY,
    REFUND_WORKFLOW_KEY,
)
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.time import Clock
from inc.kernel.workflow import WorkflowRunner


class PointsView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    opened: bool
    program_key: str = DEFAULT_PROGRAM_KEY
    balance: int = 0
    buckets: list[Any] = Field(default_factory=list)


class MeView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_id: str
    username: str
    display_name: str | None = None
    email: str
    email_verified: bool
    status: str
    avatar_asset_id: str | None = None
    avatar_url: str | None = None
    points: PointsView
    membership: Any | None = None


class CheckInResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    business_date: str
    entry_id: str | None = None


@dataclass(frozen=True, slots=True)
class UserCenterServiceContext:
    clock: Clock
    runner: WorkflowRunner
    identity_ctx: IdentityCommandContext
    identity: IdentityQueries
    points: PointsQueries
    membership_ctx: Any
    membership: MembershipQueries
    payments_ctx: PaymentCommandContext
    payments: PaymentsQueries
    gift_cards_ctx: GiftCardCommandContext
    assets_ctx: Any | None = None
    assets: AssetQueries | None = None


class UserCenterService:
    """Gateway consumed by the future HTTP adapter and event subscribers."""

    def __init__(
        self,
        *,
        ctx: UserCenterServiceContext,
        point_bundles: PointBundleRegistry,
        membership_offers: MembershipOfferRegistry,
        gift_card_fulfillments: GiftCardFulfillmentRegistry,
    ) -> None:
        if not all(
            registry.frozen
            for registry in (point_bundles, membership_offers, gift_card_fulfillments)
        ):
            raise _error(
                "user_center.registry_not_frozen",
                ErrorCategory.INTERNAL,
                "user-center registries must be frozen before service construction",
            )
        self._ctx = ctx
        self._point_bundles = point_bundles
        self._membership_offers = membership_offers
        self._gift_card_fulfillments = gift_card_fulfillments

    async def get_me(self, *, subject_id: str) -> MeView:
        subject = await self._ctx.identity.get_subject(subject_id)
        if subject is None:
            raise _error("identity.not_found", ErrorCategory.NOT_FOUND, "subject not found")
        try:
            balance = await self._ctx.points.get_balance(
                program_key=DEFAULT_PROGRAM_KEY,
                subject_type="identity",
                subject_id=subject_id,
            )
            buckets = await self._ctx.points.list_buckets(
                program_key=DEFAULT_PROGRAM_KEY,
                subject_type="identity",
                subject_id=subject_id,
            )
            points = PointsView(opened=True, balance=balance.balance, buckets=buckets)
        except KernelError as exc:
            if exc.code != "points.account_not_opened":
                raise
            points = PointsView(opened=False)
        subscription = await self._ctx.membership.get_subscription(
            subject_type="identity", subject_id=subject_id
        )
        avatar_url = await self._avatar_url(subject.avatar_asset_id)
        return MeView(
            subject_id=subject.id,
            username=subject.username,
            display_name=subject.display_name,
            email=subject.email,
            email_verified=subject.email_verified,
            status=subject.status,
            avatar_asset_id=subject.avatar_asset_id,
            avatar_url=avatar_url,
            points=points,
            membership=subscription,
        )

    async def update_profile(self, *, subject_id: str, changes: UpdateProfileInput) -> MeView:
        await UpdateProfile(self._ctx.identity_ctx)(user_id=subject_id, changes=changes)
        return await self.get_me(subject_id=subject_id)

    async def create_avatar_upload_intent(
        self, *, subject_id: str, input_: CreateUploadIntentInput
    ) -> CreateUploadIntentResult:
        del subject_id
        if self._ctx.assets_ctx is None:
            raise _unavailable("assets capability is unavailable")
        return await CreateUploadIntent(self._ctx.assets_ctx)(input_)

    async def finalize_avatar(self, *, subject_id: str, intent_id: str) -> Any:
        if self._ctx.assets_ctx is None or self._ctx.assets is None:
            raise _unavailable("assets capability is unavailable")
        result = await FinalizeAsset(self._ctx.assets_ctx)(uuid.UUID(intent_id))
        instance = await self._ctx.runner.find_by_business_key(
            workflow_key="assets.finalize.v1", idempotency_key=f"intent:{intent_id}"
        )
        if instance is None:
            raise _unavailable("asset finalize workflow did not start")
        await self._ctx.runner.advance(instance.id)
        asset = await self._ctx.assets.get_by_upload_intent(
            uuid.UUID(intent_id), permissions=frozenset({"assets.read"})
        )
        if asset is None:
            return result
        await UpdateProfile(self._ctx.identity_ctx)(
            user_id=subject_id, changes=UpdateProfileInput(avatar_asset_id=asset.id)
        )
        return await self.get_me(subject_id=subject_id)

    async def check_in(
        self, *, subject_id: str, idempotency_key: str, timezone: str = "Asia/Shanghai"
    ) -> CheckInResult:
        _require_idempotency_key(idempotency_key)
        business_date = self._ctx.clock.utc_now().astimezone(ZoneInfo(timezone)).date().isoformat()
        workflow_key = f"{subject_id}:credit:{business_date}:v1"
        previous = await self._ctx.runner.find_by_business_key(
            workflow_key=CHECK_IN_WORKFLOW_KEY, idempotency_key=workflow_key
        )
        instance = await self._ctx.runner.start(
            workflow_key=CHECK_IN_WORKFLOW_KEY,
            idempotency_key=workflow_key,
            input_data={"subject_id": subject_id, "business_date": business_date},
        )
        await self._ctx.runner.advance(instance.id)
        completed = await self._ctx.runner.find_by_business_key(
            workflow_key=CHECK_IN_WORKFLOW_KEY, idempotency_key=workflow_key
        )
        result = (
            completed.state.data.get("user_center.check_in.credit.v1")
            if completed is not None
            else None
        )
        return CheckInResult(
            status="already_rewarded" if previous is not None else "rewarded",
            business_date=business_date,
            entry_id=result.get("entry_id") if isinstance(result, dict) else None,
        )

    async def create_point_order(
        self,
        *,
        subject_id: str,
        product_key: str,
        provider_key: str,
        idempotency_key: str,
    ) -> OrderDTO:
        _require_idempotency_key(idempotency_key)
        bundle = self._point_bundles.require(product_key)
        _require_available(bundle, self._ctx.clock.utc_now())
        return await CreatePaymentOrder(self._ctx.payments_ctx)(
            CreatePaymentOrderInput(
                subject_type="identity",
                subject_id=subject_id,
                provider_key=provider_key,
                offer_key=bundle.product_key,
                offer_version=bundle.version,
                description=bundle.display_name,
                amount=bundle.price_cents,
                idempotency_key=f"user-center:points:{subject_id}:{idempotency_key}",
            )
        )

    async def list_point_products(self) -> tuple[Any, ...]:
        return self._point_bundles.specs()

    async def create_membership_order(
        self,
        *,
        subject_id: str,
        offer_key: str,
        provider_key: str,
        idempotency_key: str,
        renewal: bool = False,
    ) -> OrderDTO:
        _require_idempotency_key(idempotency_key)
        offer = self._membership_offers.require(offer_key)
        _require_available(offer, self._ctx.clock.utc_now())
        if (renewal and not offer.renewal_allowed) or (not renewal and not offer.purchase_allowed):
            raise _error(
                "user_center.product_unavailable",
                ErrorCategory.CONFLICT,
                "membership offer does not allow this purchase",
            )
        return await CreatePaymentOrder(self._ctx.payments_ctx)(
            CreatePaymentOrderInput(
                subject_type="identity",
                subject_id=subject_id,
                provider_key=provider_key,
                offer_key=offer.offer_key,
                offer_version=offer.version,
                description=offer.display_name,
                amount=offer.price_cents,
                idempotency_key=f"user-center:membership:{subject_id}:{idempotency_key}",
            )
        )

    async def fulfill_captured_payment(self, *, order_id: str) -> Any:
        order = await self._ctx.payments.get_order(order_id)
        if order is None:
            raise _error("user_center.order_not_found", ErrorCategory.NOT_FOUND, "order not found")
        if order.offer_key in {item.product_key for item in self._point_bundles.specs()}:
            workflow_key = POINT_PURCHASE_WORKFLOW_KEY
        elif order.offer_key in {item.offer_key for item in self._membership_offers.specs()}:
            workflow_key = MEMBERSHIP_PURCHASE_WORKFLOW_KEY
        else:
            raise _error(
                "user_center.version_conflict", ErrorCategory.CONFLICT, "unknown order offer"
            )
        return await self._ctx.runner.start(
            workflow_key=workflow_key,
            idempotency_key=f"payment-order:{order.id}:captured",
            input_data={"order_id": order.id, "subject_id": order.subject_id},
        )

    async def redeem_gift_card(
        self,
        *,
        subject_id: str,
        secret: str,
        idempotency_key: str,
        platform_key: str | None = None,
    ) -> Any:
        _require_idempotency_key(idempotency_key)
        redemption_key = f"user-center:{subject_id}:{idempotency_key}"
        redemption = await ReserveGiftCardRedemption(self._ctx.gift_cards_ctx)(
            ReserveGiftCardRedemptionInput(
                secret=secret,
                subject_type="identity",
                subject_id=subject_id,
                platform_key=platform_key,
                idempotency_key=redemption_key,
            )
        )
        fulfillment = self._gift_card_fulfillments.require(redemption.fulfillment_key)
        workflow_key = (
            GIFT_CARD_POINTS_WORKFLOW_KEY
            if fulfillment.fulfillment_type == "points_bundle"
            else GIFT_CARD_MEMBERSHIP_WORKFLOW_KEY
        )
        return await self._ctx.runner.start(
            workflow_key=workflow_key,
            idempotency_key=f"gift-card:{redemption.id}:fulfill",
            input_data={
                "redemption_id": redemption.id,
                "redemption_key": redemption_key,
                "subject_id": subject_id,
            },
        )

    async def compensate_refund(self, *, order_id: str, refund_id: str, subject_id: str) -> Any:
        return await self._ctx.runner.start(
            workflow_key=REFUND_WORKFLOW_KEY,
            idempotency_key=f"payment-refund:{refund_id}",
            input_data={
                "order_id": order_id,
                "refund_id": refund_id,
                "subject_id": subject_id,
            },
        )

    async def cancel_membership(self, *, subject_id: str, reason: str) -> Any:
        subscription = await self._ctx.membership.get_subscription(
            subject_type="identity", subject_id=subject_id
        )
        if subscription is None:
            raise _error(
                "user_center.membership_not_found",
                ErrorCategory.NOT_FOUND,
                "membership subscription not found",
            )
        return await CancelSubscription(self._ctx.membership_ctx)(
            CancelInput(subscription_id=subscription.id, reason=reason)
        )

    async def get_payment_order(self, *, subject_id: str, order_id: str) -> Any:
        detail = await self._ctx.payments.get_order_detail(order_id)
        if detail is None or detail.order.subject_id != subject_id:
            raise _error("user_center.order_not_found", ErrorCategory.NOT_FOUND, "order not found")
        return detail

    async def list_purchases(self, *, subject_id: str, page: int, size: int) -> Any:
        return await self._ctx.payments.list_orders(
            page=page,
            size=size,
            subject_type="identity",
            subject_id=subject_id,
        )

    async def _avatar_url(self, asset_id: str | None) -> str | None:
        if not asset_id or self._ctx.assets is None:
            return None
        try:
            resolved = await self._ctx.assets.resolve_url(
                uuid.UUID(asset_id), permissions=frozenset({"assets.read"})
            )
            return resolved.url
        except KernelError, ValueError:
            return None


def _require_available(spec: Any, now: datetime) -> None:
    if not getattr(spec, "available", True):
        raise _error(
            "user_center.product_unavailable", ErrorCategory.CONFLICT, "product is unavailable"
        )
    if spec.available_from is not None and now < spec.available_from:
        raise _error(
            "user_center.product_unavailable",
            ErrorCategory.CONFLICT,
            "product is not yet available",
        )
    if spec.available_until is not None and now >= spec.available_until:
        raise _error(
            "user_center.product_unavailable",
            ErrorCategory.CONFLICT,
            "product is no longer available",
        )


def _require_idempotency_key(value: str) -> None:
    if not value or len(value) > 200:
        raise _error(
            "user_center.invalid_idempotency_key",
            ErrorCategory.VALIDATION,
            "idempotency key is required",
        )


def _unavailable(message: str) -> KernelError:
    return _error(
        "user_center.dependency_unavailable",
        ErrorCategory.DEPENDENCY_UNAVAILABLE,
        message,
    )


def _error(code: str, category: ErrorCategory, message: str) -> KernelError:
    return KernelError(code=code, category=category, message=message)


__all__ = [
    "CheckInResult",
    "MeView",
    "PointsView",
    "UserCenterService",
    "UserCenterServiceContext",
]

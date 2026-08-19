"""Authenticated user-center HTTP adapter.

The user-center service is the public composition boundary for these routes.
This module only validates HTTP input and supplies the authenticated subject.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Depends, Header, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.assets import CreateUploadIntentInput
from inc.capabilities.identity import UpdateProfileInput
from inc.capabilities.points import DEFAULT_PROGRAM_KEY
from inc.kernel.errors import ErrorCategory, KernelError


class MembershipOrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_key: str = Field(min_length=1, max_length=200)
    provider_key: str = Field(min_length=1, max_length=100)
    renewal: bool = False


class CancelMembershipInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class PointOrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_key: str = Field(min_length=1, max_length=200)
    provider_key: str = Field(min_length=1, max_length=100)


class GiftCardRedemptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: str = Field(min_length=1, max_length=500)
    platform_key: str | None = Field(default=None, min_length=1, max_length=64)


def _service(services: Services) -> Any:
    user_center = getattr(services, "user_center", None)
    if user_center is None:
        raise KernelError(
            code="user_center.unavailable",
            category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
            message="user-center service is unavailable",
        )
    return cast(Any, user_center)


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any,
) -> APIRouter:
    del require_capability
    router = APIRouter(prefix="/api/v1", tags=["user-center"])

    @router.get("/me")
    async def get_me(ctx: AppContext = Depends(require_authenticated())) -> Any:
        return await _service(services).get_me(subject_id=ctx.principal.subject_id)

    @router.patch("/me")
    async def patch_me(
        body: UpdateProfileInput,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> Any:
        del idempotency_key
        return await _service(services).update_profile(
            subject_id=ctx.principal.subject_id, changes=body
        )

    @router.post("/me/avatar/upload-intents")
    async def avatar_intent(
        body: CreateUploadIntentInput,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> Any:
        del idempotency_key
        return await _service(services).create_avatar_upload_intent(
            subject_id=ctx.principal.subject_id, input_=body
        )

    @router.post("/me/avatar/upload-intents/{intent_id}/finalize")
    async def avatar_finalize(
        intent_id: str = Path(..., min_length=1, max_length=200),
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> Any:
        del idempotency_key
        return await _service(services).finalize_avatar(
            subject_id=ctx.principal.subject_id, intent_id=intent_id
        )

    @router.post("/me/check-ins")
    async def check_in(
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> Any:
        return await _service(services).check_in(
            subject_id=ctx.principal.subject_id, idempotency_key=idempotency_key
        )

    @router.get("/me/points")
    async def points(ctx: AppContext = Depends(require_authenticated())) -> Any:
        me = await _service(services).get_me(subject_id=ctx.principal.subject_id)
        return me.points

    @router.get("/me/points/ledger")
    async def points_ledger(
        page: int = Query(1, ge=1),
        size: int = Query(20, ge=1, le=100),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> Any:
        return await services.points_queries.list_ledger(
            program_key=DEFAULT_PROGRAM_KEY,
            subject_type="identity",
            subject_id=ctx.principal.subject_id,
            page=page,
            size=size,
        )

    @router.get("/membership/levels")
    async def membership_levels() -> Any:
        if services.membership_queries is None:
            raise KernelError(
                code="membership.unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="membership query service is unavailable",
            )
        return await services.membership_queries.list_levels()

    @router.get("/me/membership")
    async def membership(ctx: AppContext = Depends(require_authenticated())) -> Any:
        me = await _service(services).get_me(subject_id=ctx.principal.subject_id)
        return me.membership

    @router.post("/me/membership/orders")
    async def membership_order(
        body: MembershipOrderInput,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> Any:
        return await _service(services).create_membership_order(
            subject_id=ctx.principal.subject_id,
            offer_key=body.offer_key,
            provider_key=body.provider_key,
            renewal=body.renewal,
            idempotency_key=idempotency_key,
        )

    @router.post("/me/membership/cancel")
    async def membership_cancel(
        body: CancelMembershipInput,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> Any:
        del idempotency_key
        return await _service(services).cancel_membership(
            subject_id=ctx.principal.subject_id, reason=body.reason
        )

    @router.get("/points/products")
    async def point_products() -> Any:
        return await _service(services).list_point_products()

    @router.post("/me/points/orders")
    async def point_order(
        body: PointOrderInput,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> Any:
        return await _service(services).create_point_order(
            subject_id=ctx.principal.subject_id,
            product_key=body.product_key,
            provider_key=body.provider_key,
            idempotency_key=idempotency_key,
        )

    @router.get("/me/payment-orders/{order_id}")
    async def payment_order(
        order_id: str = Path(..., min_length=1, max_length=200),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> Any:
        return await _service(services).get_payment_order(
            subject_id=ctx.principal.subject_id, order_id=order_id
        )

    @router.post("/me/gift-cards/redemptions")
    async def gift_card_redemption(
        body: GiftCardRedemptionInput,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> Any:
        return await _service(services).redeem_gift_card(
            subject_id=ctx.principal.subject_id,
            secret=body.secret,
            platform_key=body.platform_key,
            idempotency_key=idempotency_key,
        )

    @router.get("/me/purchases")
    async def purchases(
        page: int = Query(1, ge=1),
        size: int = Query(20, ge=1, le=100),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> Any:
        # Purchase history is an aggregate owned by user_center, not a raw
        # payments query. The public service method is required until its
        # cross-capability read model is available on Services.
        return await _service(services).list_purchases(
            subject_id=ctx.principal.subject_id, page=page, size=size
        )

    return router


__all__ = ["build_router"]

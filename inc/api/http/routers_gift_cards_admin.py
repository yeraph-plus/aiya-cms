"""Administrator HTTP adapter for gift-card batches and redemption facts."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from fastapi import APIRouter, Depends, Path, Query

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.gift_cards import (
    CancelGiftCardRedemption,
    CloseGiftCardBatch,
    CommitGiftCardRedemption,
    GenerateGiftCardBatch,
    RecordProviderPurchase,
    ReserveGiftCardRedemption,
    RevokeGiftCard,
)
from inc.capabilities.gift_cards.commands import CommandContext
from inc.capabilities.gift_cards.queries import GiftCardQueries
from inc.capabilities.gift_cards.schemas import (
    CancelGiftCardRedemptionInput,
    CloseGiftCardBatchInput,
    CommitGiftCardRedemptionInput,
    GenerateGiftCardBatchInput,
    GiftCardBatchDTO,
    GiftCardBatchResultDTO,
    GiftCardDTO,
    GiftCardVerifyDTO,
    ProviderPurchaseInput,
    RedemptionDTO,
    ReserveGiftCardRedemptionInput,
    RevokeGiftCardInput,
    VerifyGiftCardInput,
)
from inc.kernel.db import Page
from inc.kernel.errors import ErrorCategory, KernelError

REQUIRED_PERMISSIONS: tuple[str, ...] = (
    "gift_cards.batch_generate",
    "gift_cards.manage",
    "gift_cards.verify",
    "gift_cards.redeem",
    "gift_cards.reconcile",
)


def _command_ctx(services: Services, request: AppContext) -> CommandContext:
    base = services.gift_card_context
    if base is None:
        raise KernelError(
            code="gift_cards.unavailable",
            category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
            message="gift cards are not enabled",
        )
    return replace(
        base,
        permissions=frozenset(request.principal.capabilities),
        actor_id=request.principal.subject_id,
        trace_id=request.trace_id,
    )


def _queries(services: Services) -> GiftCardQueries:
    if services.gift_card_queries is None:
        raise KernelError(
            code="gift_cards.unavailable",
            category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
            message="gift cards are not enabled",
        )
    return services.gift_card_queries


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any = None,
) -> APIRouter:
    del require_authenticated
    router = APIRouter(prefix="/api/v1/admin", tags=["admin", "admin-gift-cards"])

    @router.get("/gift-cards/batches", response_model=Page[GiftCardBatchDTO])
    async def list_batches(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        platform_key: str | None = Query(default=None, min_length=1, max_length=64),
        product_key: str | None = Query(default=None, min_length=1, max_length=100),
        status: str | None = Query(default=None, min_length=1, max_length=16),
        ctx: AppContext = Depends(require_capability("gift_cards.manage")),
    ) -> Page[GiftCardBatchDTO]:
        del ctx
        return await _queries(services).list_batches(
            page=page, size=size, platform_key=platform_key, product_key=product_key, status=status
        )

    @router.get("/gift-cards/batches/{batch_id}", response_model=GiftCardBatchDTO)
    async def get_batch(
        batch_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("gift_cards.manage")),
    ) -> GiftCardBatchDTO:
        del ctx
        batch = await _queries(services).get_batch(batch_id)
        if batch is None:
            raise KernelError(
                code="gift_cards.batch_not_found",
                category=ErrorCategory.NOT_FOUND,
                message="gift card batch not found",
            )
        return batch

    @router.get("/gift-cards/batches/{batch_id}/cards", response_model=Page[GiftCardDTO])
    async def list_cards(
        batch_id: str = Path(...),
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        ctx: AppContext = Depends(require_capability("gift_cards.manage")),
    ) -> Page[GiftCardDTO]:
        del ctx
        return await _queries(services).list_cards(batch_id=batch_id, page=page, size=size)

    @router.post("/gift-cards/batches", response_model=GiftCardBatchResultDTO)
    async def generate_batch(
        body: GenerateGiftCardBatchInput,
        ctx: AppContext = Depends(require_capability("gift_cards.batch_generate")),
    ) -> GiftCardBatchResultDTO:
        return await GenerateGiftCardBatch(_command_ctx(services, ctx))(body)

    @router.post("/gift-cards/batches/{batch_id}/close", response_model=GiftCardBatchDTO)
    async def close_batch(
        body: CloseGiftCardBatchInput,
        batch_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("gift_cards.manage")),
    ) -> GiftCardBatchDTO:
        body.batch_id = batch_id
        return await CloseGiftCardBatch(_command_ctx(services, ctx))(body)

    @router.post("/gift-cards/{card_id}/revoke", response_model=GiftCardDTO)
    async def revoke_card(
        body: RevokeGiftCardInput,
        card_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("gift_cards.manage")),
    ) -> GiftCardDTO:
        body.card_id = card_id
        return await RevokeGiftCard(_command_ctx(services, ctx))(body)

    @router.post("/gift-cards/verify", response_model=GiftCardVerifyDTO)
    async def verify_card(
        body: VerifyGiftCardInput,
        ctx: AppContext = Depends(require_capability("gift_cards.verify")),
    ) -> GiftCardVerifyDTO:
        del ctx
        return await _queries(services).verify(secret=body.secret, platform_key=body.platform_key)

    @router.post("/gift-cards/redemptions/reserve", response_model=RedemptionDTO)
    async def reserve_redemption(
        body: ReserveGiftCardRedemptionInput,
        ctx: AppContext = Depends(require_capability("gift_cards.redeem")),
    ) -> RedemptionDTO:
        return await ReserveGiftCardRedemption(_command_ctx(services, ctx))(body)

    @router.get("/gift-cards/redemptions/{redemption_id}", response_model=RedemptionDTO)
    async def get_redemption(
        redemption_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("gift_cards.manage")),
    ) -> RedemptionDTO:
        del ctx
        item = await _queries(services).get_redemption(redemption_id)
        if item is None:
            raise KernelError(
                code="gift_cards.redemption_not_found",
                category=ErrorCategory.NOT_FOUND,
                message="redemption not found",
            )
        return item

    @router.post("/gift-cards/redemptions/{redemption_id}/commit", response_model=RedemptionDTO)
    async def commit_redemption(
        body: CommitGiftCardRedemptionInput,
        redemption_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("gift_cards.redeem")),
    ) -> RedemptionDTO:
        body.redemption_id = redemption_id
        return await CommitGiftCardRedemption(_command_ctx(services, ctx))(body)

    @router.post("/gift-cards/redemptions/{redemption_id}/cancel", response_model=RedemptionDTO)
    async def cancel_redemption(
        body: CancelGiftCardRedemptionInput,
        redemption_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("gift_cards.redeem")),
    ) -> RedemptionDTO:
        body.redemption_id = redemption_id
        return await CancelGiftCardRedemption(_command_ctx(services, ctx))(body)

    @router.post("/gift-cards/provider-facts", response_model=dict[str, Any])
    async def record_provider_fact(
        body: ProviderPurchaseInput,
        ctx: AppContext = Depends(require_capability("gift_cards.reconcile")),
    ) -> dict[str, Any]:
        return await RecordProviderPurchase(_command_ctx(services, ctx))(body)

    return router

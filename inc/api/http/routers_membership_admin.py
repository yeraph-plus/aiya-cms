"""Administrator membership levels and subscription management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Query

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.membership.commands import (
    CancelSubscription,
    CommandContext,
    TerminateSubscription,
)
from inc.capabilities.membership.schemas import (
    CancelInput,
    LevelDTO,
    RenewalRecordDTO,
    SubscriptionDTO,
    TerminateInput,
)
from inc.kernel.db import Page

REQUIRED_PERMISSIONS: tuple[str, ...] = ("membership.read", "membership.manage")


def _ctx(ctx: AppContext, services: Services) -> CommandContext:
    return CommandContext(
        uow_factory=ctx.uow_factory,
        clock=ctx.clock,
        outbox=services.outbox,
        levels=services.membership_levels,  # type: ignore[arg-type]
        subject_exists=services.adapters["membership.subject_exists"],
        points_ledger=services.adapters["membership.points_ledger"],
        permissions=frozenset(ctx.principal.capabilities),
        actor_id=ctx.principal.subject_id,
        trace_id=ctx.trace_id,
    )


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin", tags=["admin", "admin-membership"])

    @router.get("/membership/levels", response_model=list[LevelDTO])
    async def list_levels(
        ctx: AppContext = Depends(require_capability("membership.read")),
    ) -> list[LevelDTO]:
        del ctx
        assert services.membership_queries is not None
        return await services.membership_queries.list_levels()

    @router.get("/membership/subscriptions", response_model=Page[SubscriptionDTO])
    async def list_subscriptions(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        subject_type: str | None = Query(default=None, min_length=1, max_length=32),
        subject_id: str | None = Query(default=None, min_length=1, max_length=200),
        level_key: str | None = Query(default=None, min_length=1, max_length=100),
        status: str | None = Query(default=None, min_length=1, max_length=32),
        ctx: AppContext = Depends(require_capability("membership.read")),
    ) -> Page[SubscriptionDTO]:
        del ctx
        assert services.membership_queries is not None
        return await services.membership_queries.list_subscriptions(
            page=page,
            size=size,
            subject_type=subject_type,
            subject_id=subject_id,
            level_key=level_key,
            status=status,
        )

    @router.get(
        "/membership/subscriptions/{subscription_id}/renewals",
        response_model=Page[RenewalRecordDTO],
    )
    async def list_renewals(
        subscription_id: str = Path(...),
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        ctx: AppContext = Depends(require_capability("membership.read")),
    ) -> Page[RenewalRecordDTO]:
        del ctx
        assert services.membership_queries is not None
        return await services.membership_queries.list_renewal_records(
            subscription_id=subscription_id, page=page, size=size
        )

    @router.post(
        "/membership/subscriptions/{subscription_id}/cancel", response_model=SubscriptionDTO
    )
    async def cancel_subscription(
        body: CancelInput,
        subscription_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("membership.manage")),
    ) -> SubscriptionDTO:
        body.subscription_id = subscription_id
        return await CancelSubscription(_ctx(ctx, services))(body)

    @router.post(
        "/membership/subscriptions/{subscription_id}/terminate", response_model=SubscriptionDTO
    )
    async def terminate_subscription(
        body: TerminateInput,
        subscription_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("membership.manage")),
    ) -> SubscriptionDTO:
        body.subscription_id = subscription_id
        return await TerminateSubscription(_ctx(ctx, services))(body)

    return router

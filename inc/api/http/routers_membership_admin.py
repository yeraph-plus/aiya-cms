"""Administrator membership levels and subscription management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Query

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.api.http.projections import AdminSubjectRefDTO
from inc.capabilities.membership.commands import (
    CancelSubscription,
    CommandContext,
    RenewSubscription,
    SubscribeLevel,
    TerminateSubscription,
)
from inc.capabilities.membership.schemas import (
    CancelInput,
    CreateLevelInput,
    LevelDTO,
    LevelStatusInput,
    MembershipSummaryDTO,
    RenewalRecordDTO,
    RenewInput,
    SubscribeInput,
    SubscriptionDTO,
    TerminateInput,
    UpdateLevelInput,
)
from inc.kernel.db import Page
from inc.kernel.errors import ErrorCategory, KernelError

REQUIRED_PERMISSIONS: tuple[str, ...] = ("membership.read", "membership.manage")


class AdminSubscriptionDTO(SubscriptionDTO):
    subject: AdminSubjectRefDTO | None = None


async def _decorate_subscription(services: Services, item: SubscriptionDTO) -> AdminSubscriptionDTO:
    subject = None
    if item.subject_type == "identity":
        found = await services.identity_queries.get_subjects([item.subject_id])
        profile = found.get(item.subject_id)
        if profile is not None:
            subject = AdminSubjectRefDTO(
                subject_type=item.subject_type,
                subject_id=item.subject_id,
                username=profile.username,
                display_name=profile.display_name,
                avatar_asset_id=profile.avatar_asset_id,
            )
    return AdminSubscriptionDTO(**item.model_dump(), subject=subject)


async def _decorate_subscriptions(
    services: Services, page: Page[SubscriptionDTO]
) -> Page[AdminSubscriptionDTO]:
    ids = {item.subject_id for item in page.items if item.subject_type == "identity"}
    profiles = await services.identity_queries.get_subjects(ids)
    return Page(
        items=[
            AdminSubscriptionDTO(
                **item.model_dump(),
                subject=(
                    AdminSubjectRefDTO(
                        subject_type=item.subject_type,
                        subject_id=item.subject_id,
                        username=profiles[item.subject_id].username,
                        display_name=profiles[item.subject_id].display_name,
                        avatar_asset_id=profiles[item.subject_id].avatar_asset_id,
                    )
                    if item.subject_type == "identity" and item.subject_id in profiles
                    else None
                ),
            )
            for item in page.items
        ],
        total=page.total,
        page=page.page,
        size=page.size,
    )


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

    @router.post("/membership/levels", response_model=LevelDTO)
    async def create_level(
        body: CreateLevelInput,
        ctx: AppContext = Depends(require_capability("membership.levels.manage")),
    ) -> LevelDTO:
        if services.membership_admin is None:
            raise KernelError(
                code="membership.unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="membership admin service is unavailable",
            )
        return await services.membership_admin.create_level(
            body, actor_id=ctx.principal.subject_id, trace_id=ctx.trace_id
        )

    @router.patch("/membership/levels/{level_key}", response_model=LevelDTO)
    async def update_level(
        body: UpdateLevelInput,
        level_key: str = Path(..., min_length=1, max_length=100),
        ctx: AppContext = Depends(require_capability("membership.levels.manage")),
    ) -> LevelDTO:
        if services.membership_admin is None:
            raise KernelError(
                code="membership.unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="membership admin service is unavailable",
            )
        return await services.membership_admin.update_level(
            level_key, body, actor_id=ctx.principal.subject_id, trace_id=ctx.trace_id
        )

    @router.post("/membership/levels/{level_key}/activate", response_model=LevelDTO)
    async def activate_level(
        body: LevelStatusInput,
        level_key: str,
        ctx: AppContext = Depends(require_capability("membership.levels.manage")),
    ) -> LevelDTO:
        if services.membership_admin is None:
            raise KernelError(
                code="membership.unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="membership admin service is unavailable",
            )
        return await services.membership_admin.set_level_status(
            level_key, "active", body, actor_id=ctx.principal.subject_id, trace_id=ctx.trace_id
        )

    @router.post("/membership/levels/{level_key}/archive", response_model=LevelDTO)
    async def archive_level(
        body: LevelStatusInput,
        level_key: str,
        ctx: AppContext = Depends(require_capability("membership.levels.manage")),
    ) -> LevelDTO:
        if services.membership_admin is None:
            raise KernelError(
                code="membership.unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="membership admin service is unavailable",
            )
        return await services.membership_admin.set_level_status(
            level_key, "archived", body, actor_id=ctx.principal.subject_id, trace_id=ctx.trace_id
        )

    @router.get("/membership/summary", response_model=MembershipSummaryDTO)
    async def membership_summary(
        ctx: AppContext = Depends(require_capability("membership.read")),
    ) -> MembershipSummaryDTO:
        del ctx
        if services.membership_admin is None:
            raise KernelError(
                code="membership.unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="membership levels are not enabled",
            )
        return await services.membership_admin.summary()

    @router.post("/membership/subscriptions", response_model=AdminSubscriptionDTO)
    async def subscribe(
        body: SubscribeInput,
        ctx: AppContext = Depends(require_capability("membership.manage")),
    ) -> AdminSubscriptionDTO:
        return await _decorate_subscription(
            services, await SubscribeLevel(_ctx(ctx, services))(body)
        )

    @router.post(
        "/membership/subscriptions/{subscription_id}/renew", response_model=AdminSubscriptionDTO
    )
    async def renew(
        body: RenewInput,
        subscription_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("membership.manage")),
    ) -> AdminSubscriptionDTO:
        body.subscription_id = subscription_id
        return await _decorate_subscription(
            services, await RenewSubscription(_ctx(ctx, services))(body)
        )

    @router.get("/membership/subscriptions", response_model=Page[AdminSubscriptionDTO])
    async def list_subscriptions(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        subject_type: str | None = Query(default=None, min_length=1, max_length=32),
        subject_id: str | None = Query(default=None, min_length=1, max_length=200),
        level_key: str | None = Query(default=None, min_length=1, max_length=100),
        status: str | None = Query(default=None, min_length=1, max_length=32),
        ctx: AppContext = Depends(require_capability("membership.read")),
    ) -> Page[AdminSubscriptionDTO]:
        del ctx
        assert services.membership_queries is not None
        result = await services.membership_queries.list_subscriptions(
            page=page,
            size=size,
            subject_type=subject_type,
            subject_id=subject_id,
            level_key=level_key,
            status=status,
        )
        return await _decorate_subscriptions(services, result)

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
        "/membership/subscriptions/{subscription_id}/cancel", response_model=AdminSubscriptionDTO
    )
    async def cancel_subscription(
        body: CancelInput,
        subscription_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("membership.manage")),
    ) -> AdminSubscriptionDTO:
        body.subscription_id = subscription_id
        return await _decorate_subscription(
            services, await CancelSubscription(_ctx(ctx, services))(body)
        )

    @router.post(
        "/membership/subscriptions/{subscription_id}/terminate", response_model=AdminSubscriptionDTO
    )
    async def terminate_subscription(
        body: TerminateInput,
        subscription_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("membership.manage")),
    ) -> AdminSubscriptionDTO:
        body.subscription_id = subscription_id
        return await _decorate_subscription(
            services, await TerminateSubscription(_ctx(ctx, services))(body)
        )

    return router

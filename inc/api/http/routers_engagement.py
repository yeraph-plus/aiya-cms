"""Authenticated favorites and administrator engagement statistics."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.engagement.schemas import EngagementSummaryDTO, FavoritePageDTO

REQUIRED_PERMISSIONS: tuple[str, ...] = ("engagement.read",)


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["engagement"])

    @router.get("/me/favorites/{type_name}", response_model=FavoritePageDTO)
    async def list_favorites(
        type_name: str,
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> FavoritePageDTO:
        if services.engagement_queries is None:
            raise RuntimeError("engagement capability is not available")
        return await services.engagement_queries.list_favorites(
            ctx.principal.subject_id, page=page, size=size, type_name=type_name
        )

    @router.get(
        "/admin/engagement",
        response_model=list[EngagementSummaryDTO],
        tags=["admin", "admin-engagement"],
    )
    async def list_engagement_stats(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        sort: str = Query(default="-view_count", max_length=64),
        ctx: AppContext = Depends(require_capability("engagement.read")),
    ) -> list[EngagementSummaryDTO]:
        del ctx
        if services.engagement_queries is None:
            raise RuntimeError("engagement capability is not available")
        items, _total = await services.engagement_queries.list_stats(
            page=page, size=size, sort=sort
        )
        return items

    return router

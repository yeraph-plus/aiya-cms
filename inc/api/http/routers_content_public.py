"""Published content read and engagement HTTP surface."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.api.http.routers_content import (
    _contains_engagement_sort,
    _list_with_engagement_sort,
)
from inc.capabilities.content.schemas import ContentDTO, ContentPageDTO
from inc.capabilities.engagement.schemas import (
    EngagementSummaryDTO,
    LikeContentInput,
    RateContentInput,
    RecordContentViewInput,
    UnlikeContentInput,
    WithdrawRatingInput,
)


class RatingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: int = Field(ge=1, le=5)


REQUIRED_PERMISSIONS: tuple[str, ...] = ()


def _summary_or_empty(content_id: uuid.UUID) -> EngagementSummaryDTO:
    return EngagementSummaryDTO(content_id=str(content_id))


async def _require_published_type(
    services: Services, type_name: str, content_id: uuid.UUID
) -> None:
    content = await services.content_queries.get(content_id)
    if content is None or content.type_name != type_name or content.status != "published":
        from inc.kernel.errors import ErrorCategory, KernelError

        raise KernelError(
            code="content.not_found",
            category=ErrorCategory.NOT_FOUND,
            message="published content not found",
        )


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any = None,
) -> APIRouter:
    del require_capability
    router = APIRouter(prefix="/api/v1/content", tags=["content", "engagement"])

    @router.get("/{type_name}", response_model=ContentPageDTO)
    async def list_published_content(
        type_name: str = Path(..., min_length=1, max_length=64),
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        sort: str | None = Query(default=None, max_length=200),
    ) -> ContentPageDTO:
        if sort and _contains_engagement_sort(sort):
            return await _list_with_engagement_sort(
                services,
                page=page,
                size=size,
                type_name=type_name,
                status=None,
                sort=sort,
                public_only=True,
            )
        result = await services.content_queries.list_contents(
            page=page, size=size, type_name=type_name, public_only=True, sort=sort
        )
        if services.engagement_queries is None:
            return result
        return result.model_copy(
            update={
                "items": [
                    item.model_copy(
                        update={
                            "engagement": await services.engagement_queries.get_summary(
                                uuid.UUID(item.id)
                            )
                        }
                    )
                    for item in result.items
                ]
            }
        )

    @router.get("/{type_name}/{content_id}", response_model=ContentDTO)
    async def get_published_content(
        type_name: str = Path(..., min_length=1, max_length=64),
        content_id: uuid.UUID = Path(...),
    ) -> ContentDTO:
        content = await services.content_queries.get(content_id)
        if content is None or content.type_name != type_name or content.status != "published":
            from inc.kernel.errors import ErrorCategory, KernelError

            raise KernelError(
                code="content.not_found",
                category=ErrorCategory.NOT_FOUND,
                message="published content not found",
            )
        return content

    @router.get("/{type_name}/{content_id}/engagement", response_model=EngagementSummaryDTO)
    async def get_engagement(
        type_name: str = Path(..., min_length=1, max_length=64),
        content_id: uuid.UUID = Path(...),
    ) -> EngagementSummaryDTO:
        content = await services.content_queries.get(content_id)
        if content is None or content.type_name != type_name or content.status != "published":
            from inc.kernel.errors import ErrorCategory, KernelError

            raise KernelError(
                code="content.not_found",
                category=ErrorCategory.NOT_FOUND,
                message="published content not found",
            )
        if services.engagement_queries is None:
            return _summary_or_empty(content_id)
        return (await services.engagement_queries.get_summary(content_id)) or _summary_or_empty(
            content_id
        )

    @router.post("/{type_name}/{content_id}/views", response_model=EngagementSummaryDTO)
    async def record_view(
        type_name: str = Path(..., min_length=1, max_length=64),
        content_id: uuid.UUID = Path(...),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=200),
    ) -> EngagementSummaryDTO:
        if services.engagement_commands is None:
            raise RuntimeError("engagement capability is not available")
        await _require_published_type(services, type_name, content_id)
        return await services.engagement_commands.record_view(
            RecordContentViewInput(content_id=content_id, idempotency_key=idempotency_key)
        )

    @router.put("/{type_name}/{content_id}/like", response_model=EngagementSummaryDTO)
    async def like_content(
        type_name: str = Path(..., min_length=1, max_length=64),
        content_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> EngagementSummaryDTO:
        if services.engagement_commands is None:
            raise RuntimeError("engagement capability is not available")
        await _require_published_type(services, type_name, content_id)
        return await services.engagement_commands.like_content(
            LikeContentInput(content_id=content_id, subject_id=ctx.principal.subject_id)
        )

    @router.delete("/{type_name}/{content_id}/like", response_model=EngagementSummaryDTO)
    async def unlike_content(
        type_name: str = Path(..., min_length=1, max_length=64),
        content_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> EngagementSummaryDTO:
        if services.engagement_commands is None:
            raise RuntimeError("engagement capability is not available")
        await _require_published_type(services, type_name, content_id)
        return await services.engagement_commands.unlike_content(
            UnlikeContentInput(content_id=content_id, subject_id=ctx.principal.subject_id)
        )

    @router.put("/{type_name}/{content_id}/rating", response_model=EngagementSummaryDTO)
    async def rate_content(
        body: RatingBody,
        type_name: str = Path(..., min_length=1, max_length=64),
        content_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> EngagementSummaryDTO:
        if services.engagement_commands is None:
            raise RuntimeError("engagement capability is not available")
        await _require_published_type(services, type_name, content_id)
        return await services.engagement_commands.rate_content(
            RateContentInput(
                content_id=content_id, subject_id=ctx.principal.subject_id, rating=body.rating
            )
        )

    @router.delete("/{type_name}/{content_id}/rating", response_model=EngagementSummaryDTO)
    async def withdraw_rating(
        type_name: str = Path(..., min_length=1, max_length=64),
        content_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> EngagementSummaryDTO:
        if services.engagement_commands is None:
            raise RuntimeError("engagement capability is not available")
        await _require_published_type(services, type_name, content_id)
        return await services.engagement_commands.withdraw_rating(
            WithdrawRatingInput(content_id=content_id, subject_id=ctx.principal.subject_id)
        )

    return router

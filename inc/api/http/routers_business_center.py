"""Authenticated business quoting, consumption and archive delivery HTTP layer."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.archive import (
    ArchiveQueries,
    DownloadGrantDTO,
    DownloadGrantPageDTO,
    ResolveDownloadLinks,
    ResolveDownloadLinksDTO,
)
from inc.features.business_center import (
    BusinessCenterService,
    BusinessPrincipal,
    BusinessQuote,
    ConsumptionDTO,
    QuoteRequest,
)
from inc.kernel.errors import ErrorCategory, KernelError

REQUIRED_PERMISSIONS: tuple[str, ...] = (
    "business.quote",
    "business.consume",
    "archive.download",
)


class ConsumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote_token: str = Field(min_length=1)


def _service(services: Services) -> BusinessCenterService:
    value = services.business_center
    if value is None:
        raise RuntimeError("business-center router requires BusinessCenterService")
    return value


def _principal(services: Services, ctx: AppContext) -> BusinessPrincipal:
    client_id = ctx.principal.client_id
    if not client_id:
        raise KernelError(
            code="business_center.client_forbidden",
            category=ErrorCategory.FORBIDDEN,
            message="authenticated principal carries no client_id",
        )
    audience = str(
        getattr(services, "business_audience", None)
        or getattr(services.settings, "api_audience", "users")
    )
    return BusinessPrincipal(
        subject=ctx.principal.subject_id,
        client_id=client_id,
        audience=audience,
        scopes=frozenset(ctx.principal.capabilities),
    )


def _archive_queries(services: Services) -> ArchiveQueries:
    queries = services.archive_queries
    if queries is None:
        raise RuntimeError("business-center router requires ArchiveQueries")
    return queries


def _archive_links(services: Services) -> ResolveDownloadLinks:
    resolver = services.archive_link_resolver
    if resolver is None:
        raise RuntimeError("business-center router requires ResolveDownloadLinks")
    return resolver


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any,
) -> APIRouter:
    del require_capability
    router = APIRouter(prefix="/api/v1", tags=["business"])

    @router.post("/business/quotes", response_model=BusinessQuote)
    async def quote(
        body: QuoteRequest,
        ctx: AppContext = Depends(require_authenticated()),
    ) -> BusinessQuote:
        return await _service(services).quote(body, principal=_principal(services, ctx))

    @router.post("/business/consumptions", response_model=ConsumptionDTO)
    async def consume(
        body: ConsumeRequest,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> ConsumptionDTO:
        return await _service(services).consume(
            quote_token=body.quote_token,
            idempotency_key=idempotency_key,
            principal=_principal(services, ctx),
            trace_id=ctx.trace_id,
        )

    @router.get("/business/consumptions/{workflow_id}", response_model=ConsumptionDTO)
    async def get_consumption(
        workflow_id: str = Path(...),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> ConsumptionDTO:
        return await _service(services).get(workflow_id, principal=_principal(services, ctx))

    @router.get("/me/downloads", response_model=DownloadGrantPageDTO)
    async def list_downloads(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        status: str | None = Query(default=None),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> DownloadGrantPageDTO:
        return await _archive_queries(services).list_download_grants_for_subject(
            subject_type="identity",
            subject_id=ctx.principal.subject_id,
            page=page,
            size=size,
            status=status,
        )

    @router.post("/me/downloads/{grant_id}/links", response_model=ResolveDownloadLinksDTO)
    async def refresh_links(
        grant_id: str = Path(...),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> ResolveDownloadLinksDTO:
        # Ownership is checked again by the Activity immediately before provider IO.
        grant: DownloadGrantDTO | None = await _archive_queries(
            services
        ).get_download_grant_for_subject(
            grant_id,
            subject_type="identity",
            subject_id=ctx.principal.subject_id,
        )
        if grant is None:
            raise KernelError(
                code="archive.grant_not_found",
                category=ErrorCategory.NOT_FOUND,
                message="download grant was not found",
            )
        return await _archive_links(services)(
            grant.id,
            subject_type="identity",
            subject_id=ctx.principal.subject_id,
        )

    return router

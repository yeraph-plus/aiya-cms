"""Admin read-only kernel execution log router."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.kernel.db import Page
from inc.kernel.tasks import ExecutionEntryDTO, ExecutionKind

REQUIRED_PERMISSIONS: tuple[str, ...] = ("audit.read",)


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any = None,
) -> APIRouter:
    del require_authenticated
    router = APIRouter(prefix="/api/v1/admin", tags=["admin", "admin-execution"])

    @router.get("/execution/entries", response_model=Page[ExecutionEntryDTO])
    async def list_entries(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        kind: ExecutionKind | None = None,
        key: str | None = None,
        status: str | None = None,
        occurred_after: datetime | None = None,
        occurred_before: datetime | None = None,
        ctx: AppContext = Depends(require_capability("audit.read")),
    ) -> Page[ExecutionEntryDTO]:
        del ctx
        return await services.execution_queries.list_entries(
            page=page,
            size=size,
            kind=kind,
            key=key,
            status=status,
            occurred_after=occurred_after,
            occurred_before=occurred_before,
        )

    return router

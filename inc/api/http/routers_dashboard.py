"""Administrator dashboard aggregation endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability


class AdminDashboardDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window: Literal["24h", "7d", "30d"]
    as_of: datetime
    capabilities: dict[str, dict[str, Any]]


REQUIRED_PERMISSIONS: tuple[str, ...] = ("admin.dashboard.read",)


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin", tags=["admin", "admin-dashboard"])

    @router.get("/dashboard/summary", response_model=AdminDashboardDTO)
    # Kept as a routing alias for already-issued admin clients.  New clients
    # must use the canonical ``/dashboard/summary`` contract.
    @router.get("/dashboard", response_model=AdminDashboardDTO, include_in_schema=False)
    async def dashboard(
        window: Literal["24h", "7d", "30d"] = Query(default="7d"),
        ctx: AppContext = Depends(require_capability("admin.dashboard.read")),
    ) -> AdminDashboardDTO:
        as_of = ctx.clock.utc_now()
        registry = services.admin_summaries
        capabilities = (
            await registry.run_all(window=window, as_of=as_of) if registry is not None else {}
        )
        return AdminDashboardDTO(
            window=window,
            as_of=as_of,
            capabilities=capabilities,
        )

    return router

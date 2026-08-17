"""Administrator dashboard aggregation endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability


class AdminDashboardMetricDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    value: Any


class AdminDashboardSectionDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    metrics: list[AdminDashboardMetricDTO] = Field(default_factory=list)


class AdminDashboardDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window: Literal["24h", "7d", "30d"]
    as_of: datetime
    sections: list[AdminDashboardSectionDTO] = Field(default_factory=list)
    # Kept for older admin clients; new clients render the typed sections.
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
        sections = [
            AdminDashboardSectionDTO(key=key, metrics=_flatten_metrics(values))
            for key, values in sorted(capabilities.items())
        ]
        return AdminDashboardDTO(
            window=window,
            as_of=as_of,
            sections=sections,
            capabilities=capabilities,
        )

    return router


def _flatten_metrics(values: dict[str, Any], *, prefix: str = "") -> list[AdminDashboardMetricDTO]:
    metrics: list[AdminDashboardMetricDTO] = []
    for key, value in sorted(values.items()):
        metric_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            metrics.extend(_flatten_metrics(value, prefix=metric_key))
        else:
            metrics.append(AdminDashboardMetricDTO(key=metric_key, value=value))
    return metrics

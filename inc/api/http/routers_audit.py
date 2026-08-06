"""Audit admin router.

Contract source: context/spec/http-openapi.md, capabilities/audit.md.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.audit.schemas import AuditEntryDTO


class AuditPageDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AuditEntryDTO]
    total: int
    page: int
    size: int


def build_router(services: Services, require_capability: RequireCapability) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin")

    @router.get("/audit/entries", response_model=AuditPageDTO)
    async def list_entries(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        action: str | None = None,
        actor_type: str | None = None,
        actor_id: str | None = None,
        outcome: str | None = None,
        occurred_after: datetime | None = None,
        occurred_before: datetime | None = None,
        ctx: AppContext = Depends(require_capability("audit.read")),
    ) -> AuditPageDTO:
        result = await services.audit_queries.list_entries(
            page=page,
            size=size,
            action=action,
            actor_type=actor_type,
            actor_id=actor_id,
            outcome=outcome,
            occurred_after=occurred_after,
            occurred_before=occurred_before,
        )
        return AuditPageDTO(
            items=result.items, total=result.total, page=result.page, size=result.size
        )

    return router

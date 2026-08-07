"""Audit admin router.

Contract source: context/spec/http-openapi.md, capabilities/audit.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.audit.schemas import AuditEntryDTO
from inc.kernel.db import Page

REQUIRED_PERMISSIONS: tuple[str, ...] = ("audit.read",)


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin")

    @router.get("/audit/entries", response_model=Page[AuditEntryDTO])
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
    ) -> Page[AuditEntryDTO]:
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
        return result

    return router

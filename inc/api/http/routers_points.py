"""Points self-service read endpoint.

Contract source: context/spec/features.md §4.3, capabilities/points.md §6.

Read-only: an unopened account returns an empty ledger page; the read path
never opens accounts or writes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.points.schemas import LedgerEntryDTO
from inc.features.check_in.workflows import REWARD_BEHAVIOR
from inc.kernel.db import Page

REQUIRED_PERMISSIONS: tuple[str, ...] = ()


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["points"])

    @router.get("/me/points/ledger", response_model=Page[LedgerEntryDTO])
    async def ledger(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> Page[LedgerEntryDTO]:
        program_key = services.behaviors.require(REWARD_BEHAVIOR).program_key
        return await services.points_queries.list_ledger(
            program_key=program_key,
            subject_type="identity",
            subject_id=ctx.principal.subject_id,
            page=page,
            size=size,
        )

    return router

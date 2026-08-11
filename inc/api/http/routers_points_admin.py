"""Admin points adjustment endpoint.

Contract source: context/spec/http-openapi.md §2, capabilities/points.md §5/§9.

Positive amounts credit into the perpetual bucket; negative amounts consume
buckets FIFO by expiry and may push the account into debt. Adjustments are
admin-only, carry a reason, and are idempotent per ``idempotency_key``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.points import DEFAULT_PROGRAM_KEY
from inc.capabilities.points.commands import (
    AdjustPoints,
)
from inc.capabilities.points.commands import (
    CommandContext as PointsCommandContext,
)
from inc.capabilities.points.schemas import AdjustInput, AdminPointsViewDTO, LedgerEntryDTO
from inc.kernel.errors import KernelError

REQUIRED_PERMISSIONS: tuple[str, ...] = ("points.adjust", "points.read")


class PointsAdjustInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: str = "identity"
    subject_id: str
    program_key: str | None = Field(default=None, min_length=1, max_length=100)
    amount: int  # nonzero; negative is a debit-style adjustment
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _points_ctx(ctx: AppContext, services: Services) -> PointsCommandContext:
    return PointsCommandContext(
        uow_factory=ctx.uow_factory,
        clock=ctx.clock,
        outbox=services.outbox,
        behaviors=services.behaviors,
        permissions=frozenset(ctx.principal.capabilities),
        actor_id=ctx.principal.subject_id,
        trace_id=ctx.trace_id,
    )


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin", tags=["admin", "admin-points"])

    @router.post("/points/adjust", response_model=LedgerEntryDTO)
    async def adjust_points(
        body: PointsAdjustInput,
        ctx: AppContext = Depends(require_capability("points.adjust")),
    ) -> LedgerEntryDTO:
        return await AdjustPoints(_points_ctx(ctx, services))(
            AdjustInput(
                subject_type=body.subject_type,
                subject_id=body.subject_id,
                program_key=body.program_key,
                amount=body.amount,
                reason=body.reason,
                idempotency_key=body.idempotency_key,
                metadata=body.metadata,
            )
        )

    @router.get("/points/ledger", response_model=AdminPointsViewDTO)
    async def list_ledger(
        subject_id: str = Query(..., min_length=1, max_length=200),
        subject_type: str = Query(default="identity", min_length=1, max_length=32),
        program_key: str = Query(default=DEFAULT_PROGRAM_KEY, min_length=1, max_length=100),
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        ctx: AppContext = Depends(require_capability("points.read")),
    ) -> AdminPointsViewDTO:
        try:
            balance = await services.points_queries.get_balance(
                program_key=program_key,
                subject_type=subject_type,
                subject_id=subject_id,
            )
        except KernelError as exc:
            if exc.code != "points.account_not_opened":
                raise
            balance = None
        buckets = await services.points_queries.list_buckets(
            program_key=program_key,
            subject_type=subject_type,
            subject_id=subject_id,
        )
        ledger = await services.points_queries.list_ledger(
            program_key=program_key,
            subject_type=subject_type,
            subject_id=subject_id,
            page=page,
            size=size,
        )
        return AdminPointsViewDTO(balance=balance, buckets=buckets, ledger=ledger)

    return router

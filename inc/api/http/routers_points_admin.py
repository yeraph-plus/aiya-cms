"""Admin points adjustment endpoint.

Contract source: context/spec/http-openapi.md §2, capabilities/points.md §5/§9.

Positive amounts credit into the perpetual bucket; negative amounts consume
buckets FIFO by expiry and may push the account into debt. Adjustments are
admin-only, carry a reason, and are idempotent per ``idempotency_key``.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.api.http.projections import AdminSubjectRefDTO
from inc.capabilities.points import (
    DEFAULT_PROGRAM_KEY,
    PointsProgramInput,
    PointsProgramPatch,
    PointsProgramStatusInput,
)
from inc.capabilities.points.commands import (
    AdjustPoints,
    FreezePointsAccount,
)
from inc.capabilities.points.commands import (
    CommandContext as PointsCommandContext,
)
from inc.capabilities.points.schemas import (
    AdjustInput,
    AdminPointsViewDTO,
    BalanceDTO,
    LedgerEntryDTO,
)
from inc.kernel.db import Page
from inc.kernel.errors import ErrorCategory, KernelError

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


class PointsProgramDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    program_key: str
    display_name: str
    unit: str
    status: str
    allow_admin_reversal: bool
    version: int = 1


class PointsAccountAdminDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str
    program_key: str
    subject_type: str
    subject_id: str
    state: str
    balance: int
    version: int
    subject: AdminSubjectRefDTO | None = None


class PointsSummaryDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_count: int
    account_count: int
    active_account_count: int
    frozen_account_count: int
    debt_account_count: int
    total_balance: int


class PointsAccountFreezeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


def _program(row: Any) -> PointsProgramDTO:
    return PointsProgramDTO(
        id=str(row.id),
        program_key=row.program_key,
        display_name=row.display_name,
        unit=row.unit,
        status=row.status,
        allow_admin_reversal=row.allow_admin_reversal,
        version=row.version,
    )


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

    @router.get("/points/programs", response_model=list[PointsProgramDTO])
    async def list_programs(
        ctx: AppContext = Depends(require_capability("points.programs.read")),
    ) -> list[PointsProgramDTO]:
        del ctx
        if services.points_admin is None:
            raise KernelError(
                code="points.unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="points admin service is unavailable",
            )
        return [_program(row) for row in await services.points_admin.list_programs()]

    @router.post("/points/programs", response_model=PointsProgramDTO)
    async def create_program(
        body: PointsProgramInput,
        ctx: AppContext = Depends(require_capability("points.programs.manage")),
    ) -> PointsProgramDTO:
        if services.points_admin is None:
            raise KernelError(
                code="points.unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="points admin service is unavailable",
            )
        return _program(
            await services.points_admin.create_program(
                body, actor_id=ctx.principal.subject_id, trace_id=ctx.trace_id
            )
        )

    @router.patch("/points/programs/{program_key}", response_model=PointsProgramDTO)
    async def update_program(
        body: PointsProgramPatch,
        program_key: str = Path(..., min_length=1, max_length=100),
        ctx: AppContext = Depends(require_capability("points.programs.manage")),
    ) -> PointsProgramDTO:
        if services.points_admin is None:
            raise KernelError(
                code="points.unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="points admin service is unavailable",
            )
        return _program(
            await services.points_admin.update_program(
                program_key,
                body,
                actor_id=ctx.principal.subject_id,
                trace_id=ctx.trace_id,
            )
        )

    @router.post("/points/programs/{program_key}/activate", response_model=PointsProgramDTO)
    async def activate_program(
        body: PointsProgramStatusInput,
        program_key: str = Path(..., min_length=1, max_length=100),
        ctx: AppContext = Depends(require_capability("points.programs.manage")),
    ) -> PointsProgramDTO:
        return await _set_program_status(services, program_key, "active", body, ctx)

    @router.post("/points/programs/{program_key}/deactivate", response_model=PointsProgramDTO)
    async def deactivate_program(
        body: PointsProgramStatusInput,
        program_key: str = Path(..., min_length=1, max_length=100),
        ctx: AppContext = Depends(require_capability("points.programs.manage")),
    ) -> PointsProgramDTO:
        return await _set_program_status(services, program_key, "inactive", body, ctx)

    @router.get("/points/summary", response_model=PointsSummaryDTO)
    async def points_summary(
        ctx: AppContext = Depends(require_capability("points.programs.read")),
    ) -> PointsSummaryDTO:
        del ctx
        if services.points_admin is None:
            raise KernelError(
                code="points.unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="points admin service is unavailable",
            )
        return PointsSummaryDTO(**(await services.points_admin.summary()).model_dump())

    @router.get("/points/accounts", response_model=Page[PointsAccountAdminDTO])
    async def list_accounts(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        program_key: str | None = Query(default=None, min_length=1, max_length=100),
        state: str | None = Query(default=None, min_length=1, max_length=16),
        ctx: AppContext = Depends(require_capability("points.programs.read")),
    ) -> Page[PointsAccountAdminDTO]:
        del ctx
        if services.points_admin is None:
            raise KernelError(
                code="points.unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="points admin service is unavailable",
            )
        result = await services.points_admin.list_accounts(
            page=page, size=size, program_key=program_key, state=state
        )
        subjects = await services.identity_queries.get_subjects(
            item.subject_id for item in result.items if item.subject_type == "identity"
        )
        return Page(
            items=[
                PointsAccountAdminDTO(
                    **item.model_dump(),
                    subject=(
                        AdminSubjectRefDTO(
                            subject_type=item.subject_type,
                            subject_id=item.subject_id,
                            username=subjects[item.subject_id].username,
                            display_name=subjects[item.subject_id].display_name,
                            avatar_asset_id=subjects[item.subject_id].avatar_asset_id,
                        )
                        if item.subject_type == "identity" and item.subject_id in subjects
                        else None
                    ),
                )
                for item in result.items
            ],
            total=result.total,
            page=result.page,
            size=result.size,
        )

    @router.get("/points/programs/{program_key}/summary")
    async def program_summary(
        program_key: str = Path(..., min_length=1, max_length=100),
        ctx: AppContext = Depends(require_capability("points.programs.read")),
    ) -> dict[str, Any]:
        if services.points_admin is None:
            raise KernelError(
                code="points.unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="points admin service is unavailable",
            )
        program, count = await services.points_admin.program_summary(program_key)
        return {"program": _program(program), "account_count": count}

    @router.post("/points/accounts/{account_id}/freeze", response_model=BalanceDTO)
    async def freeze_account_by_id(
        body: PointsAccountFreezeInput,
        account_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("points.freeze")),
    ) -> BalanceDTO:
        if services.points_admin is None:
            raise KernelError(
                code="points.unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="points admin service is unavailable",
            )
        program_key, subject_type, subject_id = await services.points_admin.account_target(
            account_id
        )
        return await FreezePointsAccount(_points_ctx(ctx, services))(
            program_key=program_key,
            subject_type=subject_type,
            subject_id=subject_id,
            frozen=True,
            reason=body.reason,
        )

    @router.post("/points/accounts/{account_id}/unfreeze", response_model=BalanceDTO)
    async def unfreeze_account_by_id(
        body: PointsAccountFreezeInput,
        account_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("points.freeze")),
    ) -> BalanceDTO:
        if services.points_admin is None:
            raise KernelError(
                code="points.unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="points admin service is unavailable",
            )
        program_key, subject_type, subject_id = await services.points_admin.account_target(
            account_id
        )
        return await FreezePointsAccount(_points_ctx(ctx, services))(
            program_key=program_key,
            subject_type=subject_type,
            subject_id=subject_id,
            frozen=False,
            reason=body.reason,
        )

    @router.post("/points/accounts/{subject_type}/{subject_id}/freeze", response_model=BalanceDTO)
    async def freeze_account(
        program_key: str = Query(default=DEFAULT_PROGRAM_KEY, min_length=1, max_length=100),
        subject_type: str = Path(..., min_length=1, max_length=32),
        subject_id: str = Path(..., min_length=1, max_length=200),
        ctx: AppContext = Depends(require_capability("points.freeze")),
    ) -> BalanceDTO:
        return await FreezePointsAccount(_points_ctx(ctx, services))(
            program_key=program_key,
            subject_type=subject_type,
            subject_id=subject_id,
            frozen=True,
            reason="admin freeze",
        )

    @router.post("/points/accounts/{subject_type}/{subject_id}/unfreeze", response_model=BalanceDTO)
    async def unfreeze_account(
        program_key: str = Query(default=DEFAULT_PROGRAM_KEY, min_length=1, max_length=100),
        subject_type: str = Path(..., min_length=1, max_length=32),
        subject_id: str = Path(..., min_length=1, max_length=200),
        ctx: AppContext = Depends(require_capability("points.freeze")),
    ) -> BalanceDTO:
        return await FreezePointsAccount(_points_ctx(ctx, services))(
            program_key=program_key,
            subject_type=subject_type,
            subject_id=subject_id,
            frozen=False,
            reason="admin unfreeze",
        )

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


async def _set_program_status(
    services: Services,
    program_key: str,
    status: Literal["active", "inactive"],
    body: PointsProgramStatusInput,
    ctx: AppContext,
) -> PointsProgramDTO:
    if services.points_admin is None:
        raise KernelError(
            code="points.unavailable",
            category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
            message="points admin service is unavailable",
        )
    return _program(
        await services.points_admin.set_program_status(
            program_key,
            status,
            expected_version=body.expected_version,
            reason=body.reason,
            actor_id=ctx.principal.subject_id,
            trace_id=ctx.trace_id,
            protected_program_key=DEFAULT_PROGRAM_KEY,
        )
    )

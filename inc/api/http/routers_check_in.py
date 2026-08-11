"""Check-in endpoint.

Contract source: context/spec/features.md §4.3, http-openapi.md §6.

Check-in is an explicit user action (never a read-path side effect). The
business idempotency key is subject + program + business date fixed at
request time, so repeats return the original reward result.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.points.commands import (
    CommandContext as PointsCommandContext,
)
from inc.features.check_in.schemas import CheckInResultDTO
from inc.features.check_in.workflows import (
    CHECK_IN_WORKFLOW_KEY,
    REWARD_BEHAVIOR,
    business_date_for,
    check_in_idempotency_key,
)
from inc.kernel.errors import ErrorCategory, KernelError

REQUIRED_PERMISSIONS: tuple[str, ...] = ()


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
    require_authenticated: Any,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["check-in"])

    @router.post("/check-in", response_model=CheckInResultDTO)
    async def check_in(
        ctx: AppContext = Depends(require_authenticated()),
    ) -> CheckInResultDTO:
        behavior = services.behaviors.require(REWARD_BEHAVIOR)
        subject_id = ctx.principal.subject_id
        business_date = business_date_for(ctx.clock, behavior.business_timezone)
        instance = await services.runner.start(
            workflow_key=CHECK_IN_WORKFLOW_KEY,
            idempotency_key=check_in_idempotency_key(
                subject_id=subject_id,
                program_key=behavior.program_key,
                business_date=business_date,
            ),
            input_data={
                "subject_type": "identity",
                "subject_id": subject_id,
                "source_id": "http:check-in",
                "program_key": behavior.program_key,
                "business_date": business_date,
            },
            trace_id=ctx.trace_id,
        )
        status = "already_rewarded"
        if instance.status != "completed":
            final_status = await services.runner.advance(instance.id)
            if final_status != "completed":
                raise KernelError(
                    code="checkin.workflow_failed",
                    category=ErrorCategory.INTERNAL,
                    message=f"check-in workflow ended in {final_status}",
                )
            status = "rewarded"
        balance = await services.points_queries.get_balance(
            program_key=behavior.program_key,
            subject_type="identity",
            subject_id=subject_id,
        )
        return CheckInResultDTO(status=status, business_date=business_date, balance=balance.balance)

    return router

"""Points self-service read endpoint.

Contract source: context/spec/features.md §4.3, capabilities/points.md §6.

Read-only: an unopened account returns an explicit empty view; the read
path never opens accounts or writes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.features.check_in.schemas import BalanceViewDTO
from inc.features.check_in.workflows import REWARD_BEHAVIOR
from inc.kernel.errors import KernelError

REQUIRED_PERMISSIONS: tuple[str, ...] = ()


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["points"])

    @router.get("/points/balance", response_model=BalanceViewDTO)
    async def balance(
        ctx: AppContext = Depends(require_authenticated()),
    ) -> BalanceViewDTO:
        program_key = services.behaviors.require(REWARD_BEHAVIOR).program_key
        try:
            result = await services.points_queries.get_balance(
                program_key=program_key,
                subject_type="identity",
                subject_id=ctx.principal.subject_id,
            )
        except KernelError as exc:
            if exc.code == "points.account_not_opened":
                return BalanceViewDTO(opened=False, program_key=program_key, balance=0)
            raise
        return BalanceViewDTO(opened=True, program_key=result.program_key, balance=result.balance)

    return router

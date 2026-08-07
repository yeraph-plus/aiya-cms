"""Settings admin router.

Contract source: context/spec/http-openapi.md, capabilities/settings.md.

Group updates require the group's registered update permission (for the
seo group that is settings.seo.update), enforced by the capability.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.settings import (
    CommandContext,
    ResetSettingGroup,
    UpdateSettingGroup,
)
from inc.capabilities.settings.schemas import SettingGroupDTO, UpdateSettingGroupInput


def _ctx(ctx: AppContext, services: Services) -> CommandContext:
    return CommandContext(
        uow_factory=ctx.uow_factory,
        clock=ctx.clock,
        outbox=services.outbox,
        groups=services.settings_groups,
        permissions=frozenset(ctx.principal.capabilities),
        actor_id=ctx.principal.subject_id,
        trace_id=ctx.trace_id,
    )


REQUIRED_PERMISSIONS: tuple[str, ...] = (
    "settings.read",
    "settings.update",
)


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin")

    @router.get("/settings/groups", response_model=list[SettingGroupDTO])
    async def list_groups(
        ctx: AppContext = Depends(require_capability("settings.read")),
    ) -> list[SettingGroupDTO]:
        return await services.settings_queries.list_groups()

    @router.get("/settings/groups/{group_key}", response_model=SettingGroupDTO)
    async def get_group(
        group_key: str = Path(...),
        ctx: AppContext = Depends(require_capability("settings.read")),
    ) -> SettingGroupDTO:
        return await services.settings_queries.get_group(group_key)

    @router.put("/settings/groups/{group_key}", response_model=SettingGroupDTO)
    async def update_group(
        body: UpdateSettingGroupInput,
        group_key: str = Path(...),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> SettingGroupDTO:
        # the group's registered update permission (settings.<group>.update)
        # is enforced by the capability command itself
        return await UpdateSettingGroup(_ctx(ctx, services))(group_key, body)

    @router.post("/settings/groups/{group_key}/reset", response_model=SettingGroupDTO)
    async def reset_group(
        group_key: str = Path(...),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> SettingGroupDTO:
        return await ResetSettingGroup(_ctx(ctx, services))(group_key)

    return router

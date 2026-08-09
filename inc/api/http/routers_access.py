"""Access admin router.

Contract source: context/spec/http-openapi.md, capabilities/access.md.

Roles, grants and permission keys. Commands run with the principal's
capability set; role management itself needs the manage grants.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, ConfigDict

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.access.commands import (
    AssignRoleToSubject,
    CommandContext,
    CreateRole,
    RevokeRoleFromSubject,
)
from inc.capabilities.access.schemas import GrantSummary, RoleDTO


class CreateRoleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    slug: str
    description: str | None = None


class AssignRoleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: str = "identity"
    subject_id: str


class CapabilityDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keys: list[str]


def _ctx(ctx: AppContext, services: Services) -> CommandContext:
    return CommandContext(
        uow_factory=ctx.uow_factory,
        clock=ctx.clock,
        outbox=services.outbox,
        permissions=services.permission_registry,
        subject_exists=_subject_exists(ctx, services),
        audit_actor_id=ctx.principal.subject_id,
        audit_trace_id=ctx.trace_id,
    )


def _subject_exists(ctx: AppContext, services: Any) -> Any:
    class _Exists:
        async def exists(self, subject_type: str, subject_id: str) -> bool:
            if subject_type == "identity":
                return await services.identity_queries.get_subject(subject_id) is not None
            return False

    return _Exists()


REQUIRED_PERMISSIONS: tuple[str, ...] = (
    "access.roles.read",
    "access.roles.manage",
    "access.roles.assign",
    "access.bootstrap",
)


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin", tags=["admin", "admin-access"])

    @router.get("/capabilities", response_model=CapabilityDTO)
    async def list_capabilities(
        ctx: AppContext = Depends(require_capability("access.roles.read")),
    ) -> CapabilityDTO:
        return CapabilityDTO(keys=list(services.permission_registry.keys()))

    @router.get("/roles", response_model=list[RoleDTO])
    async def list_roles(
        ctx: AppContext = Depends(require_capability("access.roles.read")),
    ) -> list[RoleDTO]:
        return await services.access_queries.list_roles()

    @router.post("/roles", response_model=RoleDTO)
    async def create_role(
        body: CreateRoleBody,
        ctx: AppContext = Depends(require_capability("access.roles.manage")),
    ) -> RoleDTO:
        return await CreateRole(_ctx(ctx, services))(
            name=body.name, slug=body.slug, description=body.description
        )

    @router.post("/roles/{role_id}/assign", response_model=GrantSummary)
    async def assign_role(
        body: AssignRoleBody,
        role_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("access.roles.assign")),
    ) -> GrantSummary:
        await AssignRoleToSubject(_ctx(ctx, services))(
            subject_type=body.subject_type,
            subject_id=body.subject_id,
            role_id=str(role_id),
        )
        return await services.access_queries.grants_for(
            subject_type=body.subject_type, subject_id=body.subject_id
        )

    @router.post("/roles/{role_id}/revoke", status_code=204)
    async def revoke_role(
        body: AssignRoleBody,
        role_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("access.roles.assign")),
    ) -> None:
        await RevokeRoleFromSubject(_ctx(ctx, services))(
            subject_type=body.subject_type,
            subject_id=body.subject_id,
            role_id=str(role_id),
        )

    return router

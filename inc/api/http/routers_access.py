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
    DeleteRole,
    ReplaceRoleCapabilities,
    RevokeRoleFromSubject,
    UpdateRole,
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


class UpdateRoleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None


class CapabilityDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keys: list[str]


class ReplaceCapabilitiesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_keys: list[str]


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

    @router.get(
        "/subjects/{subject_type}/{subject_id}/roles",
        response_model=GrantSummary,
        include_in_schema=False,
    )
    @router.get("/access/subjects/{subject_type}/{subject_id}/roles", response_model=GrantSummary)
    async def subject_roles(
        subject_type: str = Path(..., min_length=1, max_length=64),
        subject_id: str = Path(..., min_length=1, max_length=200),
        ctx: AppContext = Depends(require_capability("access.roles.read")),
    ) -> GrantSummary:
        del ctx
        return await services.access_queries.grants_for(
            subject_type=subject_type, subject_id=subject_id
        )

    @router.patch("/roles/{role_id}", response_model=RoleDTO)
    async def update_role(
        body: UpdateRoleBody,
        role_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("access.roles.manage")),
    ) -> RoleDTO:
        return await UpdateRole(_ctx(ctx, services))(
            role_id=str(role_id), name=body.name, description=body.description
        )

    @router.put("/roles/{role_id}/capabilities", response_model=RoleDTO)
    async def replace_capabilities(
        body: ReplaceCapabilitiesBody,
        role_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("access.roles.manage")),
    ) -> RoleDTO:
        return await ReplaceRoleCapabilities(_ctx(ctx, services))(
            role_id=str(role_id), capability_keys=body.capability_keys
        )

    @router.delete("/roles/{role_id}", status_code=204)
    async def delete_role(
        role_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("access.roles.manage")),
    ) -> None:
        await DeleteRole(_ctx(ctx, services))(role_id=str(role_id))

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

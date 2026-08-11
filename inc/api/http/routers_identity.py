"""Identity admin router.

Contract source: context/spec/http-openapi.md, capabilities/identity.md.

Reads use IdentityQueries; writes use identity commands with the
principal's capability set. Subjects are the capability's opaque ids.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.identity.commands import (
    BanUser,
    CommandContext,
    DeleteUser,
    UnbanUser,
    UpdateProfile,
)
from inc.capabilities.identity.schemas import SubjectDTO, UpdateProfileInput
from inc.kernel.db import Page


class BanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


def _ctx(ctx: AppContext, services: Services) -> CommandContext:
    return CommandContext(
        uow_factory=ctx.uow_factory,
        clock=ctx.clock,
        outbox=services.outbox,
        hasher=services.hasher,
        audit_actor_id=ctx.principal.subject_id,
        audit_trace_id=ctx.trace_id,
    )


REQUIRED_PERMISSIONS: tuple[str, ...] = (
    "identity.users.read",
    "identity.users.ban",
    "identity.users.unban",
    "identity.users.delete",
    "identity.users.update",
)


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin", tags=["admin", "admin-users"])

    @router.get("/users", response_model=Page[SubjectDTO])
    async def list_users(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        status: str | None = None,
        ctx: AppContext = Depends(require_capability("identity.users.read")),
    ) -> Page[SubjectDTO]:
        return await services.identity_queries.list_users(page=page, size=size, status=status)

    @router.get("/users/{user_id}", response_model=SubjectDTO)
    async def get_user(
        user_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("identity.users.read")),
    ) -> SubjectDTO:
        subject = await services.identity_queries.get_subject(str(user_id))
        if subject is None:
            from inc.kernel.errors import ErrorCategory, KernelError

            raise KernelError(
                code="identity.not_found",
                category=ErrorCategory.NOT_FOUND,
                message=f"user {user_id}",
            )
        return subject

    @router.patch("/users/{user_id}", response_model=SubjectDTO)
    async def update_user_profile(
        body: UpdateProfileInput,
        user_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("identity.users.update")),
    ) -> SubjectDTO:
        return await UpdateProfile(_ctx(ctx, services))(user_id=str(user_id), changes=body)

    @router.post("/users/{user_id}/ban", response_model=SubjectDTO)
    async def ban_user(
        body: BanInput,
        user_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("identity.users.ban")),
    ) -> SubjectDTO:
        return await BanUser(_ctx(ctx, services))(user_id=str(user_id), reason=body.reason)

    @router.post("/users/{user_id}/unban", response_model=SubjectDTO)
    async def unban_user(
        user_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("identity.users.unban")),
    ) -> SubjectDTO:
        return await UnbanUser(_ctx(ctx, services))(user_id=str(user_id))

    @router.delete("/users/{user_id}", status_code=204)
    async def delete_user(
        user_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("identity.users.delete")),
    ) -> None:
        await DeleteUser(_ctx(ctx, services))(user_id=str(user_id))

    return router

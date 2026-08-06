"""Auth endpoints.

Contract source: context/spec/http-openapi.md §2/§5.

``/api/v1/auth/me`` returns the current principal's minimal profile and
capability keys; the capability set comes from access grants.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability


class MeDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str
    username: str | None = None
    display_name: str | None = None
    status: str
    capabilities: list[str] = []


def build_router(services: Services, require_capability: RequireCapability) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/auth/me", response_model=MeDTO)
    async def me(
        ctx: AppContext = Depends(require_capability("identity.users.read")),
    ) -> MeDTO:
        subject = await services.identity_queries.get_subject(ctx.principal.subject_id)
        if subject is None:
            from inc.kernel.errors import ErrorCategory, KernelError

            raise KernelError(
                code="identity.not_found",
                category=ErrorCategory.NOT_FOUND,
                message="subject disappeared",
            )
        return MeDTO(
            subject_id=subject.id,
            username=subject.username,
            display_name=subject.display_name,
            status=subject.status,
            capabilities=sorted(ctx.principal.capabilities),
        )

    return router

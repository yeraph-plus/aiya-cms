"""Feature-owned authenticated self-service profile routes."""

from __future__ import annotations

import uuid
from typing import Any, cast

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, ConfigDict, Field

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.assets.schemas import CreateUploadIntentResult
from inc.capabilities.identity.schemas import UpdateProfileInput
from inc.features.check_in.api import MeService
from inc.features.check_in.schemas import MeDTO
from inc.kernel.errors import ErrorCategory, KernelError


class AvatarUploadIntentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mime_types: tuple[str, ...] = ("image/png",)
    content_length_max: int = Field(default=10 * 1024 * 1024, gt=0, le=20 * 1024 * 1024)


REQUIRED_PERMISSIONS: tuple[str, ...] = ()


def _me_service(services: Services) -> MeService:
    if services.me is None:
        raise KernelError(
            code="profile.unavailable",
            category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
            message="self-service feature is not available",
        )
    return cast(MeService, services.me)


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any,
) -> APIRouter:
    del require_capability
    router = APIRouter(prefix="/api/v1", tags=["auth"])

    @router.get("/me", response_model=MeDTO)
    async def me(ctx: AppContext = Depends(require_authenticated())) -> MeDTO:
        return await _me_service(services).get(
            subject_id=ctx.principal.subject_id,
            capabilities=frozenset(ctx.principal.capabilities),
        )

    @router.patch("/me", response_model=MeDTO)
    async def update_me(
        body: UpdateProfileInput,
        ctx: AppContext = Depends(require_authenticated()),
    ) -> MeDTO:
        return await _me_service(services).update(
            subject_id=ctx.principal.subject_id,
            changes=body,
            capabilities=frozenset(ctx.principal.capabilities),
            trace_id=ctx.trace_id,
        )

    @router.post("/me/avatar/upload-intents", response_model=CreateUploadIntentResult)
    async def create_avatar_upload_intent(
        body: AvatarUploadIntentInput,
        ctx: AppContext = Depends(require_authenticated()),
    ) -> CreateUploadIntentResult:
        return await _me_service(services).create_avatar_upload_intent(
            subject_id=ctx.principal.subject_id,
            trace_id=ctx.trace_id,
            mime_types=body.mime_types,
            content_length_max=body.content_length_max,
        )

    @router.post("/me/avatar/upload-intents/{intent_id}/finalize", response_model=MeDTO)
    async def finalize_avatar_upload(
        intent_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> MeDTO:
        return await _me_service(services).finalize_avatar_upload(
            subject_id=ctx.principal.subject_id,
            trace_id=ctx.trace_id,
            intent_id=intent_id,
            capabilities=frozenset(ctx.principal.capabilities),
        )

    return router

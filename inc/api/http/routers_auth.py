"""Auth endpoints.

Contract source: context/spec/http-openapi.md §2/§5.

``/api/v1/me`` returns the current principal's minimal profile, capability
keys and the points balance summary when the points feature is installed.

The password-reset endpoints are public (no Bearer): the request endpoint
always returns the same 202 body so account enumeration is impossible, and
the one-time challenge token travels out-of-band only — it never appears
in any response body (identity.md §4/§6).
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.assets.schemas import CreateUploadIntentResult
from inc.capabilities.identity.commands import (
    CommandContext,
    RegisterLocalUser,
    RequestPasswordReset,
    ResetPassword,
    VerifyEmail,
)
from inc.capabilities.identity.schemas import SubjectDTO, UpdateProfileInput
from inc.capabilities.oidc_provider.schemas import GrantConsentDTO
from inc.features.check_in.api import MeService
from inc.features.check_in.schemas import MeDTO
from inc.kernel.errors import ErrorCategory, KernelError


class RegisterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    email: str = Field(min_length=3, max_length=320)
    # mirrors identity.policies.PasswordPolicy defaults; the command
    # re-validates against the versioned policy.
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)


class VerifyEmailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=512)


class PasswordResetRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(min_length=1, max_length=320)


class PasswordResetConfirmInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=512)
    # mirrors identity.policies.PasswordPolicy defaults; the command
    # re-validates against the versioned policy.
    new_password: str = Field(min_length=8, max_length=128)


class AcceptedDTO(BaseModel):
    """Equivalent response for every password-reset request."""

    model_config = ConfigDict(extra="forbid")

    accepted: bool = True


class AvatarUploadIntentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mime_types: tuple[str, ...] = ("image/png",)
    content_length_max: int = Field(default=10 * 1024 * 1024, gt=0, le=20 * 1024 * 1024)


REQUIRED_PERMISSIONS: tuple[str, ...] = ()


def _public_ctx(services: Services, request: Request) -> CommandContext:
    return CommandContext(
        uow_factory=services.uow_factory,
        clock=services.clock,
        outbox=services.outbox,
        hasher=services.hasher,
        audit_trace_id=getattr(request.state, "request_id", None),
    )


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
    router = APIRouter(prefix="/api/v1", tags=["auth"])

    @router.get("/me", response_model=MeDTO)
    async def me(
        ctx: AppContext = Depends(require_authenticated()),
    ) -> MeDTO:
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

    grants = services.oidc_grants
    if grants is not None:

        @router.get("/auth/grants", response_model=list[GrantConsentDTO])
        async def list_grants(
            ctx: AppContext = Depends(require_authenticated()),
        ) -> list[GrantConsentDTO]:
            return await grants.list_for_subject(ctx.principal.subject_id)

        @router.delete("/auth/grants/{client_id}", status_code=204)
        async def revoke_grant(
            client_id: str = Path(..., min_length=1, max_length=200),
            ctx: AppContext = Depends(require_authenticated()),
        ) -> None:
            await grants.revoke(
                subject_id=ctx.principal.subject_id,
                client_id=client_id,
            )

    @router.post("/auth/register", response_model=SubjectDTO)
    async def register(body: RegisterInput, request: Request) -> SubjectDTO:
        result = await RegisterLocalUser(_public_ctx(services, request))(
            username=body.username,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            # the challenge token stays with the in-process caller;
            # out-of-band delivery is wired once notification is assembled
            issue_email_challenge=True,
        )
        return result.subject

    @router.post("/auth/verify-email", response_model=SubjectDTO)
    async def verify_email(body: VerifyEmailInput, request: Request) -> SubjectDTO:
        return await VerifyEmail(_public_ctx(services, request))(token=body.token)

    @router.post("/auth/password-reset/request", status_code=202, response_model=AcceptedDTO)
    async def request_password_reset(
        body: PasswordResetRequestInput, request: Request
    ) -> AcceptedDTO:
        await RequestPasswordReset(_public_ctx(services, request))(identifier=body.identifier)
        return AcceptedDTO()

    @router.post("/auth/password-reset/confirm", response_model=SubjectDTO)
    async def confirm_password_reset(
        body: PasswordResetConfirmInput, request: Request
    ) -> SubjectDTO:
        return await ResetPassword(_public_ctx(services, request))(
            token=body.token, new_password=body.new_password
        )

    return router

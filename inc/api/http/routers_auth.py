"""Auth endpoints.

Contract source: context/spec/http-openapi.md §2/§5.

``/api/v1/auth/me`` returns the current principal's minimal profile and
capability keys; the capability set comes from access grants.

The password-reset endpoints are public (no Bearer): the request endpoint
always returns the same 202 body so account enumeration is impossible, and
the one-time challenge token travels out-of-band only — it never appears
in any response body (identity.md §4/§6).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.identity.commands import (
    CommandContext,
    RegisterLocalUser,
    RequestPasswordReset,
    ResetPassword,
    VerifyEmail,
)
from inc.capabilities.identity.schemas import SubjectDTO


class MeDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str
    username: str | None = None
    display_name: str | None = None
    status: str
    capabilities: list[str] = []


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


REQUIRED_PERMISSIONS: tuple[str, ...] = ()


def _public_ctx(services: Services, request: Request) -> CommandContext:
    return CommandContext(
        uow_factory=services.uow_factory,
        clock=services.clock,
        outbox=services.outbox,
        hasher=services.hasher,
        audit_trace_id=getattr(request.state, "request_id", None),
    )


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["auth"])

    @router.get("/auth/me", response_model=MeDTO)
    async def me(
        ctx: AppContext = Depends(require_authenticated()),
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

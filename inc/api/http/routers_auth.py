"""Auth endpoints.

Contract source: context/spec/http-openapi.md §2/§5.

This router owns only shared identity lifecycle and grant-consent endpoints.
Feature-owned ``/api/v1/me`` routes live in ``routers_user_center``; the administrator
bootstrap projection is isolated at ``/api/v1/admin/session``.

The password-reset endpoints are public (no Bearer): the request endpoint
always returns the same 202 body so account enumeration is impossible, and
the one-time challenge token travels out-of-band only — it never appears
in any response body (identity.md §4/§6).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.api.http.rate_limit import FixedWindowRateLimiter
from inc.capabilities.identity.schemas import SubjectDTO
from inc.capabilities.oidc_provider.schemas import GrantConsentDTO
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.security import resolve_client_ip

PASSWORD_RESET_REQUEST_LIMIT = 5
PASSWORD_RESET_REQUEST_WINDOW_SECONDS = 60 * 60


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


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["auth"])
    password_reset_limiter = FixedWindowRateLimiter(
        limit=PASSWORD_RESET_REQUEST_LIMIT,
        window_seconds=PASSWORD_RESET_REQUEST_WINDOW_SECONDS,
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
        if services.auth is None:
            raise KernelError(
                code="auth.registration_unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="authentication feature is not enabled",
            )
        return await services.auth.register(
            username=body.username,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            trace_id=getattr(request.state, "request_id", None),
        )

    @router.post("/auth/verify-email", response_model=SubjectDTO)
    async def verify_email(body: VerifyEmailInput, request: Request) -> SubjectDTO:
        if services.auth is None:
            raise KernelError(
                code="auth.verification_unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="authentication feature is not enabled",
            )
        return await services.auth.verify_email(
            token=body.token, trace_id=getattr(request.state, "request_id", None)
        )

    @router.post("/auth/password-reset/request", status_code=202, response_model=AcceptedDTO)
    async def request_password_reset(
        body: PasswordResetRequestInput, request: Request
    ) -> AcceptedDTO:
        client = request.client
        source = resolve_client_ip(
            peer=client.host if client is not None else None,
            forwarded_for=request.headers.get("x-forwarded-for"),
            trusted_proxy_cidrs=getattr(services.settings, "trusted_proxy_cidrs", ()),
        )
        if not password_reset_limiter.allow(source, services.clock.utc_now()):
            raise KernelError(
                code="auth.password_reset_rate_limited",
                category=ErrorCategory.RATE_LIMITED,
                message="password reset request rate limit exceeded",
            )
        if services.auth is None:
            raise KernelError(
                code="auth.reset_unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="authentication feature is not enabled",
            )
        await services.auth.request_password_reset(
            identifier=body.identifier,
            trace_id=getattr(request.state, "request_id", None),
        )
        return AcceptedDTO()

    @router.post("/auth/password-reset/confirm", response_model=SubjectDTO)
    async def confirm_password_reset(
        body: PasswordResetConfirmInput, request: Request
    ) -> SubjectDTO:
        if services.auth is None:
            raise KernelError(
                code="auth.reset_unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="authentication feature is not enabled",
            )
        return await services.auth.reset_password(
            token=body.token,
            new_password=body.new_password,
            trace_id=getattr(request.state, "request_id", None),
        )

    return router

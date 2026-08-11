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
from typing import Any

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.assets.commands import (
    FINALIZE_WORKFLOW_KEY,
    CreateUploadIntent,
    FinalizeAsset,
)
from inc.capabilities.assets.commands import (
    CommandContext as AssetCommandContext,
)
from inc.capabilities.assets.schemas import CreateUploadIntentInput, CreateUploadIntentResult
from inc.capabilities.identity.commands import (
    CommandContext,
    RegisterLocalUser,
    RequestPasswordReset,
    ResetPassword,
    UpdateProfile,
    VerifyEmail,
)
from inc.capabilities.identity.schemas import SubjectDTO, UpdateProfileInput
from inc.capabilities.oidc_provider.schemas import GrantConsentDTO
from inc.capabilities.points import DEFAULT_PROGRAM_KEY
from inc.features.check_in.schemas import BalanceViewDTO
from inc.features.check_in.workflows import REWARD_BEHAVIOR
from inc.kernel.errors import KernelError


class MeDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str
    username: str | None = None
    display_name: str | None = None
    avatar_asset_id: str | None = None
    avatar_url: str | None = None
    status: str
    capabilities: list[str] = []
    points: BalanceViewDTO | None = None


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


def _identity_ctx(services: Services, ctx: AppContext) -> CommandContext:
    return CommandContext(
        uow_factory=services.uow_factory,
        clock=services.clock,
        outbox=services.outbox,
        hasher=services.hasher,
        audit_actor_id=ctx.principal.subject_id,
        audit_trace_id=ctx.trace_id,
    )


def _asset_ctx(services: Services, ctx: AppContext) -> AssetCommandContext:
    if services.asset_queries is None or not services.asset_providers:
        from inc.kernel.errors import ErrorCategory

        raise KernelError(
            code="assets.unavailable",
            category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
            message="assets capability is not available",
        )
    return AssetCommandContext(
        uow_factory=services.uow_factory,
        clock=services.clock,
        outbox=services.outbox,
        providers=services.asset_providers,
        runner=services.runner,
        permissions=frozenset({"assets.upload", "assets.read"}),
        actor_id=ctx.principal.subject_id,
        trace_id=ctx.trace_id,
    )


async def _me_dto(services: Services, ctx: AppContext, subject: SubjectDTO) -> MeDTO:
    avatar_url: str | None = None
    if subject.avatar_asset_id is not None and services.asset_queries is not None:
        from inc.kernel.errors import ErrorCategory

        try:
            permissions = frozenset(ctx.principal.capabilities)
            asset_id = uuid.UUID(subject.avatar_asset_id)
            if "assets.read" not in permissions:
                asset = await services.asset_queries.get(
                    asset_id, permissions=frozenset({"assets.read"})
                )
                avatar_bucket = await services.settings_queries.get_value(
                    "object_storage", "s3_avatar_bucket"
                )
                if asset is None or asset.bucket != avatar_bucket:
                    raise KernelError(
                        code="assets.forbidden",
                        category=ErrorCategory.FORBIDDEN,
                        message="avatar is not in the subject avatar bucket",
                    )
                permissions = frozenset({"assets.read"})
            avatar_url = (
                await services.asset_queries.resolve_url(asset_id, permissions=permissions)
            ).url
        except KernelError:
            # A deleted, pending or unavailable asset is represented as no URL;
            # the stable opaque ID remains useful for profile management.
            avatar_url = None
    points: BalanceViewDTO | None = None
    try:
        program_key = services.behaviors.require(REWARD_BEHAVIOR).program_key
    except KernelError as exc:
        if exc.code != "points.unknown_behavior":
            raise
    else:
        try:
            balance = await services.points_queries.get_balance(
                program_key=program_key,
                subject_type="identity",
                subject_id=subject.id,
            )
        except KernelError as exc:
            if exc.code not in {"points.account_not_opened", "points.program_inactive"}:
                raise
            points = BalanceViewDTO(
                opened=False, program_key=program_key or DEFAULT_PROGRAM_KEY, balance=0
            )
        else:
            points = BalanceViewDTO(
                opened=True,
                program_key=balance.program_key,
                balance=balance.balance,
            )
    return MeDTO(
        subject_id=subject.id,
        username=subject.username,
        display_name=subject.display_name,
        avatar_asset_id=subject.avatar_asset_id,
        avatar_url=avatar_url,
        status=subject.status,
        capabilities=sorted(ctx.principal.capabilities),
        points=points,
    )


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
        subject = await services.identity_queries.get_subject(ctx.principal.subject_id)
        if subject is None:
            from inc.kernel.errors import ErrorCategory, KernelError

            raise KernelError(
                code="identity.not_found",
                category=ErrorCategory.NOT_FOUND,
                message="subject disappeared",
            )
        return await _me_dto(services, ctx, subject)

    @router.patch("/me", response_model=MeDTO)
    async def update_me(
        body: UpdateProfileInput,
        ctx: AppContext = Depends(require_authenticated()),
    ) -> MeDTO:
        subject = await UpdateProfile(_identity_ctx(services, ctx))(
            user_id=ctx.principal.subject_id,
            changes=body,
        )
        return await _me_dto(services, ctx, subject)

    @router.post("/me/avatar/upload-intents", response_model=CreateUploadIntentResult)
    async def create_avatar_upload_intent(
        body: AvatarUploadIntentInput,
        ctx: AppContext = Depends(require_authenticated()),
    ) -> CreateUploadIntentResult:
        asset_ctx = _asset_ctx(services, ctx)
        avatar_bucket = await services.settings_queries.get_value(
            "object_storage", "s3_avatar_bucket"
        )
        return await CreateUploadIntent(asset_ctx)(
            CreateUploadIntentInput(
                provider_key="s3",
                bucket=avatar_bucket,
                mime_types=body.mime_types,
                content_length_max=body.content_length_max,
            )
        )

    @router.post("/me/avatar/upload-intents/{intent_id}/finalize", response_model=MeDTO)
    async def finalize_avatar_upload(
        intent_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> MeDTO:
        asset_ctx = _asset_ctx(services, ctx)
        await FinalizeAsset(asset_ctx)(intent_id)
        instance = await services.runner.find_by_business_key(
            workflow_key=FINALIZE_WORKFLOW_KEY,
            idempotency_key=f"intent:{intent_id}",
        )
        if instance is None:
            from inc.kernel.errors import ErrorCategory, KernelError

            raise KernelError(
                code="assets.finalize_not_started",
                category=ErrorCategory.CONFLICT,
                message="avatar finalize workflow was not started",
            )
        await services.runner.advance(instance.id)
        asset_queries = services.asset_queries
        if asset_queries is None:
            from inc.kernel.errors import ErrorCategory, KernelError

            raise KernelError(
                code="assets.unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="assets capability is not available",
            )
        asset = await asset_queries.get_by_upload_intent(
            intent_id,
            permissions=frozenset({"assets.read"}),
        )
        if asset is None:
            from inc.kernel.errors import ErrorCategory, KernelError

            raise KernelError(
                code="assets.finalize_pending",
                category=ErrorCategory.CONFLICT,
                message="avatar upload has not reached ready state",
            )
        subject = await UpdateProfile(_identity_ctx(services, ctx))(
            user_id=ctx.principal.subject_id,
            changes=UpdateProfileInput(avatar_asset_id=asset.id),
        )
        return await _me_dto(services, ctx, subject)

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

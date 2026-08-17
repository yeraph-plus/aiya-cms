"""Administrator-managed static OIDC clients."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, ConfigDict, Field

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.oidc_provider import (
    ClientCommandContext,
    DisableClient,
    EnableClient,
    RegisterClient,
    RotateClientSecret,
    UpdateClient,
)
from inc.capabilities.oidc_provider.schemas import ClientDTO, ClientRegistrationResult, OidcError
from inc.kernel.errors import ErrorCategory, KernelError

REQUIRED_PERMISSIONS: tuple[str, ...] = (
    "oidc_provider.clients.read",
    "oidc_provider.clients.manage",
)


class RegisterClientBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    client_type: str
    redirect_uris: list[str]
    post_logout_redirect_uris: list[str] = Field(default_factory=list)
    allowed_scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email"])
    allowed_audiences: list[str] = Field(default_factory=list)
    trusted: bool = False
    allow_refresh: bool = True
    client_id: str | None = Field(default=None, min_length=1, max_length=200)


class UpdateClientBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    redirect_uris: list[str]
    post_logout_redirect_uris: list[str] = Field(default_factory=list)
    allowed_scopes: list[str] | None = None
    allowed_audiences: list[str] | None = None


def _ctx(ctx: AppContext, services: Services) -> ClientCommandContext:
    return ClientCommandContext(
        uow_factory=ctx.uow_factory,
        clock=ctx.clock,
        outbox=services.outbox,
        audit_actor_id=ctx.principal.subject_id,
        audit_trace_id=ctx.trace_id,
    )


def _map_error(error: OidcError) -> KernelError:
    return KernelError(
        code=f"oidc.client.{error.code}",
        category=ErrorCategory.VALIDATION,
        message=error.description or error.code,
    )


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin/oidc", tags=["admin", "admin-oidc"])

    @router.get("/clients", response_model=list[ClientDTO])
    async def list_clients(
        ctx: AppContext = Depends(require_capability("oidc_provider.clients.read")),
    ) -> list[ClientDTO]:
        del ctx
        assert services.oidc_client_queries is not None
        return await services.oidc_client_queries.list_clients()

    @router.get("/clients/{client_id}", response_model=ClientDTO)
    async def get_client(
        client_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("oidc_provider.clients.read")),
    ) -> ClientDTO:
        del ctx
        assert services.oidc_client_queries is not None
        client = await services.oidc_client_queries.get_client(client_id)
        if client is None:
            raise KernelError(
                code="oidc_provider.client_not_found",
                category=ErrorCategory.NOT_FOUND,
                message=f"OIDC client {client_id!r} was not found",
            )
        return client

    @router.post("/clients", response_model=ClientRegistrationResult)
    async def register_client(
        body: RegisterClientBody,
        ctx: AppContext = Depends(require_capability("oidc_provider.clients.manage")),
    ) -> ClientRegistrationResult:
        try:
            return await RegisterClient(_ctx(ctx, services))(**body.model_dump())
        except OidcError as error:
            raise _map_error(error) from error

    @router.put("/clients/{client_id}", response_model=ClientDTO)
    async def update_client(
        body: UpdateClientBody,
        client_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("oidc_provider.clients.manage")),
    ) -> ClientDTO:
        try:
            return await UpdateClient(_ctx(ctx, services))(client_id=client_id, **body.model_dump())
        except OidcError as error:
            raise _map_error(error) from error

    @router.post("/clients/{client_id}/disable", response_model=ClientDTO)
    async def disable_client(
        client_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("oidc_provider.clients.manage")),
    ) -> ClientDTO:
        try:
            return await DisableClient(_ctx(ctx, services))(client_id=client_id)
        except OidcError as error:
            raise _map_error(error) from error

    @router.post("/clients/{client_id}/enable", response_model=ClientDTO)
    async def enable_client(
        client_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("oidc_provider.clients.manage")),
    ) -> ClientDTO:
        try:
            return await EnableClient(_ctx(ctx, services))(client_id=client_id)
        except OidcError as error:
            raise _map_error(error) from error

    @router.post("/clients/{client_id}/rotate-secret", response_model=ClientRegistrationResult)
    async def rotate_client_secret(
        client_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("oidc_provider.clients.manage")),
    ) -> ClientRegistrationResult:
        try:
            return await RotateClientSecret(_ctx(ctx, services))(client_id=client_id)
        except OidcError as error:
            raise _map_error(error) from error

    return router

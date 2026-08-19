"""Archive administrator CRUD and named state transition endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from inc.api.archive_services import ArchiveAdminService
from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.archive import (
    ArchiveGrantPageDTO,
    ArchiveItemAdminDTO,
    ArchiveItemPageDTO,
    ArchiveItemPatchInput,
    ArchiveLocatorInput,
    ArchiveQueries,
    DownloadGrantAdminDTO,
    MigrateArchiveItemProviderInput,
    RegisterArchiveItemInput,
    VerifyArchiveItemInput,
)
from inc.kernel.errors import ErrorCategory, KernelError

REQUIRED_PERMISSIONS: tuple[str, ...] = (
    "archive.items.read",
    "archive.items.manage",
    "archive.items.verify",
    "archive.grants.read",
    "archive.grants.revoke",
)


class StateChangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=500)


class MigrateProviderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_key: str = Field(min_length=1, max_length=64)
    provider_contract_version: str = Field(default="1", min_length=1, max_length=32)
    external_locator: ArchiveLocatorInput
    expected_version: int | None = Field(default=None, ge=1)
    reason: str = Field(default="provider migration", min_length=1, max_length=500)


def _queries(services: Services) -> ArchiveQueries:
    value = services.archive_queries
    if value is None:
        raise RuntimeError("archive admin router requires ArchiveQueries")
    return value


def _commands(services: Services) -> ArchiveAdminService:
    value = services.archive_admin
    if value is None:
        raise RuntimeError("archive admin router requires archive admin command service")
    return value


def _not_found(kind: str) -> KernelError:
    return KernelError(
        code=f"archive.{kind}_not_found",
        category=ErrorCategory.NOT_FOUND,
        message=f"archive {kind} was not found",
    )


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any = None,
) -> APIRouter:
    del require_authenticated
    router = APIRouter(prefix="/api/v1/admin/archive", tags=["admin", "admin-archive"])

    @router.get("/items", response_model=ArchiveItemPageDTO)
    async def list_items(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        state: str | None = Query(default=None),
        provider_key: str | None = Query(default=None),
        search: str | None = Query(default=None, max_length=200),
        ctx: AppContext = Depends(require_capability("archive.items.read")),
    ) -> ArchiveItemPageDTO:
        return await _queries(services).list_items_admin(
            page=page,
            size=size,
            state=state,
            provider_key=provider_key,
            search=search,
            permissions=frozenset(ctx.principal.capabilities),
        )

    @router.post("/items", response_model=ArchiveItemAdminDTO)
    async def create_item(
        body: RegisterArchiveItemInput,
        ctx: AppContext = Depends(require_capability("archive.items.manage")),
    ) -> ArchiveItemAdminDTO:
        return await _commands(services).register_item(body, request_context=ctx)

    @router.get("/items/{item_id}", response_model=ArchiveItemAdminDTO)
    async def get_item(
        item_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("archive.items.read")),
    ) -> ArchiveItemAdminDTO:
        found = await _queries(services).get_item_admin(
            item_id, permissions=frozenset(ctx.principal.capabilities)
        )
        if found is None:
            raise _not_found("item")
        return found

    @router.patch("/items/{item_id}", response_model=ArchiveItemAdminDTO)
    async def update_item(
        body: ArchiveItemPatchInput,
        item_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("archive.items.manage")),
    ) -> ArchiveItemAdminDTO:
        return await _commands(services).update_item(item_id, body, request_context=ctx)

    @router.post("/items/{item_id}/verify", response_model=ArchiveItemAdminDTO)
    async def verify_item(
        body: StateChangeBody,
        item_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("archive.items.verify")),
    ) -> ArchiveItemAdminDTO:
        return await _commands(services).verify_item(
            VerifyArchiveItemInput(item_id=item_id, expected_version=body.expected_version),
            request_context=ctx,
        )

    @router.post("/items/{item_id}/activate", response_model=ArchiveItemAdminDTO)
    async def activate_item(
        body: StateChangeBody,
        item_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("archive.items.manage")),
    ) -> ArchiveItemAdminDTO:
        return await _commands(services).activate_item(
            {"item_id": item_id, **body.model_dump()}, request_context=ctx
        )

    @router.post("/items/{item_id}/retire", response_model=ArchiveItemAdminDTO)
    async def retire_item(
        body: StateChangeBody,
        item_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("archive.items.manage")),
    ) -> ArchiveItemAdminDTO:
        return await _commands(services).retire_item(
            {"item_id": item_id, **body.model_dump()}, request_context=ctx
        )

    @router.post("/items/{item_id}/migrate-provider", response_model=ArchiveItemAdminDTO)
    async def migrate_provider(
        body: MigrateProviderBody,
        item_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("archive.items.manage")),
    ) -> ArchiveItemAdminDTO:
        return await _commands(services).migrate_provider(
            MigrateArchiveItemProviderInput(item_id=item_id, **body.model_dump()),
            request_context=ctx,
        )

    @router.get("/grants", response_model=ArchiveGrantPageDTO)
    async def list_grants(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        status: str | None = Query(default=None),
        subject_id: str | None = Query(default=None, max_length=200),
        ctx: AppContext = Depends(require_capability("archive.grants.read")),
    ) -> ArchiveGrantPageDTO:
        return await _queries(services).list_grants_admin(
            page=page,
            size=size,
            status=status,
            subject_id=subject_id,
            permissions=frozenset(ctx.principal.capabilities),
        )

    @router.get("/grants/{grant_id}", response_model=DownloadGrantAdminDTO)
    async def get_grant(
        grant_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("archive.grants.read")),
    ) -> DownloadGrantAdminDTO:
        found = await _queries(services).get_grant_admin(
            grant_id, permissions=frozenset(ctx.principal.capabilities)
        )
        if found is None:
            raise _not_found("grant")
        return found

    @router.post("/grants/{grant_id}/revoke", response_model=DownloadGrantAdminDTO)
    async def revoke_grant(
        body: StateChangeBody,
        grant_id: str = Path(...),
        ctx: AppContext = Depends(require_capability("archive.grants.revoke")),
    ) -> DownloadGrantAdminDTO:
        return await _commands(services).revoke_grant(
            {"grant_id": grant_id, **body.model_dump()}, request_context=ctx
        )

    return router

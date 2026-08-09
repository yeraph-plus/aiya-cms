"""Assets admin router.

Contract source: context/spec/http-openapi.md, capabilities/assets.md.

Upload intents and finalization are asynchronous through workflows;
signed URLs are generated per request and never persisted.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Path, Query

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.assets.commands import (
    CommandContext,
    CreateUploadIntent,
    DeleteAsset,
    FinalizeAsset,
    RegisterExternalAsset,
    UpdateAssetMetadata,
)
from inc.capabilities.assets.schemas import (
    AssetRefDTO,
    CreateUploadIntentInput,
    CreateUploadIntentResult,
    FinalizeResultDTO,
    RegisterExternalAssetInput,
    ResolvedAssetUrlDTO,
    UpdateAssetMetadataInput,
)


def _ctx(ctx: AppContext, services: Services) -> CommandContext:
    return CommandContext(
        uow_factory=ctx.uow_factory,
        clock=ctx.clock,
        outbox=services.outbox,
        providers=(
            {"dev_memory": services.dev_storage} if services.dev_storage is not None else {}
        ),
        runner=services.runner,
        permissions=frozenset(ctx.principal.capabilities),
        actor_id=ctx.principal.subject_id,
        trace_id=ctx.trace_id,
    )


REQUIRED_PERMISSIONS: tuple[str, ...] = (
    "assets.upload",
    "assets.manage",
    "assets.read",
    "assets.delete",
)


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin", tags=["admin", "admin-assets"])

    @router.post("/assets/upload-intents", response_model=CreateUploadIntentResult)
    async def create_upload_intent(
        body: CreateUploadIntentInput,
        ctx: AppContext = Depends(require_capability("assets.upload")),
    ) -> CreateUploadIntentResult:
        return await CreateUploadIntent(_ctx(ctx, services))(body)

    @router.post("/assets/upload-intents/{intent_id}/finalize", response_model=FinalizeResultDTO)
    async def finalize_upload(
        intent_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("assets.upload")),
    ) -> FinalizeResultDTO:
        return await FinalizeAsset(_ctx(ctx, services))(intent_id)

    @router.post("/assets", response_model=AssetRefDTO)
    async def register_external(
        body: RegisterExternalAssetInput,
        ctx: AppContext = Depends(require_capability("assets.manage")),
    ) -> AssetRefDTO:
        return await RegisterExternalAsset(_ctx(ctx, services))(body)

    @router.get("/assets/{asset_id}", response_model=AssetRefDTO)
    async def get_asset(
        asset_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("assets.read")),
    ) -> AssetRefDTO:
        assert services.asset_queries is not None
        asset = await services.asset_queries.get(
            asset_id, permissions=frozenset(ctx.principal.capabilities)
        )
        if asset is None:
            from inc.kernel.errors import ErrorCategory, KernelError

            raise KernelError(
                code="assets.not_found",
                category=ErrorCategory.NOT_FOUND,
                message=f"asset {asset_id}",
            )
        return asset

    @router.get("/assets/{asset_id}/url", response_model=ResolvedAssetUrlDTO)
    async def resolve_url(
        asset_id: uuid.UUID = Path(...),
        expires_in_seconds: int = Query(default=300, ge=1, le=86400),
        ctx: AppContext = Depends(require_capability("assets.read")),
    ) -> ResolvedAssetUrlDTO:
        assert services.asset_queries is not None
        return await services.asset_queries.resolve_url(
            asset_id,
            expires_in_seconds=expires_in_seconds,
            permissions=frozenset(ctx.principal.capabilities),
        )

    @router.patch("/assets/{asset_id}", response_model=AssetRefDTO)
    async def update_metadata(
        body: UpdateAssetMetadataInput,
        asset_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("assets.manage")),
    ) -> AssetRefDTO:
        return await UpdateAssetMetadata(_ctx(ctx, services))(asset_id, body)

    @router.delete("/assets/{asset_id}", status_code=204)
    async def delete_asset(
        asset_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("assets.delete")),
    ) -> None:
        await DeleteAsset(_ctx(ctx, services))(asset_id)

    return router

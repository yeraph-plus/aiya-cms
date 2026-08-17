"""Administrator-only content image upload orchestration.

The router performs HTTP/auth adaptation only.  It delegates upload intent,
normalization and deletion to the public assets capability surface.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, ConfigDict, Field

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.assets import CommandContext
from inc.capabilities.assets.schemas import CreateUploadIntentResult
from inc.features.content_bucket import ContentBucketService

_MAX_SOURCE_BYTES = 20 * 1024 * 1024


class CreateContentUploadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mime_type: str
    content_length_max: int = Field(gt=0, le=_MAX_SOURCE_BYTES)


class ContentImageDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    public_url: str
    mime_type: str
    byte_size: int


class ContentFinalizeDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str
    intent_id: str
    source_asset_id: str | None = None
    image: ContentImageDTO | None = None


def _ctx(ctx: AppContext, services: Services) -> CommandContext:
    return CommandContext(
        uow_factory=ctx.uow_factory,
        clock=ctx.clock,
        outbox=services.outbox,
        providers=services.asset_providers,
        runner=services.runner,
        permissions=frozenset(ctx.principal.capabilities),
        actor_id=ctx.principal.subject_id,
        trace_id=ctx.trace_id,
    )


async def _feature(ctx: AppContext, services: Services) -> ContentBucketService:
    if services.asset_queries is None:
        raise RuntimeError("content bucket feature requires assets queries")
    return ContentBucketService(
        assets=_ctx(ctx, services),
        asset_queries=services.asset_queries,
        settings=services.settings_queries,
        provider_key=await services.selected_provider_key("assets.object_storage"),
    )


REQUIRED_PERMISSIONS = ("assets.upload", "assets.manage", "assets.delete", "assets.read")


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any = None,
) -> APIRouter:
    del require_authenticated
    router = APIRouter(
        prefix="/api/v1/admin/content-bucket", tags=["admin", "admin-content-bucket"]
    )

    @router.post("/upload-intents", response_model=CreateUploadIntentResult)
    async def create_upload_intent(
        body: CreateContentUploadBody,
        ctx: AppContext = Depends(require_capability("assets.upload")),
    ) -> CreateUploadIntentResult:
        return await (await _feature(ctx, services)).create_upload_intent(
            mime_type=body.mime_type,
            content_length_max=body.content_length_max,
        )

    @router.post("/upload-intents/{intent_id}/finalize", response_model=ContentFinalizeDTO)
    async def finalize_upload(
        intent_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("assets.manage")),
        _upload: AppContext = Depends(require_capability("assets.upload")),
        _read: AppContext = Depends(require_capability("assets.read")),
    ) -> ContentFinalizeDTO:
        result = await (await _feature(ctx, services)).finalize(intent_id)
        return ContentFinalizeDTO(
            state=result.state,
            intent_id=result.intent_id,
            source_asset_id=result.source_asset_id,
            image=(
                ContentImageDTO(
                    asset_id=result.image.asset_id,
                    public_url=result.image.public_url,
                    mime_type=result.image.mime_type,
                    byte_size=result.image.byte_size,
                )
                if result.image is not None
                else None
            ),
        )

    @router.get("/upload-intents/{intent_id}", response_model=ContentFinalizeDTO)
    async def content_upload_status(
        intent_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("assets.read")),
    ) -> ContentFinalizeDTO:
        result = await (await _feature(ctx, services)).processing_status(intent_id)
        return ContentFinalizeDTO(
            state=result.state,
            intent_id=result.intent_id,
            source_asset_id=result.source_asset_id,
            image=(
                ContentImageDTO(
                    asset_id=result.image.asset_id,
                    public_url=result.image.public_url,
                    mime_type=result.image.mime_type,
                    byte_size=result.image.byte_size,
                )
                if result.image is not None
                else None
            ),
        )

    @router.get("/assets/{asset_id}", response_model=ContentImageDTO)
    async def get_content_image(
        asset_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("assets.read")),
    ) -> ContentImageDTO:
        image = await (await _feature(ctx, services)).get(asset_id)
        return ContentImageDTO(
            asset_id=image.asset_id,
            public_url=image.public_url,
            mime_type=image.mime_type,
            byte_size=image.byte_size,
        )

    @router.delete("/assets/{asset_id}", status_code=204)
    async def delete_content_image(
        asset_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("assets.delete")),
        _read: AppContext = Depends(require_capability("assets.read")),
    ) -> None:
        await (await _feature(ctx, services)).delete(asset_id)

    return router

"""Admin image-hosting orchestration over the public assets surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from inc.capabilities.assets import (
    AssetQueries,
    CreateUploadIntent,
    DeleteAsset,
    FinalizeContentImage,
)
from inc.capabilities.assets import (
    CommandContext as AssetCommandContext,
)
from inc.capabilities.assets.schemas import CreateUploadIntentInput, CreateUploadIntentResult
from inc.capabilities.settings import SettingsQueries
from inc.kernel.errors import ErrorCategory, KernelError

_ALLOWED_MIME_TYPES = ("image/jpeg", "image/png", "image/webp")
_MAX_SOURCE_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ContentImage:
    asset_id: str
    public_url: str
    mime_type: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class ContentFinalizeResult:
    state: str
    intent_id: str
    source_asset_id: str | None = None
    image: ContentImage | None = None


class ContentBucketService:
    """Feature workflow: private source intent -> asset finalize -> WebP result."""

    def __init__(
        self,
        *,
        assets: AssetCommandContext,
        asset_queries: AssetQueries,
        settings: SettingsQueries,
        provider_key: str,
    ) -> None:
        self._assets = assets
        self._asset_queries = asset_queries
        self._settings = settings
        self._provider_key = provider_key

    async def create_upload_intent(
        self, *, mime_type: str, content_length_max: int
    ) -> CreateUploadIntentResult:
        if mime_type not in _ALLOWED_MIME_TYPES:
            raise KernelError(
                code="assets.unsupported_image",
                category=ErrorCategory.VALIDATION,
                message="content bucket accepts JPEG, PNG and WebP only",
            )
        if not 0 < content_length_max <= _MAX_SOURCE_BYTES:
            raise KernelError(
                code="assets.image_too_large",
                category=ErrorCategory.VALIDATION,
                message="content image source must not exceed 20 MiB",
            )
        return await CreateUploadIntent(self._assets)(
            CreateUploadIntentInput(
                provider_key=self._provider_key,
                bucket="system",
                content_length_max=content_length_max,
                mime_types=(mime_type,),
            )
        )

    async def finalize(self, intent_id: Any) -> ContentFinalizeResult:
        current = await self.processing_status(intent_id)
        if current.state in {"ready", "failed"}:
            return current
        values = (await self._settings.get_group("object_storage")).values
        await FinalizeContentImage(self._assets)(
            intent_id,
            max_edge=int(values["content_image_max_edge"]),
            quality=int(values["content_image_webp_quality"]),
        )
        return ContentFinalizeResult(state="finalizing", intent_id=str(intent_id))

    async def processing_status(self, intent_id: Any) -> ContentFinalizeResult:
        """Read-only status suitable for client polling after ``finalize``."""

        source = await self._asset_queries.get_upload_intent_asset(
            intent_id,
            permissions=self._assets.permissions,
        )
        if source is None:
            return ContentFinalizeResult(state="finalizing", intent_id=str(intent_id))
        result = await self._asset_queries.get_content_derivative(
            source.id,
            permissions=self._assets.permissions,
        )
        if result is not None:
            public_url = result.metadata.get("public_url")
            if not isinstance(public_url, str):
                raise KernelError(
                    code="assets.public_url_unavailable",
                    category=ErrorCategory.CONFLICT,
                    message="content image URL is unavailable",
                )
            return ContentFinalizeResult(
                state="ready",
                intent_id=str(intent_id),
                source_asset_id=source.id,
                image=ContentImage(
                    asset_id=result.id,
                    public_url=public_url,
                    mime_type=result.mime_type,
                    byte_size=result.byte_size,
                ),
            )
        if source.state in {"failed", "deleted"}:
            return ContentFinalizeResult(
                state="failed",
                intent_id=str(intent_id),
                source_asset_id=source.id,
            )
        return ContentFinalizeResult(
            state="processing",
            intent_id=str(intent_id),
            source_asset_id=source.id,
        )

    async def get(self, asset_id: Any) -> ContentImage:
        asset = await self._asset_queries.get(asset_id, permissions=self._assets.permissions)
        if asset is None or asset.bucket != "content" or asset.state != "ready":
            raise KernelError(
                code="assets.not_found",
                category=ErrorCategory.NOT_FOUND,
                message="content image not found",
            )
        public_url = asset.metadata.get("public_url")
        if not isinstance(public_url, str):
            raise KernelError(
                code="assets.public_url_unavailable",
                category=ErrorCategory.CONFLICT,
                message="content image URL is unavailable",
            )
        return ContentImage(
            asset_id=asset.id,
            public_url=public_url,
            mime_type=asset.mime_type,
            byte_size=asset.byte_size,
        )

    async def delete(self, asset_id: Any) -> None:
        image = await self.get(asset_id)
        del image
        await DeleteAsset(self._assets)(asset_id)


__all__ = ["ContentBucketService", "ContentFinalizeResult", "ContentImage"]

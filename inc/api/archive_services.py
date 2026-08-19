"""Composition adapters for archive administration and work pricing."""

from __future__ import annotations

from typing import Any, cast

from inc.capabilities.archive import (
    ActivateArchiveItem,
    ArchiveCommandContext,
    ArchiveItemAdminDTO,
    ArchiveItemPatchInput,
    ArchiveItemStateInput,
    DownloadGrantAdminDTO,
    GrantStateInput,
    MigrateArchiveItemProvider,
    MigrateArchiveItemProviderInput,
    RegisterArchiveItem,
    RegisterArchiveItemInput,
    RetireArchiveItem,
    RevokeDownloadGrant,
    UpdateArchiveItem,
    VerifyArchiveItem,
    VerifyArchiveItemInput,
)
from inc.features.business_center import (
    ArchiveFileCost,
    ArchiveManifestCostBasis,
    BusinessProductSpec,
)
from inc.kernel.errors import ErrorCategory, KernelError


class ArchiveAdminService:
    def __init__(self, ctx: ArchiveCommandContext) -> None:
        self._ctx = ctx

    def _context(self, request_context: Any) -> ArchiveCommandContext:
        return ArchiveCommandContext(
            uow_factory=self._ctx.uow_factory,
            clock=self._ctx.clock,
            outbox=self._ctx.outbox,
            providers=self._ctx.providers,
            provider_settings=self._ctx.provider_settings,
            permissions=frozenset(request_context.principal.capabilities),
            actor_id=request_context.principal.subject_id,
            trace_id=request_context.trace_id,
        )

    async def register_item(
        self, input_: RegisterArchiveItemInput, *, request_context: Any
    ) -> ArchiveItemAdminDTO:
        return await RegisterArchiveItem(self._context(request_context))(input_)

    async def update_item(
        self,
        item_id: str,
        input_: ArchiveItemPatchInput,
        *,
        request_context: Any,
    ) -> ArchiveItemAdminDTO:
        return await UpdateArchiveItem(self._context(request_context))(item_id, input_)

    async def verify_item(
        self, input_: VerifyArchiveItemInput, *, request_context: Any
    ) -> ArchiveItemAdminDTO:
        return await VerifyArchiveItem(self._context(request_context))(input_)

    async def activate_item(
        self, input_: ArchiveItemStateInput | dict[str, Any], *, request_context: Any
    ) -> ArchiveItemAdminDTO:
        command_input = ArchiveItemStateInput.model_validate(input_)
        return await ActivateArchiveItem(self._context(request_context))(command_input)

    async def retire_item(
        self, input_: ArchiveItemStateInput | dict[str, Any], *, request_context: Any
    ) -> ArchiveItemAdminDTO:
        command_input = ArchiveItemStateInput.model_validate(input_)
        return await RetireArchiveItem(self._context(request_context))(command_input)

    async def migrate_provider(
        self, input_: MigrateArchiveItemProviderInput, *, request_context: Any
    ) -> ArchiveItemAdminDTO:
        return await MigrateArchiveItemProvider(self._context(request_context))(input_)

    async def revoke_grant(
        self, input_: GrantStateInput | dict[str, Any], *, request_context: Any
    ) -> DownloadGrantAdminDTO:
        command_input = GrantStateInput.model_validate(input_)
        result = await RevokeDownloadGrant(self._context(request_context))(command_input)
        return cast(DownloadGrantAdminDTO, result)


class WorkArchiveCostBasis:
    def __init__(self, content_queries: Any) -> None:
        self._content = content_queries

    async def resolve(
        self, *, product: BusinessProductSpec, target_ref: str, parameters: Any
    ) -> ArchiveManifestCostBasis:
        del product, parameters
        try:
            content = await self._content.get_published_by_slug(type_name="work", slug=target_ref)
        except TypeError, ValueError:
            content = None
        if content is None:
            raise KernelError(
                code="business_center.target_not_found",
                category=ErrorCategory.NOT_FOUND,
                message="published work was not found",
            )
        data = dict(content.data)
        manifest_version = str(data.get("archive_manifest_version", ""))
        raw_files = data.get("download_files", ())
        if not manifest_version or not isinstance(raw_files, (list, tuple)) or not raw_files:
            raise KernelError(
                code="business_center.target_not_found",
                category=ErrorCategory.NOT_FOUND,
                message="published work has no downloadable archive manifest",
            )
        files = tuple(
            ArchiveFileCost(
                file_id=str(item["archive_item_id"]),
                version=int(item.get("version", 1)),
                part_number=int(item["part_number"]),
                size_bytes=int(item["size_bytes"]),
                active=True,
            )
            for item in raw_files
            if isinstance(item, dict)
        )
        if not files:
            raise KernelError(
                code="business_center.target_not_found",
                category=ErrorCategory.NOT_FOUND,
                message="published work has no downloadable archive manifest",
            )
        return ArchiveManifestCostBasis(
            target_ref=target_ref,
            manifest_version=manifest_version,
            files=files,
        )


__all__ = ["ArchiveAdminService", "WorkArchiveCostBasis"]

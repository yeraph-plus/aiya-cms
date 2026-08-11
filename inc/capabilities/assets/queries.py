"""Assets queries.

Contract source: context/spec/capabilities/assets.md §5.

Signed URLs are generated per request through the provider adapter with an
explicit expiry; they are never persisted or cached in the database.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from inc.capabilities.assets.commands import PERMISSION_READ, CommandContext, _provider, _to_ref
from inc.capabilities.assets.models import AssetObject, AssetUploadIntent
from inc.capabilities.assets.ports import StorageError, storage_error
from inc.capabilities.assets.schemas import AssetPageDTO, AssetRefDTO, ResolvedAssetUrlDTO
from inc.kernel.db import fetch_page
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.time import Clock


class AssetQueries:
    """Read-only assets surface."""

    def __init__(self, *, ctx: CommandContext, clock: Clock) -> None:
        self._ctx = ctx
        self._clock = clock

    async def get(  # type: ignore[return]
        self, asset_id: Any, *, permissions: frozenset[str]
    ) -> AssetRefDTO | None:
        if PERMISSION_READ not in permissions:
            raise KernelError(
                code="assets.forbidden",
                category=ErrorCategory.FORBIDDEN,
                message=f"requires permission {PERMISSION_READ}",
            )
        async with self._ctx.uow_factory() as uow:
            row: AssetObject | None = await uow.session.get(AssetObject, asset_id)
            return _to_ref(row) if row is not None else None

    async def list(  # type: ignore[return]
        self,
        *,
        page: int,
        size: int,
        permissions: frozenset[str],
        state: str | None = None,
        provider_key: str | None = None,
        bucket: str | None = None,
        search: str | None = None,
    ) -> AssetPageDTO:
        if PERMISSION_READ not in permissions:
            raise KernelError(
                code="assets.forbidden",
                category=ErrorCategory.FORBIDDEN,
                message=f"requires permission {PERMISSION_READ}",
            )
        async with self._ctx.uow_factory() as uow:
            statement = select(AssetObject)
            if state is not None:
                statement = statement.where(AssetObject.state == state)
            if provider_key is not None:
                statement = statement.where(AssetObject.provider_key == provider_key)
            if bucket is not None:
                statement = statement.where(AssetObject.bucket == bucket)
            if search is not None:
                statement = statement.where(AssetObject.object_key.ilike(f"%{search}%"))
            statement = statement.order_by(AssetObject.created_at.desc(), AssetObject.id.desc())
            result = await fetch_page(uow.session, statement, page=page, size=size)
            return AssetPageDTO(
                items=[_to_ref(row) for row in result.items],
                total=result.total,
                page=result.page,
                size=result.size,
            )

    async def resolve_url(
        self,
        asset_id: Any,
        *,
        expires_in_seconds: int = 300,
        permissions: frozenset[str],
    ) -> ResolvedAssetUrlDTO:
        if PERMISSION_READ not in permissions:
            raise KernelError(
                code="assets.forbidden",
                category=ErrorCategory.FORBIDDEN,
                message=f"requires permission {PERMISSION_READ}",
            )
        if not 1 <= expires_in_seconds <= 86400:
            raise KernelError(
                code="assets.invalid_expiry",
                category=ErrorCategory.VALIDATION,
                message="expires_in_seconds must be within 1..86400",
            )
        async with self._ctx.uow_factory() as uow:
            row: AssetObject | None = await uow.session.get(AssetObject, asset_id)
        if row is None:
            raise KernelError(
                code="assets.not_found",
                category=ErrorCategory.NOT_FOUND,
                message=f"asset {asset_id}",
            )
        if row.state != "ready":
            raise KernelError(
                code="assets.not_ready",
                category=ErrorCategory.CONFLICT,
                message=f"asset is {row.state}",
            )
        provider = _provider(self._ctx, row.provider_key)
        try:
            url = await provider.read_url(
                bucket=row.bucket, object_key=row.object_key, expires_in_seconds=expires_in_seconds
            )
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider errors map to storage errors
            raise storage_error(str(exc)) from exc
        return ResolvedAssetUrlDTO(
            asset_id=str(row.id),
            url=url,
            expires_in_seconds=expires_in_seconds,
        )

    async def get_by_upload_intent(
        self, intent_id: Any, *, permissions: frozenset[str]
    ) -> AssetRefDTO | None:
        """Return the ready asset created by an upload intent, if finalized."""

        if PERMISSION_READ not in permissions:
            raise KernelError(
                code="assets.forbidden",
                category=ErrorCategory.FORBIDDEN,
                message=f"requires permission {PERMISSION_READ}",
            )
        async with self._ctx.uow_factory() as uow:
            intent: AssetUploadIntent | None = await uow.session.get(AssetUploadIntent, intent_id)
            if intent is None:
                return None
            row = (
                (
                    await uow.session.execute(
                        select(AssetObject).where(
                            AssetObject.provider_key == intent.provider_key,
                            AssetObject.bucket == intent.bucket,
                            AssetObject.object_key == intent.object_key,
                            AssetObject.state == "ready",
                        )
                    )
                )
                .scalars()
                .first()
            )
            return _to_ref(row) if row is not None else None
        raise AssertionError("asset upload intent query exited without returning")

"""Assets queries.

Contract source: context/spec/capabilities/assets.md §5.

Signed URLs are generated per request through the provider adapter with an
explicit expiry; they are never persisted or cached in the database.
"""

from __future__ import annotations

from typing import Any

from inc.capabilities.assets.commands import PERMISSION_READ, CommandContext, _provider, _to_ref
from inc.capabilities.assets.models import AssetObject
from inc.capabilities.assets.schemas import AssetRefDTO, ResolvedAssetUrlDTO
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.time import Clock


class AssetQueries:
    """Read-only assets surface."""

    def __init__(self, *, ctx: CommandContext, clock: Clock) -> None:
        self._ctx = ctx
        self._clock = clock

    async def get(self, asset_id: Any) -> AssetRefDTO | None:  # type: ignore[return]
        if PERMISSION_READ not in self._ctx.permissions:
            raise KernelError(
                code="assets.forbidden",
                category=ErrorCategory.FORBIDDEN,
                message=f"requires permission {PERMISSION_READ}",
            )
        async with self._ctx.uow_factory() as uow:
            row: AssetObject | None = await uow.session.get(AssetObject, asset_id)
            return _to_ref(row) if row is not None else None

    async def resolve_url(
        self, asset_id: Any, *, expires_in_seconds: int = 300
    ) -> ResolvedAssetUrlDTO:
        if PERMISSION_READ not in self._ctx.permissions:
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
        url = await provider.read_url(
            object_key=row.object_key, expires_in_seconds=expires_in_seconds
        )
        return ResolvedAssetUrlDTO(
            asset_id=str(row.id),
            url=url,
            expires_in_seconds=expires_in_seconds,
        )

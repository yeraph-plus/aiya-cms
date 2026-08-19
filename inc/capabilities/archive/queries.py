"""Read-only archive Queries.

Queries never probe providers, refresh links, change state or append events.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from inc.capabilities.archive.commands import (
    PERMISSION_GRANT_READ,
    PERMISSION_ITEM_READ,
    _attempt_dto,
    _grant_dto,
    _item_admin_dto,
    _item_dto,
)
from inc.capabilities.archive.models import (
    ArchiveDeliveryAttempt,
    ArchiveDownloadGrant,
    ArchiveItem,
)
from inc.capabilities.archive.schemas import (
    ArchiveGrantPageDTO,
    ArchiveItemAdminDTO,
    ArchiveItemDTO,
    ArchiveItemPageDTO,
    DeliveryAttemptDTO,
    DownloadGrantAdminDTO,
    DownloadGrantDTO,
    DownloadGrantPageDTO,
    GrantCostBasisDTO,
)
from inc.kernel.db import UoWFactory, fetch_page
from inc.kernel.errors import ErrorCategory, KernelError


def _forbidden(message: str) -> KernelError:
    return KernelError(code="archive.forbidden", category=ErrorCategory.FORBIDDEN, message=message)


def _not_found(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.NOT_FOUND, message=message)


def _uuid(value: Any, *, code: str, label: str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise _not_found(code, f"{label} {value}") from exc


class ArchiveQueries:
    """Capability-owned read surface used by features and HTTP adapters."""

    def __init__(
        self,
        *,
        uow_factory: UoWFactory | None = None,
        ctx: Any | None = None,
        permissions: frozenset[str] | None = None,
    ) -> None:
        if uow_factory is None and ctx is None:
            raise ValueError("ArchiveQueries requires uow_factory or ctx")
        if uow_factory is not None:
            self._uow_factory = uow_factory
        else:
            assert ctx is not None
            self._uow_factory = ctx.uow_factory
        self._permissions = (
            permissions
            if permissions is not None
            else (ctx.permissions if ctx is not None else frozenset())
        )

    def _require(self, permission: str, permissions: frozenset[str] | None) -> None:
        selected = self._permissions if permissions is None else permissions
        if permission not in selected:
            raise _forbidden(f"requires permission {permission}")

    async def get_archive_item_public(
        self,
        item_id: Any,
        *,
        permissions: frozenset[str] | None = None,
    ) -> ArchiveItemDTO | None:
        parsed = _uuid(item_id, code="archive.item_not_found", label="item")
        async with self._uow_factory() as uow:
            row: ArchiveItem | None = await uow.session.get(ArchiveItem, parsed)
            if row is None or row.state != "active":
                return None
            return _item_dto(row)
        raise AssertionError("unreachable: get public archive item completed")

    async def get_item_public(self, item_id: Any, **kwargs: Any) -> ArchiveItemDTO | None:
        return await self.get_archive_item_public(item_id, **kwargs)

    async def batch_get_archive_items_public(
        self,
        item_ids: list[Any] | tuple[Any, ...],
        *,
        permissions: frozenset[str] | None = None,
    ) -> list[ArchiveItemDTO]:
        parsed = [_uuid(value, code="archive.item_not_found", label="item") for value in item_ids]
        if not parsed:
            return []
        async with self._uow_factory() as uow:
            rows = (
                (
                    await uow.session.execute(
                        select(ArchiveItem).where(
                            ArchiveItem.id.in_(parsed), ArchiveItem.state == "active"
                        )
                    )
                )
                .scalars()
                .all()
            )
            by_id = {row.id: row for row in rows}
            return [_item_dto(by_id[value]) for value in parsed if value in by_id]
        raise AssertionError("unreachable: batch get public archive items completed")

    async def get_item_admin(
        self,
        item_id: Any,
        *,
        permissions: frozenset[str] | None = None,
    ) -> ArchiveItemAdminDTO | None:
        self._require(PERMISSION_ITEM_READ, permissions)
        parsed = _uuid(item_id, code="archive.item_not_found", label="item")
        async with self._uow_factory() as uow:
            row: ArchiveItem | None = await uow.session.get(ArchiveItem, parsed)
            return _item_admin_dto(row) if row is not None else None
        raise AssertionError("unreachable: get admin archive item completed")

    async def list_items_admin(
        self,
        *,
        page: int,
        size: int,
        state: str | None = None,
        provider_key: str | None = None,
        search: str | None = None,
        permissions: frozenset[str] | None = None,
    ) -> ArchiveItemPageDTO:
        self._require(PERMISSION_ITEM_READ, permissions)
        async with self._uow_factory() as uow:
            statement = select(ArchiveItem)
            if state is not None:
                statement = statement.where(ArchiveItem.state == state)
            if provider_key is not None:
                statement = statement.where(ArchiveItem.provider_key == provider_key)
            if search:
                statement = statement.where(ArchiveItem.item_key.ilike(f"%{search}%"))
            statement = statement.order_by(ArchiveItem.part_number, ArchiveItem.id)
            result = await fetch_page(uow.session, statement, page=page, size=size)
            return ArchiveItemPageDTO(
                items=[_item_admin_dto(row) for row in result.items],
                total=result.total,
                page=result.page,
                size=result.size,
            )
        raise AssertionError("unreachable: list admin archive items completed")

    async def get_download_grant_for_subject(
        self,
        grant_id: Any,
        *,
        subject_type: str,
        subject_id: str,
        permissions: frozenset[str] | None = None,
    ) -> DownloadGrantDTO | None:
        parsed = _uuid(grant_id, code="archive.grant_not_found", label="grant")
        async with self._uow_factory() as uow:
            row: ArchiveDownloadGrant | None = await uow.session.get(ArchiveDownloadGrant, parsed)
            if row is None:
                return None
            if row.subject_type != subject_type or row.subject_id != subject_id:
                raise KernelError(
                    code="archive.grant_forbidden",
                    category=ErrorCategory.FORBIDDEN,
                    message="grant does not belong to subject",
                )
            return _grant_dto(row)
        raise AssertionError("unreachable: get subject download grant completed")

    async def get_grant_for_subject(self, *args: Any, **kwargs: Any) -> DownloadGrantDTO | None:
        return await self.get_download_grant_for_subject(*args, **kwargs)

    async def list_download_grants_for_subject(
        self,
        *,
        subject_type: str,
        subject_id: str,
        page: int,
        size: int,
        status: str | None = None,
        permissions: frozenset[str] | None = None,
    ) -> DownloadGrantPageDTO:
        async with self._uow_factory() as uow:
            statement = select(ArchiveDownloadGrant).where(
                ArchiveDownloadGrant.subject_type == subject_type,
                ArchiveDownloadGrant.subject_id == subject_id,
            )
            if status is not None:
                statement = statement.where(ArchiveDownloadGrant.status == status)
            statement = statement.order_by(
                ArchiveDownloadGrant.created_at.desc(), ArchiveDownloadGrant.id.desc()
            )
            result = await fetch_page(uow.session, statement, page=page, size=size)
            return DownloadGrantPageDTO(
                items=[_grant_dto(row) for row in result.items],
                total=result.total,
                page=result.page,
                size=result.size,
            )
        raise AssertionError("unreachable: list subject download grants completed")

    async def list_grants_for_subject(self, **kwargs: Any) -> DownloadGrantPageDTO:
        return await self.list_download_grants_for_subject(**kwargs)

    async def get_grant_admin(
        self,
        grant_id: Any,
        *,
        permissions: frozenset[str] | None = None,
    ) -> DownloadGrantAdminDTO | None:
        self._require(PERMISSION_GRANT_READ, permissions)
        parsed = _uuid(grant_id, code="archive.grant_not_found", label="grant")
        async with self._uow_factory() as uow:
            row: ArchiveDownloadGrant | None = await uow.session.get(ArchiveDownloadGrant, parsed)
            if row is None:
                return None
            return DownloadGrantAdminDTO(
                **_grant_dto(row).model_dump(),
                idempotency_key_digest=row.idempotency_key_digest,
            )
        raise AssertionError("unreachable: get admin download grant completed")

    async def list_grants_admin(
        self,
        *,
        page: int,
        size: int,
        status: str | None = None,
        subject_id: str | None = None,
        permissions: frozenset[str] | None = None,
    ) -> ArchiveGrantPageDTO:
        self._require(PERMISSION_GRANT_READ, permissions)
        async with self._uow_factory() as uow:
            statement = select(ArchiveDownloadGrant)
            if status is not None:
                statement = statement.where(ArchiveDownloadGrant.status == status)
            if subject_id is not None:
                statement = statement.where(ArchiveDownloadGrant.subject_id == subject_id)
            statement = statement.order_by(
                ArchiveDownloadGrant.created_at.desc(), ArchiveDownloadGrant.id.desc()
            )
            result = await fetch_page(uow.session, statement, page=page, size=size)
            return ArchiveGrantPageDTO(
                items=[
                    DownloadGrantAdminDTO(
                        **_grant_dto(row).model_dump(),
                        idempotency_key_digest=row.idempotency_key_digest,
                    )
                    for row in result.items
                ],
                total=result.total,
                page=result.page,
                size=result.size,
            )
        raise AssertionError("unreachable: list admin download grants completed")

    async def get_grant_cost_basis(
        self,
        grant_id: Any,
        *,
        subject_type: str | None = None,
        subject_id: str | None = None,
        permissions: frozenset[str] | None = None,
    ) -> GrantCostBasisDTO:
        parsed = _uuid(grant_id, code="archive.grant_not_found", label="grant")
        async with self._uow_factory() as uow:
            row: ArchiveDownloadGrant | None = await uow.session.get(ArchiveDownloadGrant, parsed)
            if row is None:
                raise _not_found("archive.grant_not_found", f"grant {grant_id}")
            selected = self._permissions if permissions is None else permissions
            if PERMISSION_GRANT_READ not in selected:
                if subject_type != row.subject_type or subject_id != row.subject_id:
                    raise KernelError(
                        code="archive.grant_forbidden",
                        category=ErrorCategory.FORBIDDEN,
                        message="grant does not belong to subject",
                    )
            return GrantCostBasisDTO(
                grant_id=str(row.id),
                file_count=len(row.item_snapshot.items),
                size_bytes=sum(item.size_bytes for item in row.item_snapshot.items),
                manifest_digest=row.manifest_digest,
            )
        raise AssertionError("unreachable: get grant cost basis completed")

    async def get_delivery_attempts(
        self,
        grant_id: Any,
        *,
        permissions: frozenset[str] | None = None,
    ) -> list[DeliveryAttemptDTO]:
        self._require(PERMISSION_GRANT_READ, permissions)
        parsed = _uuid(grant_id, code="archive.grant_not_found", label="grant")
        async with self._uow_factory() as uow:
            rows = (
                (
                    await uow.session.execute(
                        select(ArchiveDeliveryAttempt)
                        .where(ArchiveDeliveryAttempt.grant_id == parsed)
                        .order_by(ArchiveDeliveryAttempt.started_at, ArchiveDeliveryAttempt.id)
                    )
                )
                .scalars()
                .all()
            )
            return [_attempt_dto(row) for row in rows]
        raise AssertionError("unreachable: get delivery attempts completed")

    # Query names from the capability specification.
    GetArchiveItemPublic = get_archive_item_public
    BatchGetArchiveItemsPublic = batch_get_archive_items_public
    GetArchiveItemAdmin = get_item_admin
    ListArchiveItemsAdmin = list_items_admin
    GetDownloadGrantForSubject = get_download_grant_for_subject
    ListDownloadGrantsForSubject = list_download_grants_for_subject
    GetDownloadGrantAdmin = get_grant_admin
    ListDownloadGrantsAdmin = list_grants_admin
    GetGrantCostBasis = get_grant_cost_basis

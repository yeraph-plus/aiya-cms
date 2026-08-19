"""Archive delivery Activity.

Provider calls happen outside database transactions. Only safe attempt facts
are committed after the provider result is normalized.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from inc.capabilities.archive.commands import (
    PERMISSION_DELIVERY,
    CommandContext,
    _required_utc,
    _settings,
    _uuid,
)
from inc.capabilities.archive.models import (
    ArchiveDeliveryAttempt,
    ArchiveDownloadGrant,
    ArchiveItem,
)
from inc.capabilities.archive.ports import (
    ArchiveDeliveryRequest,
    ArchiveProviderError,
    ProviderDelivery,
)
from inc.capabilities.archive.schemas import (
    ArchiveDeliveryLinkDTO,
    ResolveDownloadLinksDTO,
)
from inc.kernel.db import UnitOfWork
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.workflow import ActivityContext

DELIVERY_LINK_TTL_SECONDS = 5 * 60


def _forbidden(message: str) -> KernelError:
    return KernelError(code="archive.forbidden", category=ErrorCategory.FORBIDDEN, message=message)


def _conflict(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.CONFLICT, message=message)


def _not_found(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.NOT_FOUND, message=message)


def _attempt_status(delivery: ProviderDelivery) -> str:
    if delivery.status in {"redirect", "proxy"}:
        return "delivered"
    if delivery.status == "proxy_required":
        return "proxy_required"
    if delivery.status == "unknown":
        return "unknown"
    return "failed"


class ResolveDownloadLinks:
    """Resolve every item in a grant snapshot through its bound provider."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self,
        grant_id: Any,
        *,
        subject_type: str | None = None,
        subject_id: str | None = None,
    ) -> ResolveDownloadLinksDTO:
        ctx = self._ctx
        if PERMISSION_DELIVERY not in ctx.permissions:
            raise _forbidden(f"requires permission {PERMISSION_DELIVERY}")
        parsed_grant_id = _uuid(grant_id, code="archive.grant_not_found", label="grant")
        async with ctx.uow_factory() as uow:
            grant: ArchiveDownloadGrant | None = await uow.session.get(
                ArchiveDownloadGrant, parsed_grant_id
            )
            if grant is None:
                raise _not_found("archive.grant_not_found", f"grant {grant_id}")
            if subject_type is not None and subject_id is not None:
                if grant.subject_type != subject_type or grant.subject_id != subject_id:
                    raise _forbidden("grant does not belong to subject")
            now = ctx.clock.utc_now()
            if grant.status != "active":
                if grant.status == "expired":
                    raise _conflict("archive.grant_expired", "grant has expired")
                raise _conflict("archive.grant_forbidden", f"grant is {grant.status}")
            if _required_utc(grant.expires_at) <= now:
                raise _conflict("archive.grant_expired", "grant has expired")
            snapshot = grant.item_snapshot
            item_ids = [uuid.UUID(item.item_id) for item in snapshot.items]
            rows = (
                (await uow.session.execute(select(ArchiveItem).where(ArchiveItem.id.in_(item_ids))))
                .scalars()
                .all()
            )
            by_id = {row.id: row for row in rows}
            latest_rows = (
                (
                    await uow.session.execute(
                        select(ArchiveDeliveryAttempt)
                        .where(ArchiveDeliveryAttempt.grant_id == parsed_grant_id)
                        .order_by(
                            ArchiveDeliveryAttempt.item_id,
                            ArchiveDeliveryAttempt.attempt_number.desc(),
                        )
                    )
                )
                .scalars()
                .all()
            )
            latest_by_item: dict[uuid.UUID, ArchiveDeliveryAttempt] = {}
            for delivery_attempt in latest_rows:
                latest_by_item.setdefault(delivery_attempt.item_id, delivery_attempt)

            prepared: list[tuple[Any, ArchiveItem, ArchiveDeliveryAttempt | None, Any]] = []
            for item_snapshot in snapshot.items:
                parsed_item_id = uuid.UUID(item_snapshot.item_id)
                row = by_id.get(parsed_item_id)
                if row is None:
                    raise _conflict("archive.manifest_mismatch", "grant item no longer exists")
                if row.version != item_snapshot.version:
                    raise _conflict("archive.manifest_mismatch", "grant item version changed")
                if row.state != "active":
                    raise _conflict("archive.item_not_deliverable", "grant item is not active")
                link_expires_at = min(
                    _required_utc(grant.expires_at),
                    now + timedelta(seconds=DELIVERY_LINK_TTL_SECONDS),
                )
                prepared.append(
                    (item_snapshot, row, latest_by_item.get(parsed_item_id), link_expires_at)
                )

        resolved: list[tuple[Any, ProviderDelivery, Any, ArchiveDeliveryAttempt | None]] = []
        for item_snapshot, row, previous, link_expires_at in prepared:
            provider = ctx.providers.get(row.provider_key)
            if provider is None:
                delivery = ProviderDelivery(
                    status="unavailable", reason_code="archive.unknown_provider"
                )
                resolved.append((item_snapshot, delivery, link_expires_at, None))
                continue
            request = ArchiveDeliveryRequest(
                locator=row.external_locator,
                item_ref=str(row.id),
                expires_at=link_expires_at,
                provider_contract_version=row.provider_contract_version,
            )
            try:
                if (
                    previous is not None
                    and previous.provider_delivery_ref
                    and previous.status in {"delivered", "proxy_required"}
                ):
                    delivery = await provider.refresh_delivery(
                        provider_delivery_ref=previous.provider_delivery_ref,
                        request=request,
                        settings_snapshot=_settings(ctx, row.provider_key),
                    )
                else:
                    delivery = await provider.create_delivery(
                        request=request,
                        settings_snapshot=_settings(ctx, row.provider_key),
                    )
            except ArchiveProviderError as exc:
                delivery = ProviderDelivery(status="unavailable", reason_code=exc.reason_code)
            except Exception as exc:  # noqa: BLE001 - provider payloads never cross the boundary
                del exc
                delivery = ProviderDelivery(status="unknown", reason_code="provider_unavailable")
            resolved.append((item_snapshot, delivery, link_expires_at, previous))

        links: list[ArchiveDeliveryLinkDTO] = []
        async with ctx.uow_factory() as uow:
            grant = await uow.session.get(ArchiveDownloadGrant, parsed_grant_id)
            if grant is None:
                raise _not_found("archive.grant_not_found", f"grant {grant_id}")
            if grant.status != "active" or _required_utc(grant.expires_at) <= ctx.clock.utc_now():
                raise _conflict("archive.grant_expired", "grant is no longer active")
            for item_snapshot, delivery, link_expires_at, previous in resolved:
                item_id = uuid.UUID(item_snapshot.item_id)
                current = await uow.session.get(ArchiveItem, item_id)
                if (
                    current is None
                    or current.version != item_snapshot.version
                    or current.state != "active"
                ):
                    raise _conflict(
                        "archive.manifest_mismatch", "grant item changed during delivery"
                    )
                status = _attempt_status(delivery)
                completed_at = ctx.clock.utc_now()
                attempt: ArchiveDeliveryAttempt | None = None
                if previous is not None and previous.provider_delivery_ref:
                    attempt = await uow.session.get(ArchiveDeliveryAttempt, previous.id)
                if attempt is None:
                    max_number = (
                        await uow.session.execute(
                            select(func.max(ArchiveDeliveryAttempt.attempt_number)).where(
                                ArchiveDeliveryAttempt.grant_id == parsed_grant_id,
                                ArchiveDeliveryAttempt.item_id == item_id,
                            )
                        )
                    ).scalar_one()
                    attempt = ArchiveDeliveryAttempt(
                        grant_id=parsed_grant_id,
                        item_id=item_id,
                        provider_key=current.provider_key,
                        attempt_number=int(max_number or 0) + 1,
                        started_at=completed_at,
                    )
                    uow.session.add(attempt)
                attempt.status = status
                attempt.reason_code = delivery.reason_code
                attempt.provider_delivery_ref = delivery.provider_delivery_ref
                attempt.link_expires_at = delivery.expires_at or link_expires_at
                attempt.completed_at = completed_at
                await uow.session.flush()
                links.append(
                    ArchiveDeliveryLinkDTO(
                        item_id=item_snapshot.item_id,
                        attempt_id=str(attempt.id),
                        status=delivery.status,
                        redirect_url=delivery.redirect_url,
                        proxy_ticket=delivery.proxy_ticket,
                        expires_at=delivery.expires_at or link_expires_at,
                        reason_code=delivery.reason_code,
                    )
                )
            await uow.commit()
            return ResolveDownloadLinksDTO(
                grant_id=str(grant.id),
                links=links,
                expires_at=min(
                    _required_utc(grant.expires_at),
                    ctx.clock.utc_now() + timedelta(seconds=DELIVERY_LINK_TTL_SECONDS),
                ),
            )


class ResolveDownloadLinksActivity:
    """Kernel workflow handler wrapper for the public delivery Activity."""

    def __init__(self, *, ctx: CommandContext) -> None:
        self._resolver = ResolveDownloadLinks(ctx)

    async def __call__(
        self, uow: UnitOfWork, data: dict[str, Any], activity_ctx: ActivityContext
    ) -> dict[str, Any]:
        del uow
        workflow = data.get("workflow", data)
        grant_id = workflow.get("grant_id")
        if grant_id is None:
            raise KernelError(
                code="archive.delivery_invalid_input",
                category=ErrorCategory.INTERNAL,
                message="delivery activity input is missing grant_id",
            )
        result = await self._resolver(grant_id)
        return result.model_dump(mode="json")


# Stable spelling used by workflow registration code.
ResolveDownloadLinksStep = ResolveDownloadLinksActivity

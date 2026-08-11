"""Administrator notification delivery queries and recovery commands."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Path, Query

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.notification.commands import (
    CancelPendingNotification,
    CommandContext,
    RetryDelivery,
)
from inc.capabilities.notification.schemas import (
    NotificationDeliveryDetailDTO,
    NotificationDeliveryDTO,
    NotificationDeliveryPageDTO,
)
from inc.kernel.errors import ErrorCategory, KernelError

REQUIRED_PERMISSIONS: tuple[str, ...] = (
    "notification.read",
    "notification.cancel",
    "notification.retry",
)


def _ctx(ctx: AppContext, services: Services) -> CommandContext:
    if services.notification_specs is None or services.notification_resolver is None:
        raise RuntimeError("notification router requires notification services")
    return CommandContext(
        uow_factory=ctx.uow_factory,
        clock=ctx.clock,
        outbox=services.outbox,
        specs=services.notification_specs,
        resolver=services.notification_resolver,
        providers=services.notification_providers,
        runner=services.runner,
        permissions=frozenset(ctx.principal.capabilities),
        actor_id=ctx.principal.subject_id,
        trace_id=ctx.trace_id,
    )


def _not_found(delivery_id: uuid.UUID) -> KernelError:
    return KernelError(
        code="notification.delivery_not_found",
        category=ErrorCategory.NOT_FOUND,
        message=f"delivery {delivery_id} was not found",
    )


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any = None,
) -> APIRouter:
    queries = services.notification_queries
    if queries is None:
        raise RuntimeError("notification router requires notification queries")
    router = APIRouter(
        prefix="/api/v1/admin/notifications",
        tags=["admin", "admin-notifications"],
    )

    @router.get("/deliveries", response_model=NotificationDeliveryPageDTO)
    async def list_deliveries(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        status: str | None = Query(default=None),
        channel: str | None = Query(default=None),
        provider_key: str | None = Query(default=None),
        spec_key: str | None = Query(default=None),
        recipient_id: str | None = Query(default=None),
        ctx: AppContext = Depends(require_capability("notification.read")),
    ) -> NotificationDeliveryPageDTO:
        return await queries.list_deliveries(
            page=page,
            size=size,
            status=status,
            channel=channel,
            provider_key=provider_key,
            spec_key=spec_key,
            recipient_id=recipient_id,
        )

    @router.get("/deliveries/{delivery_id}", response_model=NotificationDeliveryDetailDTO)
    async def get_delivery(
        delivery_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("notification.read")),
    ) -> NotificationDeliveryDetailDTO:
        found = await queries.get_delivery(delivery_id)
        if found is None:
            raise _not_found(delivery_id)
        return found

    @router.post("/deliveries/{delivery_id}/cancel", response_model=NotificationDeliveryDTO)
    async def cancel_delivery(
        delivery_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("notification.cancel")),
    ) -> NotificationDeliveryDTO:
        return await CancelPendingNotification(_ctx(ctx, services))(delivery_id)

    @router.post("/deliveries/{delivery_id}/retry", response_model=NotificationDeliveryDTO)
    async def retry_delivery(
        delivery_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("notification.retry")),
    ) -> NotificationDeliveryDTO:
        return await RetryDelivery(_ctx(ctx, services))(delivery_id)

    return router

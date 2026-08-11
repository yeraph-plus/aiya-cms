"""Payments webhook and admin refund endpoints.

Contract source: context/spec/http-openapi.md §8, capabilities/payments.md
§6, features.md §4.4.

The webhook endpoint verifies the raw bytes against the provider signature
before anything is parsed; verified facts are bridged into workflow
signals by the point_purchase feature. Duplicate receipts are deduped by
the payments command and never re-bridged.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Path, Query, Request

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.payments.commands import (
    CancelPaymentOrder,
    ProcessVerifiedWebhook,
    ReconcilePaymentOrder,
    RequestRefund,
)
from inc.capabilities.payments.commands import (
    CommandContext as PaymentsCommandContext,
)
from inc.capabilities.payments.schemas import (
    OrderDetailDTO,
    OrderDTO,
    OrderPageDTO,
    RefundDTO,
    RequestRefundInput,
)
from inc.features.membership_purchase.workflows import (
    BridgeContext as MembershipBridgeContext,
)
from inc.features.membership_purchase.workflows import (
    bridge_payment_event as bridge_membership_purchase,
)
from inc.features.point_purchase.schemas import WebhookReceiptDTO
from inc.features.point_purchase.workflows import (
    BridgeContext as PointPurchaseBridgeContext,
)
from inc.features.point_purchase.workflows import (
    bridge_payment_event as bridge_point_purchase,
)
from inc.kernel.errors import ErrorCategory, KernelError

REQUIRED_PERMISSIONS: tuple[str, ...] = (
    "payments.read",
    "payments.cancel",
    "payments.refund",
    "payments.reconcile",
)


def _payments_ctx(services: Services, request: Request) -> PaymentsCommandContext:
    return PaymentsCommandContext(
        uow_factory=services.uow_factory,
        clock=services.clock,
        outbox=services.outbox,
        providers=services.payment_providers,
        permissions=frozenset(),
        trace_id=getattr(request.state, "request_id", None),
    )


def _admin_payments_ctx(ctx: AppContext, services: Services) -> PaymentsCommandContext:
    return PaymentsCommandContext(
        uow_factory=ctx.uow_factory,
        clock=ctx.clock,
        outbox=services.outbox,
        providers=services.payment_providers,
        permissions=frozenset(ctx.principal.capabilities),
        actor_id=ctx.principal.subject_id,
        trace_id=ctx.trace_id,
    )


def _order_not_found(order_id: uuid.UUID) -> KernelError:
    return KernelError(
        code="payments.order_not_found",
        category=ErrorCategory.NOT_FOUND,
        message=f"payment order {order_id} was not found",
    )


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get(
        "/admin/payments/orders",
        response_model=OrderPageDTO,
        tags=["admin", "admin-payments"],
    )
    async def list_orders(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        state: str | None = Query(default=None),
        provider_key: str | None = Query(default=None),
        subject_type: str | None = Query(default=None),
        subject_id: str | None = Query(default=None),
        ctx: AppContext = Depends(require_capability("payments.read")),
    ) -> OrderPageDTO:
        return await services.payments_queries.list_orders(
            page=page,
            size=size,
            state=state,
            provider_key=provider_key,
            subject_type=subject_type,
            subject_id=subject_id,
        )

    @router.get(
        "/admin/payments/orders/{order_id}",
        response_model=OrderDetailDTO,
        tags=["admin", "admin-payments"],
    )
    async def get_order(
        order_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("payments.read")),
    ) -> OrderDetailDTO:
        detail = await services.payments_queries.get_order_detail(order_id)
        if detail is None:
            raise _order_not_found(order_id)
        return detail

    @router.post(
        "/admin/payments/orders/{order_id}/cancel",
        response_model=OrderDTO,
        tags=["admin", "admin-payments"],
    )
    async def cancel_order(
        order_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("payments.cancel")),
    ) -> OrderDTO:
        return await CancelPaymentOrder(_admin_payments_ctx(ctx, services))(order_id)

    @router.post(
        "/admin/payments/orders/{order_id}/reconcile",
        response_model=OrderDTO,
        tags=["admin", "admin-payments"],
    )
    async def reconcile_order(
        order_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("payments.reconcile")),
    ) -> OrderDTO:
        return await ReconcilePaymentOrder(_admin_payments_ctx(ctx, services))(order_id)

    @router.post(
        "/webhooks/payments/{provider_key}",
        response_model=WebhookReceiptDTO,
        tags=["webhooks"],
    )
    async def payment_webhook(provider_key: str, request: Request) -> WebhookReceiptDTO:
        secret = services.payment_webhook_secrets.get(provider_key)
        if secret is None:
            raise KernelError(
                code="payments.unknown_provider",
                category=ErrorCategory.VALIDATION,
                message=f"unknown provider {provider_key!r}",
            )
        raw_body = await request.body()
        headers = {k.lower(): v for k, v in request.headers.items()}
        result = await ProcessVerifiedWebhook(_payments_ctx(services, request))(
            provider_key=provider_key,
            raw_body=raw_body,
            headers=headers,
            secret=secret,
        )
        order_id = result.get("order_id")
        if order_id:
            # A capture fact may wake either purchase workflow; each bridge
            # ignores orders it does not own. This runs on the duplicate path
            # too, so a bridge that failed after the receipt committed can be
            # recovered by the provider retry (the duplicate receipt then
            # returns 200 without re-applying the payment fact).
            await bridge_point_purchase(
                PointPurchaseBridgeContext(
                    runner=services.runner,
                    payments_queries=services.payments_queries,
                ),
                order_id=order_id,
            )
            await bridge_membership_purchase(
                MembershipBridgeContext(
                    runner=services.runner,
                    payments_queries=services.payments_queries,
                ),
                order_id=order_id,
            )
        if result.get("duplicate"):
            return WebhookReceiptDTO(received=True, duplicate=True)
        return WebhookReceiptDTO(received=True, duplicate=False)

    @router.post(
        "/admin/payments/orders/{order_id}/refund",
        response_model=RefundDTO,
        tags=["admin", "admin-payments"],
    )
    async def request_refund(
        body: RequestRefundInput,
        order_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("payments.refund")),
    ) -> RefundDTO:
        return await RequestRefund(_admin_payments_ctx(ctx, services))(order_id, body)

    return router

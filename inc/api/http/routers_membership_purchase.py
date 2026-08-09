"""Membership purchase endpoints.

Contract source: context/spec/features.md (membership purchase),
http-openapi.md §6.

Prices come from the server-side trusted offer catalog; clients only
select an ``offer_key``. Starting a purchase requires an
``Idempotency-Key`` header; the workflow and the payment order share one
business idempotency key so provider webhooks can locate the waiting
workflow.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.points.commands import (
    CommandContext as PointsCommandContext,
)
from inc.capabilities.points.commands import (
    OpenPointsAccount,
)
from inc.features.membership_purchase.definition import MEMBERSHIP_OFFERS
from inc.features.membership_purchase.schemas import (
    MembershipOfferDTO,
    MembershipOfferListDTO,
    MembershipPurchaseOrderDTO,
)
from inc.features.membership_purchase.workflows import (
    PURCHASE_WORKFLOW_KEY,
    checkout_view,
    purchase_workflow_idempotency_key,
)
from inc.kernel.errors import ErrorCategory, KernelError


class PurchaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_key: str = Field(min_length=1, max_length=100)


REQUIRED_PERMISSIONS: tuple[str, ...] = ()


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["membership-purchase"])

    @router.get("/membership-purchase/offers", response_model=MembershipOfferListDTO)
    async def list_offers(
        ctx: AppContext = Depends(require_authenticated()),
    ) -> MembershipOfferListDTO:
        return MembershipOfferListDTO(
            items=[
                MembershipOfferDTO(
                    offer_key=offer.offer_key,
                    version=offer.version,
                    description=offer.description,
                    amount=offer.amount,
                    currency=offer.currency,
                    level_key=offer.level_key,
                )
                for offer in MEMBERSHIP_OFFERS.values()
            ]
        )

    @router.post("/membership-purchase/orders", response_model=MembershipPurchaseOrderDTO)
    async def start_purchase(
        body: PurchaseInput,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> MembershipPurchaseOrderDTO:
        if body.offer_key not in MEMBERSHIP_OFFERS:
            raise KernelError(
                code="membershippurchase.unknown_offer",
                category=ErrorCategory.VALIDATION,
                message=f"unknown offer {body.offer_key!r}",
            )
        if not services.payment_providers:
            raise KernelError(
                code="payments.unknown_provider",
                category=ErrorCategory.VALIDATION,
                message="no payment provider is bound",
            )
        provider_key = sorted(services.payment_providers)[0]
        subject_id = ctx.principal.subject_id
        await OpenPointsAccount(
            PointsCommandContext(
                uow_factory=ctx.uow_factory,
                clock=ctx.clock,
                outbox=services.outbox,
                behaviors=services.behaviors,
                permissions=frozenset(ctx.principal.capabilities),
                actor_id=subject_id,
                trace_id=ctx.trace_id,
            )
        )(program_key="default", subject_type="identity", subject_id=subject_id)

        # Namespace the client-supplied key with the authenticated subject so
        # two different users sharing an Idempotency-Key header cannot collide
        # on (or read each other's) workflows and orders.
        scoped_key = f"{subject_id}:{idempotency_key}"
        workflow_key = purchase_workflow_idempotency_key(scoped_key)
        instance = await services.runner.start(
            workflow_key=PURCHASE_WORKFLOW_KEY,
            idempotency_key=workflow_key,
            input_data={
                "subject_type": "identity",
                "subject_id": subject_id,
                "provider_key": provider_key,
                "offer_key": body.offer_key,
                "idempotency_key": scoped_key,
            },
            trace_id=ctx.trace_id,
        )
        stored = instance.input.data
        if (
            stored.get("subject_id") != subject_id
            or stored.get("offer_key") != body.offer_key
            or stored.get("provider_key") != provider_key
        ):
            # runner.start is idempotent by key and ignores input_data on
            # replay; a retry that changed the payload must not silently order
            # something different than what the client asked for.
            raise KernelError(
                code="membershippurchase.idempotency_conflict",
                category=ErrorCategory.CONFLICT,
                message="Idempotency-Key was already used with a different purchase payload",
            )
        if instance.status not in ("completed", "waiting"):
            status = await services.runner.advance(instance.id)
            if status not in ("waiting", "completed"):
                raise KernelError(
                    code="membershippurchase.purchase_failed",
                    category=ErrorCategory.INTERNAL,
                    message=f"purchase workflow ended in {status}",
                )
        fresh = await services.runner.find_by_business_key(
            workflow_key=PURCHASE_WORKFLOW_KEY, idempotency_key=workflow_key
        )
        view = checkout_view(fresh) if fresh is not None else None
        if view is None:
            raise KernelError(
                code="membershippurchase.purchase_failed",
                category=ErrorCategory.INTERNAL,
                message="purchase workflow produced no checkout view",
            )
        order = await services.payments_queries.get_order_by_reference(view["order_reference"])
        if order is None:
            # A completed/waiting workflow that produced an order reference
            # must have an order; masking it as "pending" hides a data-integrity
            # anomaly and can hang the client forever.
            raise KernelError(
                code="membershippurchase.order_missing",
                category=ErrorCategory.INTERNAL,
                message="payment order missing for a purchase workflow",
            )
        return MembershipPurchaseOrderDTO(
            order_reference=view["order_reference"],
            checkout_url=view["checkout_url"],
            state=order.state,
        )

    return router

"""Application boundary for business-center HTTP adapters."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict

from inc.features.business_center.domain import (
    BusinessPrincipal,
    BusinessQuote,
    QuoteBusinessProduct,
    QuoteRequest,
    QuoteTokenCodec,
)
from inc.features.business_center.workflows import (
    COMPENSATE_ACTIVITY_KEY,
    CONSUME_WORKFLOW_KEY,
    DEBIT_ACTIVITY_KEY,
    FULFILL_ACTIVITY_KEY,
    consumption_idempotency_key,
)
from inc.kernel.db import UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.workflow import WorkflowInstance, WorkflowRepository, WorkflowRunner


class ConsumptionDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_id: str
    status: Literal["pending_debit", "fulfillment_pending", "fulfilled", "reversed", "failed"]
    points_entry_ref: str | None = None
    fulfillment_ref: str | None = None
    reversal_entry_ref: str | None = None


@dataclass(frozen=True, slots=True)
class BusinessCenterService:
    quote_service: QuoteBusinessProduct
    token_codec: QuoteTokenCodec
    runner: WorkflowRunner
    uow_factory: UoWFactory

    async def quote(self, request: QuoteRequest, *, principal: BusinessPrincipal) -> BusinessQuote:
        return await self.quote_service(request, principal=principal)

    async def consume(
        self,
        *,
        quote_token: str,
        idempotency_key: str,
        principal: BusinessPrincipal,
        trace_id: str | None = None,
    ) -> ConsumptionDTO:
        if not idempotency_key or len(idempotency_key) > 200:
            raise KernelError(
                code="business_center.invalid_idempotency_key",
                category=ErrorCategory.VALIDATION,
                message="Idempotency-Key is required",
            )
        claims = self.token_codec.decode(quote_token)
        key = consumption_idempotency_key(
            subject=principal.subject,
            quote_id=claims.quote_id,
            request_key=idempotency_key,
        )
        instance = await self.runner.start(
            workflow_key=CONSUME_WORKFLOW_KEY,
            idempotency_key=key,
            input_data={
                "quote_token": quote_token,
                "principal": principal.model_dump(mode="json"),
                "consumption_key": key,
                "compensation_policy_version": claims.compensation_policy_version,
            },
            trace_id=trace_id,
        )
        if instance.status not in {"completed", "failed", "cancelled"}:
            await self.runner.advance(instance.id)
            instance = await self._get(instance.id)
        return _to_consumption(instance)

    async def get(self, workflow_id: str, *, principal: BusinessPrincipal) -> ConsumptionDTO:
        try:
            instance_id = uuid.UUID(workflow_id)
        except ValueError as exc:
            raise KernelError(
                code="business_center.consumption_not_found",
                category=ErrorCategory.NOT_FOUND,
                message="consumption was not found",
            ) from exc
        instance = await self._get(instance_id)
        workflow = instance.input.data
        bound = BusinessPrincipal.model_validate(workflow.get("principal", {}))
        if bound.subject != principal.subject or bound.client_id != principal.client_id:
            raise KernelError(
                code="business_center.consumption_forbidden",
                category=ErrorCategory.FORBIDDEN,
                message="consumption belongs to another subject or client",
            )
        return _to_consumption(instance)

    async def _get(self, instance_id: uuid.UUID) -> WorkflowInstance:
        async with self.uow_factory() as uow:
            instance = await WorkflowRepository(uow).get_instance(instance_id)
            if instance is None or instance.workflow_key != CONSUME_WORKFLOW_KEY:
                raise KernelError(
                    code="business_center.consumption_not_found",
                    category=ErrorCategory.NOT_FOUND,
                    message="consumption was not found",
                )
            return instance
        raise AssertionError("unreachable: workflow lookup completed")


def _to_consumption(instance: WorkflowInstance) -> ConsumptionDTO:
    state = instance.state.data
    debit = state.get(DEBIT_ACTIVITY_KEY, {})
    fulfill = state.get(FULFILL_ACTIVITY_KEY, {})
    compensation = state.get(COMPENSATE_ACTIVITY_KEY, {})
    if compensation.get("status") == "reversed":
        status = "reversed"
    elif fulfill.get("status") == "fulfilled":
        status = "fulfilled"
    elif instance.status in {"failed", "cancelled"}:
        status = "failed"
    elif debit.get("points_entry_ref"):
        status = "fulfillment_pending"
    else:
        status = "pending_debit"
    return ConsumptionDTO(
        workflow_id=str(instance.id),
        status=cast(
            Literal["pending_debit", "fulfillment_pending", "fulfilled", "reversed", "failed"],
            status,
        ),
        points_entry_ref=debit.get("points_entry_ref"),
        fulfillment_ref=fulfill.get("fulfillment_ref"),
        reversal_entry_ref=compensation.get("reversal_entry_ref"),
    )


__all__ = ["BusinessCenterService", "ConsumptionDTO"]

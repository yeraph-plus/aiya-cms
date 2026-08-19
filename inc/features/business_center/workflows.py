"""Persistent business consumption workflow.

Every external effect has a stable idempotency key.  This is important even
though the kernel persists completed activity results: a process can stop
after a capability commits and before the workflow step commit.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from inc.capabilities.archive import (
    ActivateDownloadGrant,
    ArchiveCommandContext,
    IssueDownloadGrant,
    IssueDownloadGrantInput,
)
from inc.capabilities.points import (
    CommandContext as PointsCommandContext,
)
from inc.capabilities.points import (
    CreditDebitInput,
    DebitPoints,
    ReverseInput,
    ReverseLedgerEntry,
)
from inc.features.business_center.domain import (
    DEBIT_BEHAVIOR_KEY,
    PROGRAM_KEY,
    ArchiveFulfillment,
    BusinessPrincipal,
    BusinessProductRegistry,
    CostBasisPort,
    FulfillmentTemporarilyUnavailable,
    QuoteClaims,
    QuoteTokenCodec,
    _authorize,
    _price,
    _stale,
    _utc,
)
from inc.kernel.db import UnitOfWork
from inc.kernel.errors import ErrorCategory, KernelError, RetryCategory
from inc.kernel.workflow import ActivityContext, ActivitySpec, RetryPolicy, WorkflowSpec

CONSUME_WORKFLOW_KEY = "business_center.consume.v1"
VALIDATE_ACTIVITY_KEY = "business_center.consume.validate.v1"
DEBIT_ACTIVITY_KEY = "business_center.consume.debit.v1"
FULFILL_ACTIVITY_KEY = "business_center.consume.fulfill.v1"
COMPENSATE_ACTIVITY_KEY = "business_center.consume.compensate.v1"


@dataclass(frozen=True, slots=True)
class BusinessCenterWorkflowContext:
    products: BusinessProductRegistry
    cost_basis: CostBasisPort
    token_codec: QuoteTokenCodec
    points_ctx: PointsCommandContext
    archive_ctx: ArchiveCommandContext
    grant_ttl: timedelta = timedelta(minutes=30)
    fulfillment_terminal_attempts: int = 5


def consumption_idempotency_key(*, subject: str, quote_id: str, request_key: str) -> str:
    value = f"{subject}\0{quote_id}\0{request_key}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _workflow(data: dict[str, Any]) -> dict[str, Any]:
    value = data.get("workflow", data)
    return dict(value)


def _state(data: dict[str, Any]) -> dict[str, Any]:
    return dict(data.get("state", {}))


async def _fresh_claims(
    ctx: BusinessCenterWorkflowContext, workflow: dict[str, Any]
) -> QuoteClaims:
    claims = ctx.token_codec.decode(workflow["quote_token"])
    product = ctx.products.require(claims.product_key)
    principal = BusinessPrincipal.model_validate(workflow["principal"])
    _authorize(product, principal, action_scope="business.consume")
    if (
        claims.subject != principal.subject
        or claims.client_id != principal.client_id
        or claims.audience != principal.audience
    ):
        raise KernelError(
            code="business_center.invalid_quote",
            category=ErrorCategory.FORBIDDEN,
            message="quote is bound to another subject or client",
        )
    if (
        _utc(ctx.points_ctx.clock.utc_now()) >= _utc(claims.expires_at)
        or claims.product_version != product.version
        or claims.pricing_policy_key != product.pricing_policy_key
        or claims.compensation_policy_version != product.compensation_policy_version
        or claims.program_key != PROGRAM_KEY
    ):
        raise _stale()
    parameters = product.request_schema.model_validate(claims.parameters)
    basis = product.cost_basis_schema.model_validate(
        await ctx.cost_basis.resolve(
            product=product, target_ref=claims.target_ref, parameters=parameters
        )
    )
    if getattr(basis, "target_ref", claims.target_ref) != claims.target_ref:
        raise _stale()
    current = _price(product.pricing_policy_key, basis)
    if current.target_digest != claims.target_digest or current.amount != claims.amount:
        raise _stale()
    return claims


def build_consume_workflow_spec(*, ctx: BusinessCenterWorkflowContext) -> WorkflowSpec:
    if ctx.fulfillment_terminal_attempts < 1:
        raise ValueError("fulfillment_terminal_attempts must be positive")

    async def validate(
        uow: UnitOfWork, data: dict[str, Any], activity_ctx: ActivityContext
    ) -> dict[str, Any]:
        del uow, activity_ctx
        claims = await _fresh_claims(ctx, _workflow(data))
        return {"claims": claims.model_dump(mode="json")}

    async def debit(
        uow: UnitOfWork, data: dict[str, Any], activity_ctx: ActivityContext
    ) -> dict[str, Any]:
        del uow, activity_ctx
        workflow = _workflow(data)
        claims = QuoteClaims.model_validate(_state(data)[VALIDATE_ACTIVITY_KEY]["claims"])
        key = workflow["consumption_key"]
        try:
            entry = await DebitPoints(ctx.points_ctx)(
                DEBIT_BEHAVIOR_KEY,
                CreditDebitInput(
                    subject_type="identity",
                    subject_id=claims.subject,
                    amount=claims.amount,
                    source_type="business_center",
                    source_id=claims.quote_id,
                    idempotency_key=f"{key}:debit",
                    actor_type="user",
                    actor_id=claims.subject,
                    metadata={
                        "product_key": claims.product_key,
                        "quote_id": claims.quote_id,
                        "client_id": claims.client_id,
                    },
                ),
            )
        except KernelError as exc:
            if exc.code == "points.insufficient_balance":
                raise KernelError(
                    code="business_center.insufficient_balance",
                    category=ErrorCategory.CONFLICT,
                    message="insufficient credit balance",
                ) from exc
            raise
        return {"points_entry_ref": entry.id}

    async def fulfill(
        uow: UnitOfWork, data: dict[str, Any], activity_ctx: ActivityContext
    ) -> dict[str, Any]:
        del uow
        workflow = _workflow(data)
        state = _state(data)
        claims = QuoteClaims.model_validate(state[VALIDATE_ACTIVITY_KEY]["claims"])
        payload = ArchiveFulfillment.model_validate(claims.fulfillment)
        entry_ref = state[DEBIT_ACTIVITY_KEY]["points_entry_ref"]
        try:
            grant = await IssueDownloadGrant(ctx.archive_ctx)(
                IssueDownloadGrantInput(
                    subject_type="identity",
                    subject_id=claims.subject,
                    product_ref=claims.product_key,
                    quote_ref=claims.quote_id,
                    points_entry_ref=entry_ref,
                    target_type="work",
                    target_id=payload.target_ref,
                    item_ids=payload.file_ids,
                    manifest_version=payload.manifest_version,
                    expires_at=ctx.points_ctx.clock.utc_now() + ctx.grant_ttl,
                    idempotency_key=f"{workflow['consumption_key']}:fulfill",
                    business_consumption_ref=workflow["consumption_key"],
                )
            )
            if getattr(grant, "status", "active") != "active":
                grant = await ActivateDownloadGrant(ctx.archive_ctx)(grant.id)
        except FulfillmentTemporarilyUnavailable:
            if activity_ctx.attempt < ctx.fulfillment_terminal_attempts:
                raise
            return {"status": "terminal_failure", "reason": "temporarily_unavailable"}
        except KernelError as exc:
            if exc.category == ErrorCategory.DEPENDENCY_UNAVAILABLE:
                if activity_ctx.attempt < ctx.fulfillment_terminal_attempts:
                    raise
                return {"status": "terminal_failure", "reason": exc.code}
            if exc.category in {
                ErrorCategory.VALIDATION,
                ErrorCategory.CONFLICT,
                ErrorCategory.NOT_FOUND,
                ErrorCategory.FORBIDDEN,
            }:
                return {"status": "terminal_failure", "reason": exc.code}
            raise
        return {"status": "fulfilled", "fulfillment_ref": grant.id}

    async def compensate(
        uow: UnitOfWork, data: dict[str, Any], activity_ctx: ActivityContext
    ) -> dict[str, Any]:
        del uow, activity_ctx
        workflow = _workflow(data)
        state = _state(data)
        fulfillment = state[FULFILL_ACTIVITY_KEY]
        if fulfillment["status"] == "fulfilled":
            return {"status": "not_required"}
        entry_ref = state[DEBIT_ACTIVITY_KEY]["points_entry_ref"]
        reversal = await ReverseLedgerEntry(ctx.points_ctx)(
            entry_ref,
            ReverseInput(
                reason=(
                    "business_center fulfillment terminated "
                    f"under compensation policy {workflow['compensation_policy_version']}"
                ),
                idempotency_key=f"{workflow['consumption_key']}:reverse",
            ),
        )
        return {"status": "reversed", "reversal_entry_ref": reversal.id}

    retry = RetryPolicy(
        max_attempts=ctx.fulfillment_terminal_attempts,
        base_delay_seconds=1,
        max_delay_seconds=60,
        jitter_seconds=0,
        permanent_categories=frozenset({RetryCategory.PERMANENT, RetryCategory.CANCELLED}),
    )
    return WorkflowSpec(
        key=CONSUME_WORKFLOW_KEY,
        version="1",
        activities=(
            ActivitySpec(key=VALIDATE_ACTIVITY_KEY, handler=validate),
            ActivitySpec(key=DEBIT_ACTIVITY_KEY, handler=debit),
            ActivitySpec(key=FULFILL_ACTIVITY_KEY, handler=fulfill, retry=retry),
            ActivitySpec(key=COMPENSATE_ACTIVITY_KEY, handler=compensate),
        ),
    )


__all__ = [
    "BusinessCenterWorkflowContext",
    "COMPENSATE_ACTIVITY_KEY",
    "CONSUME_WORKFLOW_KEY",
    "DEBIT_ACTIVITY_KEY",
    "FULFILL_ACTIVITY_KEY",
    "VALIDATE_ACTIVITY_KEY",
    "build_consume_workflow_spec",
    "consumption_idempotency_key",
]

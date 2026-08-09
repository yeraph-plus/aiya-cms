"""Payments commands.

Contract source: context/spec/capabilities/payments.md §6/§7.

Order state transitions are monotonic; only a verified webhook or a
trusted server-side status query moves an order to captured/refunded.
Webhook receipts are idempotent by (provider, event_id). The captured
event commits atomically with the order state.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from inc.capabilities.payments.models import (
    OfferSnapshot,
    PaymentAttempt,
    PaymentOrder,
    PaymentRefund,
    PaymentWebhookReceipt,
    RequestDigestData,
)
from inc.capabilities.payments.ports import (
    PaymentProvider,
    ProviderError,
    WebhookEvent,
    WebhookVerificationError,
)
from inc.capabilities.payments.schemas import (
    PAYMENT_EVENT_SCHEMAS,
    CreatePaymentOrderInput,
    OrderDTO,
    RefundDTO,
    RequestRefundInput,
    StartAttemptResult,
)
from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock

ORDER_TTL_SECONDS = 30 * 60

PERMISSION_CREATE = "payments.create"
PERMISSION_CANCEL = "payments.cancel"
PERMISSION_REFUND = "payments.refund"
PERMISSION_RECONCILE = "payments.reconcile"

ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "created": ("pending", "cancelled", "failed"),
    "pending": ("captured", "cancelled", "failed"),
    "captured": ("partially_refunded", "refunded"),
    "partially_refunded": ("refunded",),
    "refunded": (),
    "cancelled": (),
    "failed": (),
}


@dataclass(frozen=True, slots=True)
class CommandContext:
    uow_factory: UoWFactory
    clock: Clock
    outbox: OutboxWriter
    providers: dict[str, PaymentProvider]
    permissions: frozenset[str] = frozenset()
    actor_id: str | None = None
    trace_id: str | None = None


def _forbidden(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.FORBIDDEN, message=message)


def _conflict(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.CONFLICT, message=message)


def _validation(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.VALIDATION, message=message)


def _not_found(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.NOT_FOUND, message=message)


def _require_permission(ctx: CommandContext, key: str) -> None:
    if key not in ctx.permissions:
        raise _forbidden("payments.forbidden", f"requires permission {key}")


def _ensure_utc(value: Any) -> Any:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _provider(ctx: CommandContext, provider_key: str) -> PaymentProvider:
    provider = ctx.providers.get(provider_key)
    if provider is None:
        raise _validation(
            "payments.unknown_provider", f"provider {provider_key!r} is not configured"
        )
    return provider


async def _emit(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    key: str,
    order: PaymentOrder,
    **values: Any,
) -> None:
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=key,
            occurred_at=ctx.clock.utc_now(),
            producer="payments",
            aggregate_type="payments",
            aggregate_id=str(order.id),
            trace_id=ctx.trace_id,
            payload=PAYMENT_EVENT_SCHEMAS[key]
            .model_validate(
                {
                    "order_id": str(order.id),
                    "order_reference": order.order_reference,
                    "subject_type": order.subject_type,
                    "subject_id": order.subject_id,
                    "amount": order.amount,
                    "currency": order.currency,
                    **values,
                }
            )
            .model_dump(mode="json"),
        ),
    )


def _to_order(row: PaymentOrder) -> OrderDTO:
    return OrderDTO(
        id=str(row.id),
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        provider_key=row.provider_key,
        order_reference=row.order_reference,
        idempotency_key=row.idempotency_key,
        offer_key=row.offer.offer_key,
        offer_version=row.offer.offer_version,
        description=row.offer.description,
        amount=row.amount,
        currency=row.currency,
        state=row.state,
        captured_amount=row.captured_amount,
        refunded_amount=row.refunded_amount,
        created_at=_ensure_utc(row.created_at),
    )


def _to_refund(row: PaymentRefund) -> RefundDTO:
    return RefundDTO(
        id=str(row.id),
        order_id=str(row.order_id),
        refund_ref=row.refund_ref,
        amount=row.amount,
        currency=row.currency,
        state=row.state,
        reason=row.reason,
    )


def _transition(order: PaymentOrder, target: str) -> None:
    if target not in ALLOWED_TRANSITIONS.get(order.state, ()):
        raise _conflict(
            "payments.invalid_transition",
            f"cannot move order from {order.state!r} to {target!r}",
        )


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class CreatePaymentOrder:
    """Create (or return) an order; idempotent by (provider, key)."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: CreatePaymentOrderInput) -> OrderDTO:  # type: ignore[return]
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_CREATE)
        _provider(ctx, input_.provider_key)
        async with ctx.uow_factory() as uow:
            existing = await _find_by_idempotency(uow, input_.provider_key, input_.idempotency_key)
            if existing is not None:
                return _to_order(existing)
            order = PaymentOrder(
                subject_type=input_.subject_type,
                subject_id=input_.subject_id,
                provider_key=input_.provider_key,
                order_reference=_new_reference(),
                offer=OfferSnapshot(
                    offer_key=input_.offer_key,
                    offer_version=input_.offer_version,
                    description=input_.description,
                ),
                amount=input_.amount,
                currency=input_.currency,
                state="created",
                idempotency_key=input_.idempotency_key,
                expires_at=ctx.clock.utc_now() + timedelta(seconds=ORDER_TTL_SECONDS),
            )
            uow.session.add(order)
            try:
                await uow.session.flush()
            except IntegrityError as exc:
                raise _conflict(
                    "payments.duplicate_order", "an order with this idempotency key exists"
                ) from exc
            await _emit(
                ctx,
                uow,
                key="payment.order_created.v1",
                order=order,
                provider_key=order.provider_key,
                offer_key=order.offer.offer_key,
            )
            await uow.commit()
            return _to_order(order)


async def _find_by_idempotency(
    uow: UnitOfWork, provider_key: str, idempotency_key: str
) -> PaymentOrder | None:
    row: PaymentOrder | None = (
        (
            await uow.session.execute(
                select(PaymentOrder).where(
                    PaymentOrder.provider_key == provider_key,
                    PaymentOrder.idempotency_key == idempotency_key,
                )
            )
        )
        .scalars()
        .first()
    )
    return row


def _new_reference() -> str:
    return f"ord_{secrets.token_urlsafe(18)}"


class StartPaymentAttempt:
    """Create a provider session; the order becomes pending.

    Replay-safe: if the order is already ``pending`` with a provider
    reference (previous attempt persisted, step crashed before commit of
    the attempt record), the existing session is reused instead of
    contacting the provider again.
    """

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, order_id: Any) -> StartAttemptResult:
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_CREATE)
        async with ctx.uow_factory() as read_uow:
            order: PaymentOrder | None = await read_uow.session.get(PaymentOrder, order_id)
        if order is None:
            raise _not_found("payments.order_not_found", f"order {order_id}")
        provider = _provider(ctx, order.provider_key)
        if _ensure_utc(order.expires_at) < ctx.clock.utc_now():
            raise _conflict("payments.order_expired", "order expired")
        if order.state == "pending" and order.provider_ref:
            return StartAttemptResult(
                order=_to_order(order),
                checkout_url="",
                requires_action=False,
            )
        try:
            session = await provider.create_payment(
                order_reference=order.order_reference,
                amount=order.amount,
                currency=order.currency,
                idempotency_key=f"order:{order.id}",
                return_url="",
                cancel_url="",
            )
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - adapter errors normalize upstream
            raise ProviderError(message=str(exc)) from exc
        async with ctx.uow_factory() as uow:
            order = await uow.session.get(PaymentOrder, order_id)
            if order is None:
                raise _not_found("payments.order_not_found", f"order {order_id}")
            _transition(order, "pending")
            order.state = "pending"
            order.provider_ref = session.provider_ref
            uow.session.add(
                PaymentAttempt(
                    order_id=order.id,
                    provider_ref=session.provider_ref,
                    attempt=1,
                    state="pending",
                    request_digest=RequestDigestData(values={"digest": _digest(b"")}),
                )
            )
            await _emit(
                ctx,
                uow,
                key="payment.pending.v1",
                order=order,
                provider_ref=session.provider_ref,
            )
            await uow.commit()
        return StartAttemptResult(
            order=_to_order(order),
            checkout_url=session.url,
            requires_action=session.requires_action,
        )


async def _find_latest_attempt(  # type: ignore[return]
    ctx: CommandContext, order_id: Any
) -> PaymentAttempt | None:
    async with ctx.uow_factory() as uow:
        row: PaymentAttempt | None = (
            (
                await uow.session.execute(
                    select(PaymentAttempt)
                    .where(PaymentAttempt.order_id == order_id)
                    .order_by(PaymentAttempt.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        return row


class CancelPaymentOrder:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, order_id: Any) -> OrderDTO:  # type: ignore[return]
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_CANCEL)
        async with ctx.uow_factory() as uow:
            order: PaymentOrder | None = await uow.session.get(PaymentOrder, order_id)
            if order is None:
                raise _not_found("payments.order_not_found", f"order {order_id}")
            _transition(order, "cancelled")
            order.state = "cancelled"
            order.cancelled_at = ctx.clock.utc_now()
            await _emit(ctx, uow, key="payment.cancelled.v1", order=order)
            await uow.commit()
            return _to_order(order)


class ProcessVerifiedWebhook:
    """Verify raw bytes, dedupe by (provider, event_id), then apply."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, *, provider_key: str, raw_body: bytes, headers: dict[str, str], secret: str
    ) -> dict[str, Any]:
        ctx = self._ctx
        provider = _provider(ctx, provider_key)
        try:
            event: WebhookEvent = await provider.verify_webhook(
                raw_body=raw_body, headers=headers, secret=secret
            )
        except WebhookVerificationError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider errors normalize upstream
            raise WebhookVerificationError(f"verification failed: {type(exc).__name__}") from exc
        digest = _digest(raw_body)
        async with ctx.uow_factory() as uow:
            receipt: PaymentWebhookReceipt | None = (
                (
                    await uow.session.execute(
                        select(PaymentWebhookReceipt).where(
                            PaymentWebhookReceipt.provider_key == provider_key,
                            PaymentWebhookReceipt.event_id == event.event_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if receipt is not None:
                return {
                    "duplicate": True,
                    "event_id": event.event_id,
                    "order_id": str(receipt.order_id) if receipt.order_id is not None else None,
                }

            order = (
                (
                    await uow.session.execute(
                        select(PaymentOrder)
                        .where(
                            PaymentOrder.order_reference == event.order_reference,
                            PaymentOrder.provider_key == provider_key,
                        )
                        .with_for_update()
                    )
                )
                .scalars()
                .first()
            )

            receipt = PaymentWebhookReceipt(
                provider_key=provider_key,
                event_id=event.event_id,
                payload_digest=digest,
                verified_at=ctx.clock.utc_now(),
                processing_state="verified",
                failure_reason=None,
                order_id=order.id if order is not None else None,
            )
            uow.session.add(receipt)
            try:
                await uow.session.flush()
            except IntegrityError:
                uow.session.rollback()
                async with ctx.uow_factory() as again:
                    existing: PaymentWebhookReceipt | None = (
                        (
                            await again.session.execute(
                                select(PaymentWebhookReceipt).where(
                                    PaymentWebhookReceipt.provider_key == provider_key,
                                    PaymentWebhookReceipt.event_id == event.event_id,
                                )
                            )
                        )
                        .scalars()
                        .first()
                    )
                if existing is not None:
                    return {
                        "duplicate": True,
                        "event_id": event.event_id,
                        "order_id": (
                            str(existing.order_id) if existing.order_id is not None else None
                        ),
                    }
                raise

            if order is None:
                receipt.processing_state = "rejected"
                receipt.failure_reason = "unknown order"
                await uow.commit()
                raise _conflict(
                    "payments.unknown_order",
                    f"no order for reference {event.order_reference!r}",
                )
            if order.amount != event.amount or order.currency != event.currency:
                receipt.processing_state = "rejected"
                receipt.failure_reason = "amount/currency mismatch"
                await uow.commit()
                raise _conflict(
                    "payments.amount_mismatch",
                    "webhook amount/currency does not match the order",
                )

            try:
                if event.event_type == "capture":
                    _transition(order, "captured")
                    order.state = "captured"
                    order.captured_amount = event.amount
                    order.captured_at = ctx.clock.utc_now()
                    await _emit(
                        ctx,
                        uow,
                        key="payment.captured.v1",
                        order=order,
                        provider_ref=order.provider_ref or "",
                    )
                elif event.event_type == "failure":
                    _transition(order, "failed")
                    order.state = "failed"
                    order.failed_at = ctx.clock.utc_now()
                    await _emit(ctx, uow, key="payment.failed.v1", order=order)
                elif event.event_type == "refund":
                    await _apply_refund_event(ctx, uow, order=order, event=event)
                else:
                    raise WebhookVerificationError(f"unsupported event type {event.event_type!r}")
            except WebhookVerificationError:
                receipt.processing_state = "rejected"
                receipt.failure_reason = f"unsupported event type {event.event_type!r}"
                await uow.commit()
                raise
            except KernelError:
                receipt.processing_state = "rejected"
                receipt.failure_reason = f"invalid transition: {event.event_type}"
                await uow.commit()
                raise
            await uow.commit()
            return {"duplicate": False, "event_id": event.event_id, "order_id": str(order.id)}


async def _apply_refund_event(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    order: PaymentOrder,
    event: WebhookEvent,
) -> None:
    """A provider refund webhook completes the matching pending refund.

    The refund is matched by (order, amount) against the still-pending
    local record; a mismatch rejects the event without guessing.
    """
    if order.state not in ("captured", "partially_refunded"):
        raise _conflict(
            "payments.invalid_transition",
            f"cannot apply refund to order in {order.state!r}",
        )
    pending = (
        (
            await uow.session.execute(
                select(PaymentRefund)
                .where(
                    PaymentRefund.order_id == order.id,
                    PaymentRefund.state == "pending",
                )
                .order_by(PaymentRefund.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    candidate = next((r for r in pending if r.amount == event.amount), None)
    if candidate is None:
        raise _conflict(
            "payments.refund_mismatch",
            f"no pending refund for amount {event.amount} on order {order.order_reference}",
        )
    candidate.state = "completed"
    candidate.completed_at = ctx.clock.utc_now()
    order.refunded_amount += candidate.amount
    target = "refunded" if order.refunded_amount >= order.captured_amount else "partially_refunded"
    if target != order.state:
        _transition(order, target)
        order.state = target
    await _emit(
        ctx,
        uow,
        key="payment.refund_completed.v1",
        order=order,
        refund_ref=candidate.refund_ref,
        refund_amount=candidate.amount,
    )


class ReconcilePaymentOrder:
    """Trusted server-side status query corrects stale orders."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, order_id: Any) -> OrderDTO:  # type: ignore[return]
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_RECONCILE)
        async with ctx.uow_factory() as read_uow:
            order: PaymentOrder | None = await read_uow.session.get(PaymentOrder, order_id)
        if order is None:
            raise _not_found("payments.order_not_found", f"order {order_id}")
        if order.state in ("captured", "refunded", "cancelled", "failed"):
            return _to_order(order)
        provider = _provider(ctx, order.provider_key)
        try:
            status = await provider.get_payment(provider_ref=order.provider_ref or "")
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(message=str(exc)) from exc
        async with ctx.uow_factory() as uow:
            order = await uow.session.get(PaymentOrder, order_id)
            if order is None:
                raise _not_found("payments.order_not_found", f"order {order_id}")
            if status.state == "captured":
                _transition(order, "captured")
                order.state = "captured"
                order.captured_amount = status.captured_amount or order.amount
                order.captured_at = ctx.clock.utc_now()
                await _emit(
                    ctx,
                    uow,
                    key="payment.captured.v1",
                    order=order,
                    provider_ref=order.provider_ref or "",
                )
            elif status.state == "failed":
                _transition(order, "failed")
                order.state = "failed"
                order.failed_at = ctx.clock.utc_now()
                await _emit(ctx, uow, key="payment.failed.v1", order=order)
            elif status.state == "unknown":
                return _to_order(order)  # stays pending; do not guess
            await uow.commit()
            return _to_order(order)


class RequestRefund:
    """Request a provider refund; idempotent by (order, key)."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, order_id: Any, input_: RequestRefundInput
    ) -> RefundDTO:
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_REFUND)
        async with ctx.uow_factory() as read_uow:
            order: PaymentOrder | None = await read_uow.session.get(PaymentOrder, order_id)
        if order is None:
            raise _not_found("payments.order_not_found", f"order {order_id}")
        if order.state not in ("captured", "partially_refunded", "refunded"):
            raise _conflict("payments.not_refundable", f"order is {order.state}")
        # idempotency check happens before the amount guard so a repeated
        # request returns the original refund instead of a false refusal
        async with ctx.uow_factory() as uow:
            existing: PaymentRefund | None = (
                (
                    await uow.session.execute(
                        select(PaymentRefund).where(
                            PaymentRefund.order_id == order.id,
                            PaymentRefund.idempotency_key == input_.idempotency_key,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                return _to_refund(existing)
        if order.refunded_amount + input_.amount > order.captured_amount:
            raise _validation(
                "payments.refund_exceeds_captured",
                "refund would exceed the captured amount",
            )
        provider = _provider(ctx, order.provider_key)
        try:
            provider_refund = await provider.create_refund(
                payment_ref=order.provider_ref or "",
                amount=input_.amount,
                currency=order.currency,
                idempotency_key=f"refund:{order.id}:{input_.idempotency_key}",
                reason=input_.reason,
            )
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(message=str(exc)) from exc
        async with ctx.uow_factory() as uow:
            order = (
                (
                    await uow.session.execute(
                        select(PaymentOrder).where(PaymentOrder.id == order_id).with_for_update()
                    )
                )
                .scalars()
                .first()
            )
            if order is None:
                raise _not_found("payments.order_not_found", f"order {order_id}")
            if order.refunded_amount + input_.amount > order.captured_amount:
                raise _validation(
                    "payments.refund_exceeds_captured",
                    "refund would exceed the captured amount",
                )
            refund = PaymentRefund(
                order_id=order.id,
                refund_ref=provider_refund.refund_ref,
                amount=input_.amount,
                currency=order.currency,
                state=provider_refund.state,
                idempotency_key=input_.idempotency_key,
                reason=input_.reason,
            )
            uow.session.add(refund)
            try:
                await uow.session.flush()
            except IntegrityError as exc:
                raise _conflict(
                    "payments.duplicate_refund", "a refund with this key exists"
                ) from exc
            if provider_refund.state == "completed":
                order.refunded_amount += input_.amount
                target = (
                    "refunded"
                    if order.refunded_amount >= order.captured_amount
                    else "partially_refunded"
                )
                _transition(order, target)
                order.state = target
                refund.completed_at = ctx.clock.utc_now()
                refund.state = "completed"
                await _emit(
                    ctx,
                    uow,
                    key="payment.refund_completed.v1",
                    order=order,
                    refund_ref=refund.refund_ref,
                    refund_amount=refund.amount,
                )
            await uow.commit()
            return _to_refund(refund)

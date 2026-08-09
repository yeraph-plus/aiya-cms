"""Payments DTOs, events and command inputs.

Contract source: context/spec/capabilities/payments.md §6/§8.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from inc.kernel.errors import validate_error_code


class OrderDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    subject_type: str
    subject_id: str
    provider_key: str
    order_reference: str
    idempotency_key: str
    offer_key: str
    offer_version: str
    description: str
    amount: int
    currency: str
    state: str
    captured_amount: int
    refunded_amount: int
    created_at: datetime


class CreatePaymentOrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: str
    subject_id: str
    provider_key: str
    offer_key: str
    offer_version: str
    description: str = Field(max_length=500)
    amount: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=8)
    idempotency_key: str = Field(min_length=1, max_length=200)
    return_url: str | None = None
    cancel_url: str | None = None


class StartAttemptResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: OrderDTO
    checkout_url: str
    requires_action: bool = False


class RequestRefundInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=200)


class RefundDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    order_id: str
    refund_ref: str
    amount: int
    currency: str
    state: str
    reason: str


# events -------------------------------------------------------------


class _EventBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str
    order_reference: str
    subject_type: str
    subject_id: str
    amount: int
    currency: str


class OrderCreatedPayload(_EventBase):
    provider_key: str
    offer_key: str


class PendingPayload(_EventBase):
    provider_ref: str


class CapturedPayload(_EventBase):
    provider_ref: str


class FailedPayload(_EventBase):
    reason: str | None = None


class CancelledPayload(_EventBase):
    pass


class RefundCompletedPayload(_EventBase):
    refund_ref: str
    refund_amount: int


PAYMENT_EVENT_SCHEMAS: dict[str, type[BaseModel]] = {
    "payment.order_created.v1": OrderCreatedPayload,
    "payment.pending.v1": PendingPayload,
    "payment.captured.v1": CapturedPayload,
    "payment.failed.v1": FailedPayload,
    "payment.cancelled.v1": CancelledPayload,
    "payment.refund_completed.v1": RefundCompletedPayload,
}

for _key in PAYMENT_EVENT_SCHEMAS:
    validate_error_code(_key)

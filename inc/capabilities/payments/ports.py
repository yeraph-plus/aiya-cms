"""Payments Ports.

Contract source: context/spec/capabilities/payments.md §5.

PaymentProvider is implemented by adapters that own SDKs, credentials,
signature algorithms and error normalization. Provider-specific payloads
never enter business DTOs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from inc.kernel.errors import ErrorCategory, KernelError, RetryCategory


@dataclass(frozen=True, slots=True)
class ProviderSession:
    provider_ref: str
    url: str
    requires_action: bool = False


@dataclass(frozen=True, slots=True)
class PaymentStatus:
    state: str  # captured | failed | pending | unknown
    captured_amount: int | None = None
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    event_id: str
    event_type: str  # capture | failure | refund
    order_reference: str
    amount: int
    currency: str


@dataclass(frozen=True, slots=True)
class ProviderRefund:
    refund_ref: str
    state: str  # completed | pending | failed


class ProviderError(KernelError):
    """Provider failure classified for reconciliation."""

    def __init__(
        self,
        *,
        message: str,
        category: ErrorCategory = ErrorCategory.DEPENDENCY_UNAVAILABLE,
        permanent: bool = False,
    ) -> None:
        super().__init__(code="payments.provider_error", category=category, message=message)
        self.permanent = permanent

    @property
    def retry_category(self) -> RetryCategory:
        if self.permanent:
            return RetryCategory.PERMANENT
        if self.category == ErrorCategory.RATE_LIMITED:
            return RetryCategory.RATE_LIMITED
        return RetryCategory.TRANSIENT


class WebhookVerificationError(KernelError):
    """Signature, freshness or format failure; never treated as success."""

    def __init__(self, message: str) -> None:
        super().__init__(
            code="payments.webhook_invalid",
            category=ErrorCategory.VALIDATION,
            message=message,
        )


class PaymentProvider(Protocol):
    """External payment SDK contract."""

    key: str

    async def create_payment(
        self,
        *,
        order_reference: str,
        amount: int,
        currency: str,
        idempotency_key: str,
        return_url: str,
        cancel_url: str,
    ) -> ProviderSession: ...

    async def get_payment(self, *, provider_ref: str) -> PaymentStatus: ...

    async def verify_webhook(
        self, *, raw_body: bytes, headers: dict[str, str], secret: str
    ) -> WebhookEvent: ...

    async def create_refund(
        self,
        *,
        payment_ref: str,
        amount: int,
        currency: str,
        idempotency_key: str,
        reason: str,
    ) -> ProviderRefund: ...

    async def get_refund(self, *, refund_ref: str) -> ProviderRefund: ...

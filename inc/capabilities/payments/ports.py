"""Payments Ports.

Contract source: context/spec/capabilities/payments.md §5.

PaymentProvider is implemented by adapters that own SDKs, credentials,
signature algorithms and error normalization. Provider-specific payloads
never enter business DTOs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from inc.kernel.errors import ErrorCategory, KernelError, RetryCategory

CNY: Literal["CNY"] = "CNY"


@dataclass(frozen=True, slots=True)
class ProviderSession:
    provider_ref: str
    redirect_url: str | None = None
    qr_code_payload: str | None = None
    app_url: str | None = None
    requires_action: bool = False

    def __post_init__(self) -> None:
        if not any((self.redirect_url, self.qr_code_payload, self.app_url)):
            raise ValueError("payment provider session requires an action target")

    @property
    def url(self) -> str:
        """Legacy caller convenience; new callers use the explicit target fields."""

        return self.redirect_url or self.app_url or self.qr_code_payload or ""


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
    acknowledgement: str | None = None


@dataclass(frozen=True, slots=True)
class WebhookRequest:
    """Transport-neutral callback input; providers decide which fields matter."""

    method: str
    raw_body: bytes
    headers: dict[str, str]
    query_params: dict[str, str]


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
        code: str = "payments.provider_error",
        category: ErrorCategory = ErrorCategory.DEPENDENCY_UNAVAILABLE,
        permanent: bool = False,
    ) -> None:
        super().__init__(code=code, category=category, message=message)
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

    async def check_availability(self) -> tuple[bool, str | None]: ...

    async def create_payment(
        self,
        *,
        order_reference: str,
        amount: int,
        currency: str,
        idempotency_key: str,
        return_url: str,
        cancel_url: str,
        notify_url: str = "",
        description: str = "",
        client_ip: str = "",
    ) -> ProviderSession: ...

    async def get_payment(self, *, provider_ref: str) -> PaymentStatus: ...

    async def verify_webhook(self, *, request: WebhookRequest) -> WebhookEvent: ...

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

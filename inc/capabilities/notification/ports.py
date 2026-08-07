"""Notification Ports.

Contract source: context/spec/capabilities/notification.md §4.

The RecipientResolver Port is bound by the composition root (identity or
contact-book adapter); NotificationProvider is implemented by Email/SMS
adapters. Provider results are normalized so the activity never parses
SDK-specific payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from inc.kernel.errors import ErrorCategory, KernelError, RetryCategory


@dataclass(frozen=True, slots=True)
class RecipientTarget:
    channel: str
    address: str
    masked_address: str


class RecipientResolver(Protocol):
    """Resolves the live address for a recipient ref and channel."""

    async def resolve(
        self, recipient_type: str, recipient_id: str, channel: str
    ) -> RecipientTarget | None: ...


@dataclass(frozen=True, slots=True)
class ProviderResult:
    status: str  # delivered | failed | unknown
    provider_ref: str | None = None
    error_category: str | None = None
    error_summary: str | None = None


class ProviderError(KernelError):
    """Provider failure classified for the delivery state machine."""

    def __init__(
        self,
        *,
        message: str,
        category: ErrorCategory = ErrorCategory.DEPENDENCY_UNAVAILABLE,
        permanent: bool = False,
    ) -> None:
        super().__init__(
            code="notification.provider_error",
            category=category,
            message=message,
        )
        self.permanent = permanent

    @property
    def retry_category(self) -> RetryCategory:
        if self.permanent:
            return RetryCategory.PERMANENT
        if self.category == ErrorCategory.RATE_LIMITED:
            return RetryCategory.RATE_LIMITED
        return RetryCategory.TRANSIENT


class NotificationProvider(Protocol):
    """Sends one rendered delivery; idempotency key passed through."""

    key: str

    async def send(
        self,
        *,
        target: RecipientTarget,
        subject: str,
        body: str,
        idempotency_key: str,
    ) -> ProviderResult: ...


def timeout_result(provider_ref: str | None = None) -> ProviderResult:
    """Provider outcome is unknown after a timeout; never assume sent."""

    return ProviderResult(
        status="unknown",
        provider_ref=provider_ref,
        error_category="timeout",
        error_summary="provider timeout; outcome unknown",
    )

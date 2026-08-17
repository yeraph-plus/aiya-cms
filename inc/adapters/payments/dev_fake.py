"""Development fake payment provider (key ``payments.dev_fake``).

Contract source: context/spec/adapters.md §3.2, capabilities/payments.md §5/§6.

Deterministic in-memory provider for dev/test closed loops: checkout
sessions live in process memory, webhooks are HMAC-SHA256 signed with the
public module test secret, and ``build_event``/``sign_webhook`` helpers let
tests and local tooling drive capture/failure/refund events. Production
manifests must never bind this adapter (``kernel.adapter_production_denied``);
the test secret is not a real credential.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import Any

from inc.capabilities.payments.ports import (
    PaymentStatus,
    ProviderRefund,
    ProviderSession,
    WebhookEvent,
    WebhookVerificationError,
)

DEV_FAKE_WEBHOOK_SECRET = "dev-fake-webhook-secret"

_EVENT_TYPES = ("capture", "failure", "refund")


def sign_webhook(body: bytes, secret: str = DEV_FAKE_WEBHOOK_SECRET) -> str:
    """HMAC-SHA256 hex signature carried in the ``X-Signature`` header."""

    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def build_event(
    *,
    event_id: str,
    event_type: str,
    order_reference: str,
    amount: int,
    currency: str = "CNY",
) -> bytes:
    """Construct a raw webhook body (dev/test tooling)."""

    if event_type not in _EVENT_TYPES:
        raise ValueError(f"unknown dev_fake event type {event_type!r}")
    return json.dumps(
        {
            "id": event_id,
            "type": event_type,
            "order_reference": order_reference,
            "amount": amount,
            "currency": currency,
        }
    ).encode()


class DevFakePaymentProvider:
    """In-memory provider; every call is deterministic and side-effect free."""

    key = "dev_fake"

    @property
    def webhook_secret(self) -> str:
        return DEV_FAKE_WEBHOOK_SECRET

    def __init__(self) -> None:
        self._statuses: dict[str, str] = {}
        self._refunds: dict[str, str] = {}

    async def create_payment(
        self,
        *,
        order_reference: str,
        amount: int,
        currency: str,
        idempotency_key: str,
        return_url: str,
        cancel_url: str,
    ) -> ProviderSession:
        provider_ref = f"devpay_{uuid.uuid4().hex[:12]}"
        self._statuses[provider_ref] = "pending"
        return ProviderSession(
            provider_ref=provider_ref,
            url=f"https://pay.dev-fake.local/checkout/{provider_ref}",
        )

    async def get_payment(self, *, provider_ref: str) -> PaymentStatus:
        return PaymentStatus(state=self._statuses.get(provider_ref, "pending"))

    async def verify_webhook(
        self, *, raw_body: bytes, headers: dict[str, str], secret: str
    ) -> WebhookEvent:
        signature = headers.get("X-Signature") or headers.get("x-signature") or ""
        if not hmac.compare_digest(signature, sign_webhook(raw_body, secret)):
            raise WebhookVerificationError("bad signature")
        try:
            payload: dict[str, Any] = json.loads(raw_body)
            event_type = str(payload["type"])
            if event_type not in _EVENT_TYPES:
                raise ValueError(event_type)
            return WebhookEvent(
                event_id=str(payload["id"]),
                event_type=event_type,
                order_reference=str(payload["order_reference"]),
                amount=int(payload["amount"]),
                currency=str(payload["currency"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise WebhookVerificationError(f"malformed payload: {type(exc).__name__}") from exc

    async def create_refund(
        self,
        *,
        payment_ref: str,
        amount: int,
        currency: str,
        idempotency_key: str,
        reason: str,
    ) -> ProviderRefund:
        refund_ref = f"devref_{uuid.uuid4().hex[:12]}"
        self._refunds[refund_ref] = "pending"
        return ProviderRefund(refund_ref=refund_ref, state="pending")

    async def get_refund(self, *, refund_ref: str) -> ProviderRefund:
        return ProviderRefund(refund_ref=refund_ref, state=self._refunds.get(refund_ref, "pending"))

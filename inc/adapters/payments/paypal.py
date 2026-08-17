"""PayPal Orders v2 adapter.

The adapter is the only module that knows the PayPal Server SDK, OAuth
credentials, minor-unit conversion and webhook verification endpoint. The
capability receives only the frozen ``PaymentProvider`` DTOs.

The SDK client is created lazily and all synchronous SDK/HTTP calls run in a
worker thread so payment activity never blocks the async event loop.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

import requests

from inc.capabilities.payments.ports import (
    CNY,
    PaymentStatus,
    ProviderError,
    ProviderRefund,
    ProviderSession,
    WebhookEvent,
    WebhookRequest,
    WebhookVerificationError,
)
from inc.kernel.errors import ErrorCategory

_SANDBOX_API = "https://api-m.sandbox.paypal.com"
_PRODUCTION_API = "https://api-m.paypal.com"
_WEBHOOK_MAX_AGE_SECONDS = 10 * 60


@dataclass(frozen=True, slots=True)
class PaypalConfig:
    """Validated provider configuration; secrets never appear in repr output."""

    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    webhook_id: str = field(repr=False)
    environment: Literal["sandbox", "production"] = "sandbox"
    return_url: str | None = None
    cancel_url: str | None = None
    timeout_seconds: float = 30.0

    @property
    def api_base_url(self) -> str:
        return _PRODUCTION_API if self.environment == "production" else _SANDBOX_API


class PaypalPaymentProvider:
    """PayPal implementation of the payments ``PaymentProvider`` Port."""

    key = "paypal"

    def __init__(
        self,
        config: PaypalConfig | None = None,
        *,
        settings_queries: Any | None = None,
        client: Any | None = None,
    ) -> None:
        self._config = config or PaypalConfig(client_id="", client_secret="", webhook_id="")
        self._settings_queries = settings_queries
        self._client_instance = client

    async def _configure(self) -> None:
        """Read the selected provider configuration at call time, never at boot."""

        if self._settings_queries is None:
            return
        group = await self._settings_queries.get_group("payments")
        values = group.values
        secret = values.get("paypal_client_secret")
        getter = getattr(secret, "get_secret_value", None)
        config = PaypalConfig(
            client_id=str(values.get("paypal_client_id") or "").strip(),
            client_secret=str(getter() if getter is not None else secret or "").strip(),
            webhook_id=str(values.get("paypal_webhook_id") or "").strip(),
            environment=(
                "production"
                if str(values.get("paypal_environment") or "sandbox") == "production"
                else "sandbox"
            ),
        )
        if config != self._config:
            self._config = config
            self._client_instance = None
        missing = [
            name
            for name, value in (
                ("paypal_client_id", config.client_id),
                ("paypal_client_secret", config.client_secret),
                ("paypal_webhook_id", config.webhook_id),
            )
            if not value
        ]
        if missing:
            raise ProviderError(
                code="payments.provider_unavailable",
                message="PayPal is unavailable because required settings are missing",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                permanent=True,
            )

    async def check_availability(self) -> tuple[bool, str | None]:
        """Validate the selected settings without leaking configuration values."""

        try:
            await self._configure()
        except ProviderError as exc:
            return False, exc.code
        return True, None

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
    ) -> ProviderSession:
        del notify_url, description, client_ip
        await self._configure()
        _require_cny(currency)
        client = self._require_client()
        from paypalserversdk.models.amount_with_breakdown import (  # type: ignore[import-untyped]
            AmountWithBreakdown,
        )
        from paypalserversdk.models.checkout_payment_intent import (  # type: ignore[import-untyped]
            CheckoutPaymentIntent,
        )
        from paypalserversdk.models.order_application_context import (  # type: ignore[import-untyped]
            OrderApplicationContext,
        )
        from paypalserversdk.models.order_request import (  # type: ignore[import-untyped]
            OrderRequest,
        )
        from paypalserversdk.models.purchase_unit_request import (  # type: ignore[import-untyped]
            PurchaseUnitRequest,
        )

        effective_return_url = return_url or self._config.return_url
        effective_cancel_url = cancel_url or self._config.cancel_url
        if not effective_return_url or not effective_cancel_url:
            raise ProviderError(
                message="PayPal return and cancel URLs are not configured",
                category=ErrorCategory.INTERNAL,
                permanent=True,
            )
        request = OrderRequest(
            intent=CheckoutPaymentIntent.CAPTURE,
            purchase_units=[
                PurchaseUnitRequest(
                    reference_id=order_reference,
                    custom_id=order_reference,
                    amount=AmountWithBreakdown(
                        currency_code=currency.upper(),
                        value=_minor_to_major(amount, currency),
                    ),
                )
            ],
            application_context=OrderApplicationContext(
                return_url=effective_return_url,
                cancel_url=effective_cancel_url,
            ),
        )
        response = await self._call(
            client.orders.create_order,
            {
                "body": request,
                "paypal_request_id": idempotency_key,
                "prefer": "return=representation",
            },
        )
        body = _response_body(response)
        provider_ref = _text(body, "id")
        approval_url = _approval_url(body)
        if not provider_ref or not approval_url:
            raise ProviderError(
                message="PayPal create order returned no approval link",
                category=ErrorCategory.INTERNAL,
                permanent=True,
            )
        return ProviderSession(
            provider_ref=provider_ref, redirect_url=approval_url, requires_action=True
        )

    async def get_payment(self, *, provider_ref: str) -> PaymentStatus:
        await self._configure()
        client = self._require_client()
        response = await self._call(client.orders.get_order, {"id": provider_ref})
        body = _response_body(response)
        state = _order_state(_text(body, "status"))
        captured_amount, currency = _captured_amount(body)
        return PaymentStatus(state=state, captured_amount=captured_amount, currency=currency)

    async def verify_webhook(self, *, request: WebhookRequest) -> WebhookEvent:
        """Verify a PayPal transmission using the official verification endpoint."""

        await self._configure()
        raw_body, headers, secret = request.raw_body, request.headers, self._config.webhook_id

        try:
            payload = json.loads(raw_body)
        except (TypeError, ValueError) as exc:
            raise WebhookVerificationError("malformed PayPal webhook body") from exc
        if not isinstance(payload, dict):
            raise WebhookVerificationError("malformed PayPal webhook body")

        normalized = {key.lower(): value for key, value in headers.items()}
        required = {
            "paypal-transmission-id": normalized.get("paypal-transmission-id"),
            "paypal-transmission-time": normalized.get("paypal-transmission-time"),
            "paypal-cert-url": normalized.get("paypal-cert-url"),
            "paypal-auth-algo": normalized.get("paypal-auth-algo"),
            "paypal-transmission-sig": normalized.get("paypal-transmission-sig"),
        }
        if any(not isinstance(value, str) or not value for value in required.values()):
            raise WebhookVerificationError("missing PayPal transmission headers")
        transmission_time = required["paypal-transmission-time"]
        if not isinstance(transmission_time, str) or not _timestamp_is_fresh(transmission_time):
            raise WebhookVerificationError("stale PayPal webhook transmission")
        if not secret:
            raise WebhookVerificationError("PayPal webhook id is not configured")

        client = self._require_client_for_webhook()
        try:
            token = await asyncio.to_thread(client.oauth_2.fetch_token)
            access_token = _text(token, "access_token")
            if not access_token:
                raise WebhookVerificationError("PayPal OAuth token was not returned")
            response = await asyncio.to_thread(
                requests.post,
                f"{self._config.api_base_url}/v1/notifications/verify-webhook-signature",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "transmission_id": required["paypal-transmission-id"],
                    "transmission_time": required["paypal-transmission-time"],
                    "cert_url": required["paypal-cert-url"],
                    "auth_algo": required["paypal-auth-algo"],
                    "transmission_sig": required["paypal-transmission-sig"],
                    "webhook_id": secret,
                    "webhook_event": payload,
                },
                timeout=self._config.timeout_seconds,
            )
            if response.status_code >= 400:
                raise WebhookVerificationError("PayPal webhook verification request failed")
            result = response.json()
        except WebhookVerificationError:
            raise
        except (requests.RequestException, ValueError, TypeError) as exc:
            raise WebhookVerificationError("PayPal webhook verification unavailable") from exc
        if result.get("verification_status") != "SUCCESS":
            raise WebhookVerificationError("PayPal webhook signature rejected")
        return _webhook_event(payload)

    async def create_refund(
        self,
        *,
        payment_ref: str,
        amount: int,
        currency: str,
        idempotency_key: str,
        reason: str,
    ) -> ProviderRefund:
        await self._configure()
        _require_cny(currency)
        client = self._require_client()
        capture_ref = await self._resolve_capture_ref(client, payment_ref)
        from paypalserversdk.models.money import Money  # type: ignore[import-untyped]
        from paypalserversdk.models.refund_request import (  # type: ignore[import-untyped]
            RefundRequest,
        )

        response = await self._call(
            client.payments.refund_captured_payment,
            {
                "capture_id": capture_ref,
                "body": RefundRequest(
                    amount=Money(
                        currency_code=currency.upper(),
                        value=_minor_to_major(amount, currency),
                    ),
                    note_to_payer=reason,
                ),
                "paypal_request_id": idempotency_key,
                "prefer": "return=representation",
            },
        )
        return _refund_result(_response_body(response), fallback_state="pending")

    async def get_refund(self, *, refund_ref: str) -> ProviderRefund:
        await self._configure()
        client = self._require_client()
        response = await self._call(client.payments.get_refund, {"refund_id": refund_ref})
        return _refund_result(_response_body(response), fallback_state="pending")

    def _require_client(self) -> Any:
        if not self._config.client_id or not self._config.client_secret:
            raise ProviderError(
                code="payments.provider_unavailable",
                message="PayPal credentials are not configured",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                permanent=True,
            )
        if self._client_instance is None:
            from paypalserversdk.configuration import Environment  # type: ignore[import-untyped]
            from paypalserversdk.http.auth.o_auth_2 import (  # type: ignore[import-untyped]
                ClientCredentialsAuthCredentials,
            )
            from paypalserversdk.paypal_serversdk_client import (  # type: ignore[import-untyped]
                PaypalServersdkClient,
            )

            self._client_instance = PaypalServersdkClient(
                environment=(
                    Environment.PRODUCTION
                    if self._config.environment == "production"
                    else Environment.SANDBOX
                ),
                client_credentials_auth_credentials=ClientCredentialsAuthCredentials(
                    o_auth_client_id=self._config.client_id,
                    o_auth_client_secret=self._config.client_secret,
                ),
                timeout=self._config.timeout_seconds,
                max_retries=0,
            )
        return self._client_instance

    def _require_client_for_webhook(self) -> Any:
        try:
            return self._require_client()
        except ProviderError as exc:
            raise WebhookVerificationError("PayPal credentials are not configured") from exc

    async def _resolve_capture_ref(self, client: Any, payment_ref: str) -> str:
        try:
            response = await self._call(client.orders.get_order, {"id": payment_ref})
            body = _response_body(response)
            for unit in _items(body, "purchase_units"):
                payments = _value(unit, "payments")
                for capture in _items(payments, "captures"):
                    capture_id = _text(capture, "id")
                    if capture_id and _text(capture, "status") in {"COMPLETED", "PENDING"}:
                        return capture_id
        except ProviderError:
            # A caller may already have supplied a capture id. Let the
            # refund endpoint validate it instead of masking that valid form
            # behind an order lookup failure.
            return payment_ref
        except Exception:
            # The command Port historically stores the provider order id. If a
            # caller already supplied a capture id, PayPal accepts it directly.
            pass
        return payment_ref

    async def _call(self, operation: Any, options: dict[str, Any]) -> Any:
        try:
            response = await asyncio.to_thread(operation, options)
            _ensure_success(response)
            return response
        except ProviderError:
            raise
        except Exception as exc:  # SDK errors are normalized at this boundary.
            raise ProviderError(
                code="payments.provider_unavailable",
                message=f"PayPal request failed: {type(exc).__name__}",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
            ) from exc


def _minor_to_major(amount: int, currency: str) -> str:
    _require_cny(currency)
    if amount <= 0:
        raise ProviderError(
            message="payment amount must be positive",
            category=ErrorCategory.VALIDATION,
            permanent=True,
        )
    value = Decimal(amount) / Decimal(100)
    return f"{value:.2f}"


def _major_to_minor(value: Any, currency: str) -> int:
    if currency.upper() != CNY:
        raise WebhookVerificationError("payments only support CNY")
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise WebhookVerificationError("invalid PayPal amount") from exc
    scaled = (numeric * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if scaled <= 0:
        raise WebhookVerificationError("PayPal amount must be positive")
    return int(scaled)


def _require_cny(currency: str) -> None:
    if currency.upper() != CNY:
        raise ProviderError(
            code="payments.currency_unsupported",
            message="payments only support CNY",
            category=ErrorCategory.VALIDATION,
            permanent=True,
        )


def _ensure_success(response: Any) -> None:
    is_success = getattr(response, "is_success", None)
    if callable(is_success) and not is_success():
        status = getattr(response, "status_code", "unknown")
        category = (
            ErrorCategory.RATE_LIMITED if status == 429 else ErrorCategory.DEPENDENCY_UNAVAILABLE
        )
        raise ProviderError(message=f"PayPal returned HTTP {status}", category=category)


def _response_body(response: Any) -> Any:
    body = getattr(response, "body", None)
    if body is None:
        raise ProviderError(
            message="PayPal returned an empty response",
            category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
        )
    return body


def _value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _text(value: Any, name: str) -> str:
    found = _value(value, name)
    return str(found) if found is not None else ""


def _items(value: Any, name: str) -> list[Any]:
    found = _value(value, name)
    return list(found) if isinstance(found, (list, tuple)) else []


def _approval_url(order: Any) -> str:
    for link in _items(order, "links"):
        if _text(link, "rel").lower() in {"approve", "payer-action"}:
            href = _text(link, "href")
            if href:
                return href
    return ""


def _order_state(status: str) -> str:
    return {
        "COMPLETED": "captured",
        "APPROVED": "pending",
        "CREATED": "pending",
        "SAVED": "pending",
        "PAYER_ACTION_REQUIRED": "pending",
        "VOIDED": "failed",
    }.get(status.upper(), "unknown")


def _captured_amount(order: Any) -> tuple[int | None, str | None]:
    for unit in _items(order, "purchase_units"):
        payments = _value(unit, "payments")
        for capture in _items(payments, "captures"):
            if _text(capture, "status").upper() != "COMPLETED":
                continue
            amount = _value(capture, "amount")
            currency = _text(amount, "currency_code")
            try:
                return _major_to_minor(_value(amount, "value"), currency), currency
            except WebhookVerificationError:
                return None, currency or None
    return None, None


def _refund_result(body: Any, *, fallback_state: str) -> ProviderRefund:
    refund_ref = _text(body, "id")
    if not refund_ref:
        raise ProviderError(
            message="PayPal returned no refund id",
            category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
        )
    status = _text(body, "status").upper()
    state = {"COMPLETED": "completed", "FAILED": "failed", "CANCELLED": "failed"}.get(
        status, fallback_state
    )
    return ProviderRefund(refund_ref=refund_ref, state=state)


def _timestamp_is_fresh(value: str) -> bool:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            return False
        return abs(time.time() - timestamp.astimezone(UTC).timestamp()) <= _WEBHOOK_MAX_AGE_SECONDS
    except ValueError:
        return False


def _webhook_event(payload: dict[str, Any]) -> WebhookEvent:
    raw_type = str(payload.get("event_type", ""))
    event_type = {
        "PAYMENT.CAPTURE.COMPLETED": "capture",
        "PAYMENT.CAPTURE.REFUNDED": "refund",
        "PAYMENT.CAPTURE.DENIED": "failure",
        "PAYMENT.CAPTURE.DECLINED": "failure",
    }.get(raw_type)
    if event_type is None:
        raise WebhookVerificationError(f"unsupported PayPal event {raw_type!r}")
    resource = payload.get("resource")
    if not isinstance(resource, dict):
        raise WebhookVerificationError("PayPal webhook resource is missing")
    supplementary = resource.get("supplementary_data")
    related = supplementary.get("related_ids", {}) if isinstance(supplementary, dict) else {}
    order_reference = (
        related.get("order_id") or resource.get("custom_id") or resource.get("invoice_id")
    )
    breakdown = resource.get("seller_payable_breakdown")
    amount = resource.get("amount") or (
        breakdown.get("total_refunded_amount") if isinstance(breakdown, dict) else None
    )
    if not isinstance(order_reference, str) or not order_reference:
        raise WebhookVerificationError("PayPal webhook has no order reference")
    if not isinstance(amount, dict):
        raise WebhookVerificationError("PayPal webhook has no amount")
    currency = amount.get("currency_code")
    if not isinstance(currency, str) or not currency:
        raise WebhookVerificationError("PayPal webhook has no currency")
    event_id = payload.get("id")
    if not isinstance(event_id, str) or not event_id:
        raise WebhookVerificationError("PayPal webhook has no event id")
    return WebhookEvent(
        event_id=event_id,
        event_type=event_type,
        order_reference=order_reference,
        amount=_major_to_minor(amount.get("value"), currency),
        currency=currency,
    )


__all__ = ["PaypalConfig", "PaypalPaymentProvider"]

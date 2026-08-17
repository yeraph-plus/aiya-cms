"""LemPay-compatible Epay adapter.

The adapter follows the documented ``mapi.php`` and ``api.php`` protocol:
form-encoded order/refund requests, JSON responses, and a lower-case MD5
signature over sorted non-empty parameters plus the merchant key.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin, urlparse

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

_SETTINGS_GROUP = "payments"
_TIMEOUT_SECONDS = 20


@dataclass(frozen=True, slots=True)
class EpayConfig:
    gateway_url: str
    merchant_id: str = field(repr=False)
    merchant_key: str = field(repr=False)
    payment_type: str

    @classmethod
    def from_values(cls, values: dict[str, Any]) -> EpayConfig:
        gateway_url = str(values.get("epay_gateway_url") or "").strip().rstrip("/")
        merchant_id = str(values.get("epay_merchant_id") or "").strip()
        secret = values.get("epay_merchant_key")
        getter = getattr(secret, "get_secret_value", None)
        merchant_key = str(getter() if getter is not None else secret or "").strip()
        payment_type = str(values.get("epay_payment_type") or "").strip()
        parsed = urlparse(gateway_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or not merchant_id
            or not merchant_key
            or not payment_type
        ):
            raise ValueError("missing or invalid Epay settings")
        return cls(
            gateway_url=gateway_url,
            merchant_id=merchant_id,
            merchant_key=merchant_key,
            payment_type=payment_type,
        )


def sign_parameters(values: dict[str, Any], merchant_key: str) -> str:
    """LemPay's exact MD5 canonicalization, intentionally before URL encoding."""

    fragments = [
        f"{key}={values[key]}"
        for key in sorted(values)
        if key not in {"sign", "sign_type"} and values[key] not in (None, False, 0, "", "0")
    ]
    return hashlib.md5(("&".join(fragments) + merchant_key).encode("utf-8")).hexdigest()


class EpayPaymentProvider:
    """Settings-backed payment Port implementation; construction performs no I/O."""

    key = "epay"

    def __init__(self, *, settings_queries: Any, timeout_seconds: int = _TIMEOUT_SECONDS) -> None:
        self._settings_queries = settings_queries
        self._timeout_seconds = timeout_seconds

    async def check_availability(self) -> tuple[bool, str | None]:
        try:
            await self._config()
        except ProviderError as exc:
            return False, exc.code
        return True, None

    async def _config(self) -> EpayConfig:
        try:
            group = await self._settings_queries.get_group(_SETTINGS_GROUP)
            return EpayConfig.from_values(group.values)
        except Exception as exc:  # settings must never leak configuration detail to a caller
            raise ProviderError(
                code="payments.provider_unavailable",
                message="Epay is unavailable because required settings are missing",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                permanent=True,
            ) from exc

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await asyncio.to_thread(
                requests.request,
                method,
                url,
                params=params,
                data=data,
                timeout=self._timeout_seconds,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            result = response.json()
        except (requests.RequestException, ValueError, TypeError) as exc:
            raise ProviderError(
                code="payments.provider_unavailable",
                message="Epay gateway is unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
            ) from exc
        if not isinstance(result, dict):
            raise ProviderError(
                code="payments.provider_unavailable",
                message="Epay returned an invalid response",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
            )
        return result

    @staticmethod
    def _signed(values: dict[str, Any], config: EpayConfig) -> dict[str, str]:
        signed = {key: str(value) for key, value in values.items() if value is not None}
        signed["sign"] = sign_parameters(signed, config.merchant_key)
        signed["sign_type"] = "MD5"
        return signed

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
        del idempotency_key, cancel_url
        config = await self._config()
        _require_cny(currency)
        if not notify_url or not return_url or not description:
            raise ProviderError(
                code="payments.provider_unavailable",
                message="Epay requires notify URL, return URL and order description",
                category=ErrorCategory.VALIDATION,
                permanent=True,
            )
        values = self._signed(
            {
                "pid": config.merchant_id,
                "type": config.payment_type,
                "out_trade_no": order_reference,
                "notify_url": notify_url,
                "return_url": return_url,
                "name": description,
                "money": _fen_to_money(amount),
                "clientip": client_ip or "127.0.0.1",
            },
            config,
        )
        result = await self._request(
            "POST", urljoin(f"{config.gateway_url}/", "mapi.php"), data=values
        )
        if str(result.get("code")) != "1":
            raise ProviderError(
                message="Epay rejected the payment order",
                category=ErrorCategory.VALIDATION,
                permanent=True,
            )
        provider_ref = str(result.get("trade_no") or "").strip()
        redirect_url = _text(result.get("payurl"))
        qr_code_payload = _text(result.get("qrcode"))
        app_url = _text(result.get("urlscheme"))
        if not provider_ref:
            raise ProviderError(message="Epay response has no trade number", permanent=True)
        try:
            return ProviderSession(
                provider_ref=provider_ref,
                redirect_url=redirect_url or None,
                qr_code_payload=qr_code_payload or None,
                app_url=app_url or None,
                requires_action=True,
            )
        except ValueError as exc:
            raise ProviderError(
                message="Epay response has no payment action", permanent=True
            ) from exc

    async def get_payment(self, *, provider_ref: str) -> PaymentStatus:
        config = await self._config()
        values = self._signed(
            {"act": "order", "pid": config.merchant_id, "trade_no": provider_ref}, config
        )
        result = await self._request(
            "GET", urljoin(f"{config.gateway_url}/", "api.php"), params=values
        )
        if str(result.get("code")) != "1":
            return PaymentStatus(state="unknown", currency=CNY)
        status = str(result.get("trade_status") or "").upper()
        state = "captured" if status == "TRADE_SUCCESS" else "pending"
        amount = _money_to_fen(result.get("money")) if result.get("money") is not None else None
        return PaymentStatus(state=state, captured_amount=amount, currency=CNY)

    async def verify_webhook(self, *, request: WebhookRequest) -> WebhookEvent:
        config = await self._config()
        if request.method.upper() != "GET":
            raise WebhookVerificationError("Epay webhook must use GET")
        values = request.query_params
        supplied = values.get("sign")
        if not supplied or supplied.lower() != sign_parameters(values, config.merchant_key):
            raise WebhookVerificationError("Epay webhook signature rejected")
        if values.get("pid") != config.merchant_id or values.get("trade_status") != "TRADE_SUCCESS":
            raise WebhookVerificationError("Epay webhook is not a successful payment")
        trade_no = _text(values.get("trade_no"))
        order_reference = _text(values.get("out_trade_no"))
        if not trade_no or not order_reference:
            raise WebhookVerificationError("Epay webhook lacks order references")
        return WebhookEvent(
            event_id=f"{trade_no}:TRADE_SUCCESS",
            event_type="capture",
            order_reference=order_reference,
            amount=_money_to_fen(values.get("money")),
            currency=CNY,
            acknowledgement="success",
        )

    async def create_refund(
        self,
        *,
        payment_ref: str,
        amount: int,
        currency: str,
        idempotency_key: str,
        reason: str,
    ) -> ProviderRefund:
        del idempotency_key, reason
        config = await self._config()
        _require_cny(currency)
        values = self._signed(
            {"pid": config.merchant_id, "trade_no": payment_ref, "money": _fen_to_money(amount)},
            config,
        )
        result = await self._request(
            "POST", urljoin(f"{config.gateway_url}/", "api.php?act=refund"), data=values
        )
        if str(result.get("code")) != "1":
            raise ProviderError(
                message="Epay rejected the refund",
                category=ErrorCategory.VALIDATION,
                permanent=True,
            )
        return ProviderRefund(
            refund_ref=str(result.get("refund_no") or payment_ref), state="completed"
        )

    async def get_refund(self, *, refund_ref: str) -> ProviderRefund:
        # LemPay's documented API has no dedicated refund lookup.  The refund reference is
        # therefore a terminal local fact once the authenticated refund response succeeded.
        await self._config()
        return ProviderRefund(refund_ref=refund_ref, state="completed")


def _require_cny(currency: str) -> None:
    if currency.upper() != CNY:
        raise ProviderError(
            message="payments only support CNY",
            category=ErrorCategory.VALIDATION,
            permanent=True,
        )


def _fen_to_money(amount: int) -> str:
    if amount <= 0:
        raise ProviderError(
            message="payment amount must be positive",
            category=ErrorCategory.VALIDATION,
            permanent=True,
        )
    return f"{Decimal(amount) / Decimal(100):.2f}"


def _money_to_fen(value: Any) -> int:
    try:
        money = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise WebhookVerificationError("invalid Epay amount") from exc
    if money <= 0:
        raise WebhookVerificationError("Epay amount must be positive")
    return int(money * 100)


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


__all__ = ["EpayConfig", "EpayPaymentProvider", "sign_parameters"]

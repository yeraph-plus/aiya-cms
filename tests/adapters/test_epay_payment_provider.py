"""LemPay-compatible Epay adapter contract tests without real payments."""

from __future__ import annotations

from typing import Any

import pytest

from inc.adapters.payments.epay import EpayPaymentProvider, sign_parameters
from inc.capabilities.payments.ports import WebhookRequest, WebhookVerificationError


class _Group:
    values = {
        "epay_gateway_url": "https://gateway.example/pay",
        "epay_merchant_id": "10001",
        "epay_merchant_key": "merchant-secret",
        "epay_payment_type": "alipay",
    }


class _Settings:
    async def get_group(self, group_key: str) -> _Group:
        assert group_key == "payments"
        return _Group()


def test_signature_uses_sorted_non_empty_values_and_lowercase_md5() -> None:
    signed = sign_parameters(
        {"z": "last", "a": "first", "empty": "", "zero": 0, "sign": "ignore"},
        "key",
    )
    assert signed == "dce467b519e81164a2001b596a8f7784"


@pytest.mark.asyncio
async def test_order_query_refund_and_get_webhook_close_over_documented_protocol(
    monkeypatch: Any,
) -> None:
    calls: list[dict[str, Any]] = []

    class Response:
        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self._payload

    def request(method: str, url: str, **kwargs: Any) -> Response:
        calls.append({"method": method, "url": url, **kwargs})
        if "mapi.php" in url:
            return Response(
                {
                    "code": 1,
                    "trade_no": "epay-1",
                    "payurl": "https://gateway.example/cashier/epay-1",
                }
            )
        if "act=refund" in url:
            return Response({"code": 1, "refund_no": "refund-1"})
        return Response({"code": 1, "trade_status": "TRADE_SUCCESS", "money": "12.34"})

    monkeypatch.setattr("inc.adapters.payments.epay.requests.request", request)
    provider = EpayPaymentProvider(settings_queries=_Settings())

    session = await provider.create_payment(
        order_reference="ord-1",
        amount=1234,
        currency="CNY",
        idempotency_key="ignored-by-epay",
        return_url="https://client.example/return",
        cancel_url="https://client.example/cancel",
        notify_url="https://api.example/webhooks/epay",
        description="Image hosting credits",
        client_ip="203.0.113.7",
    )
    assert session.provider_ref == "epay-1"
    assert session.redirect_url == "https://gateway.example/cashier/epay-1"
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "https://gateway.example/pay/mapi.php"
    assert calls[0]["data"]["money"] == "12.34"
    assert calls[0]["data"]["sign"] == sign_parameters(calls[0]["data"], "merchant-secret")

    status = await provider.get_payment(provider_ref="epay-1")
    assert status.state == "captured"
    assert status.captured_amount == 1234
    assert status.currency == "CNY"

    refund = await provider.create_refund(
        payment_ref="epay-1",
        amount=100,
        currency="CNY",
        idempotency_key="refund-1",
        reason="not required by gateway",
    )
    assert refund.refund_ref == "refund-1"
    assert calls[-1]["url"].endswith("api.php?act=refund")

    query = {
        "pid": "10001",
        "trade_no": "epay-1",
        "out_trade_no": "ord-1",
        "trade_status": "TRADE_SUCCESS",
        "money": "12.34",
    }
    query["sign"] = sign_parameters(query, "merchant-secret")
    event = await provider.verify_webhook(
        request=WebhookRequest(method="GET", raw_body=b"", headers={}, query_params=query)
    )
    assert event.event_id == "epay-1:TRADE_SUCCESS"
    assert event.acknowledgement == "success"

    duplicate = await provider.verify_webhook(
        request=WebhookRequest(method="GET", raw_body=b"", headers={}, query_params=query)
    )
    assert duplicate.event_id == event.event_id


@pytest.mark.asyncio
async def test_epay_rejects_bad_signature_and_missing_settings() -> None:
    provider = EpayPaymentProvider(settings_queries=_Settings())
    with pytest.raises(WebhookVerificationError):
        await provider.verify_webhook(
            request=WebhookRequest(
                method="GET",
                raw_body=b"",
                headers={},
                query_params={"pid": "10001", "sign": "forged"},
            )
        )

    class MissingSettings:
        async def get_group(self, group_key: str) -> Any:
            return type("Group", (), {"values": {}})()

    unavailable = EpayPaymentProvider(settings_queries=MissingSettings())
    assert await unavailable.check_availability() == (False, "payments.provider_unavailable")

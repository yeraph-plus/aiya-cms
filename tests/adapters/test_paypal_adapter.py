"""Contract tests for the PayPal adapter boundary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from inc.adapters.payments.paypal import PaypalConfig, PaypalPaymentProvider
from inc.capabilities.payments.ports import ProviderError
from inc.kernel.errors import KernelError


class _Response:
    status_code = 201

    def __init__(self, body: object) -> None:
        self.body = body

    def is_success(self) -> bool:
        return True


class _Orders:
    def __init__(self) -> None:
        self.options: dict[str, object] | None = None

    def create_order(self, options: dict[str, object]) -> _Response:
        self.options = options
        return _Response(
            SimpleNamespace(
                id="PAYPAL-ORDER-1",
                links=[SimpleNamespace(rel="payer-action", href="https://paypal.test/approve")],
            )
        )


class _Client:
    def __init__(self) -> None:
        self.orders = _Orders()


@pytest.mark.asyncio
async def test_create_payment_uses_minor_units_and_idempotency() -> None:
    client = _Client()
    provider = PaypalPaymentProvider(
        PaypalConfig(
            client_id="id",
            client_secret="secret",
            webhook_id="webhook",
            return_url="https://app.test/return",
            cancel_url="https://app.test/cancel",
        ),
        client=client,
    )

    session = await provider.create_payment(
        order_reference="ord_1",
        amount=1234,
        currency="CNY",
        idempotency_key="order:1",
        return_url="",
        cancel_url="",
    )

    assert session.provider_ref == "PAYPAL-ORDER-1"
    assert session.url == "https://paypal.test/approve"
    assert client.orders.options is not None
    assert client.orders.options["paypal_request_id"] == "order:1"
    request = client.orders.options["body"]
    assert request.purchase_units[0].amount.value == "12.34"


@pytest.mark.asyncio
async def test_unconfigured_provider_fails_explicitly() -> None:
    provider = PaypalPaymentProvider(PaypalConfig(client_id="", client_secret="", webhook_id=""))
    with pytest.raises(ProviderError, match="credentials"):
        await provider.get_payment(provider_ref="PAYPAL-ORDER-1")


def test_production_settings_require_paypal_secrets_and_urls() -> None:
    with pytest.raises(KernelError) as exc_info:
        PaypalPaymentProvider.from_settings(SimpleNamespace(paypal_environment="production"))
    assert exc_info.value.code == "payments.paypal_configuration_missing"

"""Epay payment adapter (planned).

Target: ``inc.capabilities.payments.ports.PaymentProvider``.

Planned integration: Epay (易支付) gateway SDK. Must own SDK client,
credentials, webhook signature verification and ProviderError
normalization. Do not implement until the provider contract is frozen;
this file must stay import-safe and side-effect free.
"""

"""PayPal payment adapter (planned).

Target: ``inc.capabilities.payments.ports.PaymentProvider``.

Planned integration: PayPal Orders API (v2, REST). Must own SDK client,
credentials, webhook signature verification (paypal transmission-id /
signature / timestamp headers) and ProviderError normalization. Do not
implement until the provider contract is frozen; this file must stay
import-safe and side-effect free.
"""

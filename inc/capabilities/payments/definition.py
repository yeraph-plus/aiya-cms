"""Payments capability: external payment orders, webhooks and refunds.

Contract source: context/spec/capabilities/payments.md.

Payments never imports points or identity; purchase semantics arrive via
feature workflows.
"""

from __future__ import annotations

from inc.kernel.boot import CapabilitySpec

spec = CapabilitySpec(
    name="payments",
    schema_version="1",
    access_keys=(
        "payments.create",
        "payments.cancel",
        "payments.refund",
        "payments.reconcile",
        "payments.read",
    ),
)

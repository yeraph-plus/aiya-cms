"""Payments diagnostics: read-only consistency probes.

Contract source: context/spec/capabilities/payments.md §9.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from inc.capabilities.payments.models import (
    PaymentOrder,
    PaymentRefund,
    PaymentWebhookReceipt,
)
from inc.kernel.db import UoWFactory
from inc.kernel.observability import DiagnosticResult, DiagnosticStatus
from inc.kernel.time import Clock


class PaymentsDiagnostics:
    key = "payments"

    def __init__(self, *, uow_factory: UoWFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def run(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        async with self._uow_factory() as uow:
            stale = (
                await uow.session.execute(
                    select(func.count(PaymentOrder.id)).where(
                        PaymentOrder.state.in_(("created", "pending")),
                        PaymentOrder.created_at < self._clock.utc_now() - timedelta(hours=24),
                    )
                )
            ).scalar_one()
            results.append(
                DiagnosticResult(
                    code="payments.stale_orders",
                    status=DiagnosticStatus.OK if stale == 0 else DiagnosticStatus.DEGRADED,
                    summary=f"{stale} orders stuck in created/pending longer than 24h",
                )
            )

            captured_mismatch = (
                await uow.session.execute(
                    select(func.count(PaymentOrder.id)).where(
                        PaymentOrder.state == "captured",
                        PaymentOrder.captured_amount != PaymentOrder.amount,
                    )
                )
            ).scalar_one()
            results.append(
                DiagnosticResult(
                    code="payments.captured_amount_mismatch",
                    status=(
                        DiagnosticStatus.OK if captured_mismatch == 0 else DiagnosticStatus.DEGRADED
                    ),
                    summary=f"{captured_mismatch} captured orders with amount mismatch",
                )
            )

            refund_mismatch = (
                await uow.session.execute(
                    select(func.count(PaymentRefund.id)).where(
                        PaymentRefund.state != "completed",
                        PaymentRefund.created_at < self._clock.utc_now() - timedelta(hours=24),
                    )
                )
            ).scalar_one()
            results.append(
                DiagnosticResult(
                    code="payments.stale_refunds",
                    status=(
                        DiagnosticStatus.OK if refund_mismatch == 0 else DiagnosticStatus.DEGRADED
                    ),
                    summary=f"{refund_mismatch} refunds not completed within 24h",
                )
            )

            receipts = (
                await uow.session.execute(
                    select(func.count(PaymentWebhookReceipt.id)).where(
                        PaymentWebhookReceipt.processing_state == "verified",
                        PaymentWebhookReceipt.order_id.is_(None),
                    )
                )
            ).scalar_one()
            results.append(
                DiagnosticResult(
                    code="payments.orphan_webhooks",
                    status=DiagnosticStatus.OK if receipts == 0 else DiagnosticStatus.DEGRADED,
                    summary=f"{receipts} verified webhooks without an order",
                )
            )
        return results

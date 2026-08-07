"""Payments queries.

Contract source: context/spec/capabilities/payments.md §6.

Read-only surface for cross-capability consumers (features); order state
is exposed so orchestration can decide whether a credit still applies.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from inc.capabilities.payments.commands import _to_order
from inc.capabilities.payments.models import PaymentOrder
from inc.capabilities.payments.schemas import OrderDTO
from inc.kernel.db import UoWFactory


class PaymentsQueries:
    """Read-only payments surface."""

    def __init__(self, *, uow_factory: UoWFactory) -> None:
        self._uow_factory = uow_factory

    async def get_order_by_reference(self, order_reference: str) -> OrderDTO | None:  # type: ignore[return]
        async with self._uow_factory() as uow:
            row: PaymentOrder | None = (
                (
                    await uow.session.execute(
                        select(PaymentOrder).where(PaymentOrder.order_reference == order_reference)
                    )
                )
                .scalars()
                .first()
            )
            return _to_order(row) if row is not None else None

    async def get_order(self, order_id: Any) -> OrderDTO | None:  # type: ignore[return]
        async with self._uow_factory() as uow:
            row: PaymentOrder | None = await uow.session.get(PaymentOrder, order_id)
            return _to_order(row) if row is not None else None

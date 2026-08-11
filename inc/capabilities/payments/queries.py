"""Payments queries.

Contract source: context/spec/capabilities/payments.md §6.

Read-only surface for cross-capability consumers (features); order state
is exposed so orchestration can decide whether a credit still applies.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from inc.capabilities.payments.commands import _to_order
from inc.capabilities.payments.models import PaymentAttempt, PaymentOrder, PaymentRefund
from inc.capabilities.payments.schemas import (
    OrderDetailDTO,
    OrderDTO,
    OrderPageDTO,
    PaymentAttemptDTO,
    RefundDTO,
)
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

    async def list_orders(  # type: ignore[return]
        self,
        *,
        page: int = 1,
        size: int = 20,
        state: str | None = None,
        provider_key: str | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
    ) -> OrderPageDTO:
        filters = []
        if state is not None:
            filters.append(PaymentOrder.state == state)
        if provider_key is not None:
            filters.append(PaymentOrder.provider_key == provider_key)
        if subject_type is not None:
            filters.append(PaymentOrder.subject_type == subject_type)
        if subject_id is not None:
            filters.append(PaymentOrder.subject_id == subject_id)

        async with self._uow_factory() as uow:
            total = int(
                (
                    await uow.session.execute(select(func.count(PaymentOrder.id)).where(*filters))
                ).scalar_one()
            )
            rows = (
                (
                    await uow.session.execute(
                        select(PaymentOrder)
                        .where(*filters)
                        .order_by(PaymentOrder.created_at.desc(), PaymentOrder.id.desc())
                        .offset((page - 1) * size)
                        .limit(size)
                    )
                )
                .scalars()
                .all()
            )
            return OrderPageDTO(
                items=[_to_order(row) for row in rows],
                page=page,
                size=size,
                total=total,
            )

    async def get_order_detail(  # type: ignore[return]
        self, order_id: Any
    ) -> OrderDetailDTO | None:
        async with self._uow_factory() as uow:
            order: PaymentOrder | None = await uow.session.get(PaymentOrder, order_id)
            if order is None:
                return None
            attempts = (
                (
                    await uow.session.execute(
                        select(PaymentAttempt)
                        .where(PaymentAttempt.order_id == order.id)
                        .order_by(PaymentAttempt.attempt, PaymentAttempt.id)
                    )
                )
                .scalars()
                .all()
            )
            refunds = (
                (
                    await uow.session.execute(
                        select(PaymentRefund)
                        .where(PaymentRefund.order_id == order.id)
                        .order_by(PaymentRefund.created_at, PaymentRefund.id)
                    )
                )
                .scalars()
                .all()
            )
            return OrderDetailDTO(
                order=_to_order(order),
                attempts=[
                    PaymentAttemptDTO(
                        id=str(row.id),
                        order_id=str(row.order_id),
                        provider_ref=row.provider_ref,
                        attempt=row.attempt,
                        state=row.state,
                        error_category=row.error_category,
                        error_summary=row.error_summary,
                        created_at=row.created_at,
                    )
                    for row in attempts
                ],
                refunds=[
                    RefundDTO(
                        id=str(row.id),
                        order_id=str(row.order_id),
                        refund_ref=row.refund_ref,
                        amount=row.amount,
                        currency=row.currency,
                        state=row.state,
                        reason=row.reason,
                    )
                    for row in refunds
                ],
            )

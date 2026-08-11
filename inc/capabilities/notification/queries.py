"""Side-effect-free administrator notification delivery queries."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from inc.capabilities.notification.models import (
    NotificationDelivery,
    NotificationDeliveryAttempt,
    NotificationIntent,
)
from inc.capabilities.notification.schemas import (
    NotificationDeliveryAttemptDTO,
    NotificationDeliveryDetailDTO,
    NotificationDeliveryPageDTO,
    NotificationDeliveryRecordDTO,
)
from inc.kernel.db import UoWFactory


def _record(
    delivery: NotificationDelivery, intent: NotificationIntent
) -> NotificationDeliveryRecordDTO:
    return NotificationDeliveryRecordDTO(
        id=str(delivery.id),
        intent_id=str(delivery.intent_id),
        channel=delivery.channel,
        provider_key=delivery.provider_key,
        masked_address=delivery.recipient.masked_address,
        attempt=delivery.attempt,
        status=delivery.status,
        provider_ref=delivery.provider_ref,
        error_category=delivery.error_category,
        error_summary=delivery.error_summary,
        next_retry_at=delivery.next_retry_at,
        delivered_at=delivery.delivered_at,
        spec_key=intent.spec_key,
        recipient_type=intent.recipient_type,
        recipient_id=intent.recipient_id,
        requested_at=intent.requested_at,
        created_at=delivery.created_at,
    )


def _attempt(row: NotificationDeliveryAttempt) -> NotificationDeliveryAttemptDTO:
    return NotificationDeliveryAttemptDTO(
        id=str(row.id),
        delivery_id=str(row.delivery_id),
        delivery_attempt=row.delivery_attempt,
        provider_sequence=row.provider_sequence,
        provider_key=row.provider_key,
        status=row.status,
        provider_ref=row.provider_ref,
        error_category=row.error_category,
        error_summary=row.error_summary,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


class NotificationQueries:
    def __init__(self, *, uow_factory: UoWFactory) -> None:
        self._uow_factory = uow_factory

    async def list_deliveries(  # type: ignore[return]
        self,
        *,
        page: int,
        size: int,
        status: str | None = None,
        channel: str | None = None,
        provider_key: str | None = None,
        spec_key: str | None = None,
        recipient_id: str | None = None,
    ) -> NotificationDeliveryPageDTO:
        statement = select(NotificationDelivery, NotificationIntent).join(
            NotificationIntent, NotificationIntent.id == NotificationDelivery.intent_id
        )
        if status is not None:
            statement = statement.where(NotificationDelivery.status == status)
        if channel is not None:
            statement = statement.where(NotificationDelivery.channel == channel)
        if provider_key is not None:
            statement = statement.where(NotificationDelivery.provider_key == provider_key)
        if spec_key is not None:
            statement = statement.where(NotificationIntent.spec_key == spec_key)
        if recipient_id is not None:
            statement = statement.where(NotificationIntent.recipient_id == recipient_id)
        statement = statement.order_by(
            NotificationDelivery.created_at.desc(), NotificationDelivery.id.desc()
        )
        async with self._uow_factory() as uow:
            total = (
                await uow.session.execute(
                    select(func.count()).select_from(statement.order_by(None).subquery())
                )
            ).scalar_one()
            rows = (
                await uow.session.execute(statement.offset((page - 1) * size).limit(size))
            ).all()
            return NotificationDeliveryPageDTO(
                items=[_record(delivery, intent) for delivery, intent in rows],
                total=total,
                page=page,
                size=size,
            )

    async def get_delivery(  # type: ignore[return]
        self, delivery_id: uuid.UUID
    ) -> NotificationDeliveryDetailDTO | None:
        async with self._uow_factory() as uow:
            pair = (
                await uow.session.execute(
                    select(NotificationDelivery, NotificationIntent)
                    .join(
                        NotificationIntent,
                        NotificationIntent.id == NotificationDelivery.intent_id,
                    )
                    .where(NotificationDelivery.id == delivery_id)
                )
            ).first()
            if pair is None:
                return None
            attempts = (
                (
                    await uow.session.execute(
                        select(NotificationDeliveryAttempt)
                        .where(NotificationDeliveryAttempt.delivery_id == delivery_id)
                        .order_by(
                            NotificationDeliveryAttempt.delivery_attempt,
                            NotificationDeliveryAttempt.provider_sequence,
                            NotificationDeliveryAttempt.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            return NotificationDeliveryDetailDTO(
                delivery=_record(pair[0], pair[1]),
                attempts=[_attempt(row) for row in attempts],
            )

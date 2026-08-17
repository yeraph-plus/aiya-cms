"""Retention activity for terminal notification delivery history."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import delete, exists, select

from inc.capabilities.notification.models import (
    NotificationDelivery,
    NotificationDeliveryAttempt,
    NotificationIntent,
)
from inc.kernel.db import UnitOfWork
from inc.kernel.observability import get_logger
from inc.kernel.time import Clock

RETENTION_GROUP_KEY = "operations"
RETENTION_FIELD = "audit_retention_days"


class RetentionSettings(Protocol):
    async def get_value(self, group_key: str, field_slug: str) -> Any: ...


async def cleanup_notifications_in_uow(uow: UnitOfWork, cutoff: datetime) -> dict[str, int]:
    """Delete only terminal notification records older than ``cutoff``."""

    terminal_delivery_ids = select(NotificationDelivery.id).where(
        NotificationDelivery.status.in_(("delivered", "failed", "dead", "cancelled")),
        NotificationDelivery.created_at < cutoff,
    )
    attempts = await uow.session.execute(
        delete(NotificationDeliveryAttempt).where(
            NotificationDeliveryAttempt.delivery_id.in_(terminal_delivery_ids)
        )
    )
    deliveries = await uow.session.execute(
        delete(NotificationDelivery).where(NotificationDelivery.id.in_(terminal_delivery_ids))
    )
    orphan_intents = await uow.session.execute(
        delete(NotificationIntent).where(
            NotificationIntent.created_at < cutoff,
            ~exists(
                select(NotificationDelivery.id).where(
                    NotificationDelivery.intent_id == NotificationIntent.id
                )
            ),
        )
    )
    return {
        "notification_attempts_deleted": attempts.rowcount or 0,
        "notification_deliveries_deleted": deliveries.rowcount or 0,
        "notification_intents_deleted": orphan_intents.rowcount or 0,
    }


class NotificationRetentionActivity:
    """Persistently clean terminal notification history on a Cron tick."""

    def __init__(self, *, settings: RetentionSettings, clock: Clock) -> None:
        self._settings = settings
        self._clock = clock

    async def __call__(self, uow: UnitOfWork, data: dict[str, Any], ctx: Any) -> dict[str, int]:
        del data, ctx
        days = int(await self._settings.get_value(RETENTION_GROUP_KEY, RETENTION_FIELD))
        cutoff = self._clock.utc_now() - timedelta(days=days)
        counts = await cleanup_notifications_in_uow(uow, cutoff)
        get_logger("notification.retention").info(
            "notification retention cleanup completed", retention_days=days, **counts
        )
        return {"retention_days": days, **counts}


__all__ = ["NotificationRetentionActivity", "cleanup_notifications_in_uow"]

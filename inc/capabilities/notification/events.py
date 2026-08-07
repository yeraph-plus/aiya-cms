"""Notification events.

Contract source: context/spec/capabilities/notification.md §7.

Events never carry full recipient addresses or rendered bodies; only the
delivery reference, channel and status facts.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from inc.kernel.errors import validate_error_code


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery_id: str
    intent_id: str
    spec_key: str
    channel: str


class NotificationRequestedPayload(_Base):
    pass


class NotificationDeliveredPayload(_Base):
    provider_ref: str | None = None


class NotificationDeliveryFailedPayload(_Base):
    error_category: str
    attempt: int


class NotificationDeliveryDeadPayload(_Base):
    error_category: str
    attempt: int


NOTIFICATION_EVENT_SCHEMAS: dict[str, type[BaseModel]] = {
    "notification.requested.v1": NotificationRequestedPayload,
    "notification.delivered.v1": NotificationDeliveredPayload,
    "notification.delivery_failed.v1": NotificationDeliveryFailedPayload,
    "notification.delivery_dead.v1": NotificationDeliveryDeadPayload,
}

for _key in NOTIFICATION_EVENT_SCHEMAS:
    validate_error_code(_key)

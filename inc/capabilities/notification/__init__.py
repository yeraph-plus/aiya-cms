"""Notification capability: intent, delivery planning and reliable dispatch.

Contract source: context/spec/capabilities/notification.md.

Public surface for the composition root: spec registry, commands,
deliver workflow wiring and diagnostics.
"""

from __future__ import annotations

from inc.capabilities.notification.activities import DeliverActivity, build_deliver_workflow_spec
from inc.capabilities.notification.auth import (
    AUTH_CHALLENGE_DELIVERY_MAX_ATTEMPTS,
    AUTH_NOTIFICATION_SPECS,
    AuthChallengeInput,
    AuthChallengeNotifier,
    ensure_auth_templates,
)
from inc.capabilities.notification.commands import CommandContext
from inc.capabilities.notification.diagnostics import NotificationDiagnostics
from inc.capabilities.notification.queries import NotificationQueries
from inc.capabilities.notification.retention import (
    NotificationRetentionActivity,
    cleanup_notifications_in_uow,
)
from inc.capabilities.notification.specs import (
    NOTIFICATION_DELIVERY_MAX_ATTEMPTS,
    DeliveryPolicy,
    NotificationSpec,
    NotificationSpecRegistry,
)

__all__ = [
    "CommandContext",
    "AUTH_CHALLENGE_DELIVERY_MAX_ATTEMPTS",
    "AUTH_NOTIFICATION_SPECS",
    "AuthChallengeInput",
    "AuthChallengeNotifier",
    "DeliverActivity",
    "DeliveryPolicy",
    "NotificationDiagnostics",
    "NOTIFICATION_DELIVERY_MAX_ATTEMPTS",
    "NotificationQueries",
    "NotificationRetentionActivity",
    "NotificationSpec",
    "NotificationSpecRegistry",
    "build_deliver_workflow_spec",
    "cleanup_notifications_in_uow",
    "ensure_auth_templates",
]

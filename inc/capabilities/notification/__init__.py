"""Notification capability: intent, delivery planning and reliable dispatch.

Contract source: context/spec/capabilities/notification.md.

Public surface for the composition root: spec registry, commands,
deliver workflow wiring and diagnostics.
"""

from __future__ import annotations

from inc.capabilities.notification.activities import DeliverActivity, build_deliver_workflow_spec
from inc.capabilities.notification.commands import CommandContext
from inc.capabilities.notification.diagnostics import NotificationDiagnostics
from inc.capabilities.notification.specs import (
    DeliveryPolicy,
    NotificationSpec,
    NotificationSpecRegistry,
)

__all__ = [
    "CommandContext",
    "DeliverActivity",
    "DeliveryPolicy",
    "NotificationDiagnostics",
    "NotificationSpec",
    "NotificationSpecRegistry",
    "build_deliver_workflow_spec",
]

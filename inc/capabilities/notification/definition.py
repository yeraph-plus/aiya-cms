"""Notification capability: intent, delivery planning and reliable dispatch.

Contract source: context/spec/capabilities/notification.md.

Email and SMS are adapters bound by the composition root; this capability
never opens provider connections on its own. A manifest that does not
assemble notification connects nothing.
"""

from __future__ import annotations

from inc.kernel.boot import CapabilitySpec

spec = CapabilitySpec(
    name="notification",
    schema_version="1",
    access_keys=(
        "notification.request",
        "notification.cancel",
        "notification.retry",
        "notification.read",
        "notification.templates.manage",
    ),
)

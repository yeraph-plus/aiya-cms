"""Explicit migration manifest.

Contract source: context/spec/kernel/database.md §6/§7.

Maps every shipped table owner to the model module that registers its
tables on the kernel Base metadata. ``alembic/env.py`` imports exactly these
modules; directory scanning is forbidden. Owners are ``kernel:<component>``
or ``capability:<name>``.

Kernel technical tables (outbox, inbox receipts, workflow instances, step
attempts, signals, task instances, cron state) and shipped capability models
are collected here explicitly and released through the single ``release_0001``
revision. Later changes advance by owner-specific revisions.
"""

from __future__ import annotations

MIGRATION_OWNER_MODULES: dict[str, str] = {
    "kernel:events": "inc.kernel.events.models",
    "kernel:workflow": "inc.kernel.workflow.models",
    "kernel:tasks": "inc.kernel.tasks.models",
    "capability:audit": "inc.capabilities.audit.models",
    "capability:identity": "inc.capabilities.identity.models",
    "capability:access": "inc.capabilities.access.models",
    "capability:oidc_provider": "inc.capabilities.oidc_provider.models",
    "capability:content": "inc.capabilities.content.models",
    "capability:comments": "inc.capabilities.comments.models",
    "capability:community": "inc.capabilities.community.models",
    "capability:taxonomy": "inc.capabilities.taxonomy.models",
    "capability:settings": "inc.capabilities.settings.models",
    "capability:assets": "inc.capabilities.assets.models",
    "capability:notification": "inc.capabilities.notification.models",
    "capability:points": "inc.capabilities.points.models",
    "capability:payments": "inc.capabilities.payments.models",
    "capability:membership": "inc.capabilities.membership.models",
    "capability:engagement": "inc.capabilities.engagement.models",
}

"""Explicit migration manifest.

Contract source: context/spec/kernel/database.md §6/§7.

Maps every shipped table owner to the model module that registers its
tables on the kernel Base metadata. ``alembic/env.py`` imports exactly these
modules; directory scanning is forbidden. Owners are ``kernel:<component>``
or ``capability:<name>``.

Kernel technical tables (outbox, inbox receipts, workflow instances, step
attempts, signals, task instances, cron state) land with R3. Capability
models are added as their phases land, and everything is squashed into a
single ``0001_initial`` revision at R9.
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
}

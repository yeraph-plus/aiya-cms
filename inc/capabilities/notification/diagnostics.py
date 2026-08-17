"""Notification diagnostics: read-only consistency probes.

Contract source: context/spec/capabilities/notification.md §8.

Reports pending age, expired leases, unknown/dead backlogs, spec drift and
unbound channels. Never repairs.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from inc.capabilities.notification.models import (
    NotificationDelivery,
    NotificationIntent,
    NotificationTemplate,
)
from inc.capabilities.notification.specs import NotificationSpecRegistry
from inc.kernel.db import UoWFactory
from inc.kernel.observability import DiagnosticResult, DiagnosticStatus
from inc.kernel.time import Clock


class NotificationDiagnostics:
    key = "notification"

    def __init__(
        self, *, uow_factory: UoWFactory, specs: NotificationSpecRegistry, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory
        self._specs = specs
        self._clock = clock

    async def run(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        async with self._uow_factory() as uow:
            pending = (
                await uow.session.execute(
                    select(func.count(NotificationDelivery.id)).where(
                        NotificationDelivery.status == "pending",
                        NotificationDelivery.created_at
                        < self._clock.utc_now() - timedelta(hours=24),
                    )
                )
            ).scalar_one()
            results.append(
                DiagnosticResult(
                    code="notification.pending_old",
                    status=DiagnosticStatus.OK if pending == 0 else DiagnosticStatus.DEGRADED,
                    summary=f"{pending} deliveries pending longer than 24h",
                )
            )

            expired_lease = (
                await uow.session.execute(
                    select(func.count(NotificationDelivery.id)).where(
                        NotificationDelivery.status == "sending",
                        NotificationDelivery.lease_expires_at < self._clock.utc_now(),
                    )
                )
            ).scalar_one()
            results.append(
                DiagnosticResult(
                    code="notification.expired_lease",
                    status=(
                        DiagnosticStatus.OK if expired_lease == 0 else DiagnosticStatus.DEGRADED
                    ),
                    summary=f"{expired_lease} sending deliveries with expired leases",
                )
            )

            unknown_dead = (
                await uow.session.execute(
                    select(func.count(NotificationDelivery.id)).where(
                        NotificationDelivery.status.in_(("unknown", "dead"))
                    )
                )
            ).scalar_one()
            results.append(
                DiagnosticResult(
                    code="notification.unknown_dead_backlog",
                    status=(
                        DiagnosticStatus.OK if unknown_dead == 0 else DiagnosticStatus.DEGRADED
                    ),
                    summary=f"{unknown_dead} unknown/dead deliveries awaiting manual recovery",
                )
            )

            intents = (
                (await uow.session.execute(select(NotificationIntent.spec_key))).scalars().all()
            )
            registered = {s.key for s in self._specs.specs()}
            unknown_specs = sorted(set(intents) - registered)
            results.append(
                DiagnosticResult(
                    code="notification.spec_drift",
                    status=(
                        DiagnosticStatus.OK if not unknown_specs else DiagnosticStatus.DEGRADED
                    ),
                    summary=f"{len(unknown_specs)} intents reference unregistered specs",
                )
            )

            template_rows = (
                await uow.session.execute(
                    select(
                        NotificationTemplate.template_key,
                        NotificationTemplate.channel,
                        NotificationTemplate.locale,
                    ).where(NotificationTemplate.status == "active")
                )
            ).all()
            available_templates = {
                (template_key, channel, locale) for template_key, channel, locale in template_rows
            }
            missing_templates: list[str] = []
            for spec in self._specs.specs():
                for template_key in spec.template_keys:
                    for channel in spec.channels:
                        if not any(
                            (template_key, channel, locale) in available_templates
                            for locale in (spec.locale, "en")
                        ):
                            missing_templates.append(f"{template_key}:{channel}:{spec.locale}")
            results.append(
                DiagnosticResult(
                    code="notification.template_seed",
                    status=(
                        DiagnosticStatus.OK if not missing_templates else DiagnosticStatus.DEGRADED
                    ),
                    summary=(
                        "all registered notification templates are seeded"
                        if not missing_templates
                        else f"{len(missing_templates)} registered notification templates "
                        f"are missing"
                    ),
                )
            )
        return results

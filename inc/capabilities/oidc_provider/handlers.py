"""Security event consumption and OIDC diagnostics.

Contract source: context/spec/capabilities/oidc-provider.md §4/§12.

Consumes identity security facts (ban, password change) and revokes the
subject's sessions through the SecurityEventSubscriber Port, which the
composition root binds.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from inc.capabilities.oidc_provider.models import OidcAuthorizationCode, OidcSigningKey
from inc.capabilities.oidc_provider.ports import SecurityEventSubscriber
from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.events import EventEnvelope, InboxGuard
from inc.kernel.observability import DiagnosticResult, DiagnosticStatus
from inc.kernel.time import Clock

SECURITY_EVENT_KEYS = ("identity.user_banned.v1", "identity.password_changed.v1")


class SecurityEventRevoker:
    """Revokes a subject's sessions when security facts arrive."""

    key = "oidc.revoke_on_security_event.v1"

    def __init__(self, *, subscriber: SecurityEventSubscriber, clock: Clock) -> None:
        self._subscriber = subscriber
        self._clock = clock

    async def handle(self, envelope: EventEnvelope, uow: UnitOfWork) -> None:
        subject_id = str(envelope.payload.get("subject_id", ""))

        async def work() -> None:
            await self._subscriber.revoke_subject_sessions(subject_id, envelope.event_key)

        await InboxGuard.process(
            uow,
            handler_key=self.key,
            event_id=envelope.event_id,
            work=work,
            processed_at=self._clock.utc_now(),
        )


class OidcDiagnostics:
    key = "oidc_provider"

    def __init__(self, *, uow_factory: UoWFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def run(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        async with self._uow_factory() as uow:
            active_keys = (
                (
                    await uow.session.execute(
                        select(OidcSigningKey.id).where(OidcSigningKey.status == "active")
                    )
                )
                .scalars()
                .all()
            )
            results.append(
                DiagnosticResult(
                    code="oidc.no_active_signing_key",
                    status=DiagnosticStatus.FAILED if not active_keys else DiagnosticStatus.OK,
                    summary=f"{len(active_keys)} active signing keys",
                )
            )

            expired_codes = (
                await uow.session.execute(
                    select(func.count(OidcAuthorizationCode.id)).where(
                        OidcAuthorizationCode.expires_at
                        < self._clock.utc_now() - timedelta(days=7),
                        OidcAuthorizationCode.consumed_at.is_(None),
                    )
                )
            ).scalar_one()
            results.append(
                DiagnosticResult(
                    code="oidc.expired_codes_backlog",
                    status=DiagnosticStatus.OK if expired_codes == 0 else DiagnosticStatus.DEGRADED,
                    summary=f"{expired_codes} unconsumed codes older than 7 days",
                )
            )
        return results

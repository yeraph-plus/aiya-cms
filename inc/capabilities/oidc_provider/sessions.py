"""Subject session revocation (public composition-root service).

Contract source: context/spec/capabilities/oidc-provider.md §4.

The composition root binds the SecurityEventSubscriber Port to this
service; it revokes the subject's login sessions so existing cookies and
refresh grants stop working after ban or password change.
"""

from __future__ import annotations

from sqlalchemy import update

from inc.capabilities.oidc_provider.models import OidcSession
from inc.kernel.db import UoWFactory
from inc.kernel.time import Clock


class OidcSessionRevoker:
    """SecurityEventSubscriber implementation: revoke all open sessions."""

    def __init__(self, *, uow_factory: UoWFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def revoke_subject_sessions(self, subject_id: str, reason: str) -> None:
        now = self._clock.utc_now()
        async with self._uow_factory() as uow:
            await uow.session.execute(
                update(OidcSession)
                .where(
                    OidcSession.subject_id == subject_id,
                    OidcSession.revoked_at.is_(None),
                    OidcSession.expires_at > now,
                )
                .values(revoked_at=now)
            )
            await uow.commit()

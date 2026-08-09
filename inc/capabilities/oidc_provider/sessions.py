"""Subject session revocation (public composition-root service).

Contract source: context/spec/capabilities/oidc-provider.md §4.

The composition root binds the SecurityEventSubscriber Port to this
service; it revokes the subject's login sessions and refresh-token
families so existing cookies, refresh grants and in-flight refresh
rotation stop working after ban or password change.
"""

from __future__ import annotations

from sqlalchemy import select, update

from inc.capabilities.oidc_provider.models import (
    OidcRefreshFamily,
    OidcRefreshToken,
    OidcSession,
)
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
            # A banned/password-changed subject must also lose refresh grants:
            # the refresh path only consults family/token revocation, so a
            # leftover family would otherwise keep minting access tokens.
            await uow.session.execute(
                update(OidcRefreshFamily)
                .where(
                    OidcRefreshFamily.subject_id == subject_id,
                    OidcRefreshFamily.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            await uow.session.execute(
                update(OidcRefreshToken)
                .where(
                    OidcRefreshToken.revoked_at.is_(None),
                    OidcRefreshToken.family_id.in_(
                        select(OidcRefreshFamily.id).where(
                            OidcRefreshFamily.subject_id == subject_id,
                        )
                    ),
                )
                .values(revoked_at=now)
            )
            await uow.commit()

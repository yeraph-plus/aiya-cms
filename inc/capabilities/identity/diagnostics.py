"""Identity diagnostics: read-only consistency probes.

Contract source: context/spec/capabilities/identity.md §9.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from inc.capabilities.identity.models import (
    IdentityChallenge,
    IdentityLoginIdentity,
    IdentityPasswordCredential,
    IdentityUser,
)
from inc.kernel.db import UoWFactory
from inc.kernel.observability import DiagnosticResult, DiagnosticStatus


class IdentityDiagnostics:
    key = "identity"

    def __init__(self, *, uow_factory: UoWFactory, clock: Any) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def run(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        async with self._uow_factory() as uow:
            no_login = (
                (
                    await uow.session.execute(
                        select(IdentityUser.id)
                        .outerjoin(
                            IdentityLoginIdentity,
                            IdentityLoginIdentity.user_id == IdentityUser.id,
                        )
                        .where(
                            IdentityUser.status == "active",
                            IdentityLoginIdentity.id.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            results.append(
                DiagnosticResult(
                    code="identity.no_login_method",
                    status=DiagnosticStatus.OK if not no_login else DiagnosticStatus.DEGRADED,
                    summary=f"{len(no_login)} active users without login identities",
                )
            )

            expired = (
                await uow.session.execute(
                    select(func.count(IdentityChallenge.id)).where(
                        IdentityChallenge.expires_at < self._clock.utc_now() - timedelta(days=7),
                        IdentityChallenge.consumed_at.is_(None),
                    )
                )
            ).scalar_one()
            results.append(
                DiagnosticResult(
                    code="identity.expired_challenge_backlog",
                    status=DiagnosticStatus.OK if expired == 0 else DiagnosticStatus.DEGRADED,
                    summary=f"{expired} unconsumed challenges older than 7 days",
                )
            )

            hash_versions = (
                await uow.session.execute(
                    select(IdentityPasswordCredential.hash_version, func.count()).group_by(
                        IdentityPasswordCredential.hash_version
                    )
                )
            ).all()
            versions = ", ".join(f"{v}={n}" for v, n in hash_versions)
            results.append(
                DiagnosticResult(
                    code="identity.hash_versions",
                    status=DiagnosticStatus.OK,
                    summary=f"credential hash versions: {versions or 'none'}",
                )
            )
        return results

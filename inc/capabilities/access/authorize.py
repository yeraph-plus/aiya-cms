"""Authorization decisions.

Contract source: context/spec/capabilities/access.md §5.

Default deny. Decisions read role grants and their capability keys from the
current database state — no cached permission claims are trusted. Banned,
deleted or anonymous principals are denied unless explicitly evaluated by
scope semantics.
"""

from __future__ import annotations

from sqlalchemy import select

from inc.capabilities.access.models import AccessRole, AccessRoleCapability, AccessSubjectRole
from inc.capabilities.access.schemas import AuthorizationDecision, Principal
from inc.kernel.db import UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.time import Clock


class AuthorizeService:
    def __init__(self, *, uow_factory: UoWFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def decide(
        self,
        principal: Principal,
        permission_key: str,
        *,
        scope: str = "global",
    ) -> AuthorizationDecision:
        if principal.status not in ("active", "anonymous"):
            return AuthorizationDecision(allowed=False, reason="deny.principal_status")
        if principal.status == "anonymous":
            return AuthorizationDecision(allowed=False, reason="deny.anonymous")
        if scope not in ("global", "own"):
            raise KernelError(
                code="access.invalid_scope",
                category=ErrorCategory.VALIDATION,
                message=f"unknown scope {scope!r}",
            )

        now = self._clock.utc_now()
        async with self._uow_factory() as uow:
            rows = (
                await uow.session.execute(
                    select(AccessRoleCapability.capability_key, AccessSubjectRole.scope)
                    .join(
                        AccessSubjectRole, AccessSubjectRole.role_id == AccessRoleCapability.role_id
                    )
                    .where(
                        AccessSubjectRole.subject_type == "identity",
                        AccessSubjectRole.subject_id == principal.subject_id,
                        (AccessSubjectRole.valid_from.is_(None))
                        | (AccessSubjectRole.valid_from <= now),
                        (AccessSubjectRole.valid_until.is_(None))
                        | (AccessSubjectRole.valid_until >= now),
                    )
                )
            ).all()
        granted = {key for key, _ in rows}
        if permission_key not in granted:
            return AuthorizationDecision(allowed=False, reason="deny.no_grant")
        scopes = {grant_scope for key, grant_scope in rows if key == permission_key}
        if scope == "global":
            if "global" in scopes:
                return AuthorizationDecision(allowed=True, reason="allow.global")
            return AuthorizationDecision(allowed=False, reason="deny.scope")
        if "global" in scopes or "own" in scopes:
            return AuthorizationDecision(allowed=True, reason=f"allow.{scope}")
        return AuthorizationDecision(allowed=False, reason="deny.scope")

    async def capabilities_of(self, principal: Principal) -> set[str]:
        """Current capability set for Principal construction (short-cached)."""

        if principal.status != "active":
            return set()
        now = self._clock.utc_now()
        async with self._uow_factory() as uow:
            rows = (
                (
                    await uow.session.execute(
                        select(AccessRoleCapability.capability_key)
                        .join(AccessRole, AccessRole.id == AccessRoleCapability.role_id)
                        .join(AccessSubjectRole, AccessSubjectRole.role_id == AccessRole.id)
                        .where(
                            AccessSubjectRole.subject_type == "identity",
                            AccessSubjectRole.subject_id == principal.subject_id,
                            (AccessSubjectRole.valid_from.is_(None))
                            | (AccessSubjectRole.valid_from <= now),
                            (AccessSubjectRole.valid_until.is_(None))
                            | (AccessSubjectRole.valid_until >= now),
                        )
                    )
                )
                .scalars()
                .all()
            )
        return set(rows)

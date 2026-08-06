"""Access queries and diagnostics.

Contract source: context/spec/capabilities/access.md §5/§8.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from inc.capabilities.access.models import AccessRole, AccessRoleCapability, AccessSubjectRole
from inc.capabilities.access.registry import PermissionRegistry
from inc.capabilities.access.schemas import GrantSummary, RoleDTO
from inc.kernel.db import UoWFactory
from inc.kernel.observability import DiagnosticResult, DiagnosticStatus


class AccessQueries:
    def __init__(self, *, uow_factory: UoWFactory) -> None:
        self._uow_factory = uow_factory

    async def list_roles(self) -> list[RoleDTO]:  # type: ignore[return]
        async with self._uow_factory() as uow:
            roles = (
                (
                    await uow.session.execute(
                        select(AccessRole).order_by(AccessRole.slug, AccessRole.id)
                    )
                )
                .scalars()
                .all()
            )
            result: list[RoleDTO] = []
            for role in roles:
                keys = (
                    (
                        await uow.session.execute(
                            select(AccessRoleCapability.capability_key).where(
                                AccessRoleCapability.role_id == role.id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                result.append(
                    RoleDTO(
                        id=str(role.id),
                        name=role.name,
                        slug=role.slug,
                        description=role.description,
                        system=role.system,
                        capability_keys=list(keys),
                    )
                )
            return result

    async def grants_for(self, subject_type: str, subject_id: str) -> GrantSummary:  # type: ignore[return]
        async with self._uow_factory() as uow:
            rows = (
                (
                    await uow.session.execute(
                        select(AccessSubjectRole)
                        .where(
                            AccessSubjectRole.subject_type == subject_type,
                            AccessSubjectRole.subject_id == subject_id,
                        )
                        .order_by(AccessSubjectRole.created_at, AccessSubjectRole.id)
                    )
                )
                .scalars()
                .all()
            )
            return GrantSummary(
                subject_type=subject_type,
                subject_id=subject_id,
                roles=[str(row.role_id) for row in rows],
                scopes=[row.scope for row in rows],
            )


class AccessDiagnostics:
    key = "access"

    def __init__(
        self,
        *,
        uow_factory: UoWFactory,
        permissions: PermissionRegistry,
        clock: Any,
    ) -> None:
        self._uow_factory = uow_factory
        self._permissions = permissions
        self._clock = clock

    async def run(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        async with self._uow_factory() as uow:
            role_keys = (
                (await uow.session.execute(select(AccessRoleCapability.capability_key).distinct()))
                .scalars()
                .all()
            )
            unknown = [key for key in role_keys if not self._permissions.contains(key)]
            results.append(
                DiagnosticResult(
                    code="access.unknown_capability_keys",
                    status=DiagnosticStatus.OK if not unknown else DiagnosticStatus.FAILED,
                    summary=f"{len(unknown)} unregistered capability keys on roles",
                )
            )

            admin_count = (
                (
                    await uow.session.execute(
                        select(AccessSubjectRole.id)
                        .join(AccessRole, AccessRole.id == AccessSubjectRole.role_id)
                        .where(AccessRole.slug == "administrator")
                    )
                )
                .scalars()
                .all()
            )
            results.append(
                DiagnosticResult(
                    code="access.no_admin_subjects",
                    status=DiagnosticStatus.DEGRADED if not admin_count else DiagnosticStatus.OK,
                    summary=f"{len(admin_count)} administrator subjects",
                )
            )
        return results

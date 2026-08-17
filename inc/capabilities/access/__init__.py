"""Access capability: roles, permission keys, authorization decisions.

Contract source: context/spec/capabilities/access.md.

Public surface for the composition root: authorization service, role
commands, queries, the permission registry and diagnostics.
"""

from __future__ import annotations

from inc.capabilities.access.authorize import AuthorizeService
from inc.capabilities.access.commands import (
    AssignDefaultUserRole,
    AssignRoleToSubject,
    BootstrapAdministrator,
    CommandContext,
    CreateRole,
    DeleteRole,
    EnsureBaseRoles,
    ReplaceRoleCapabilities,
    RevokeRoleFromSubject,
    UpdateRole,
)
from inc.capabilities.access.queries import AccessDiagnostics, AccessQueries
from inc.capabilities.access.registry import PermissionRegistry

__all__ = [
    "AccessDiagnostics",
    "AccessQueries",
    "AssignRoleToSubject",
    "AssignDefaultUserRole",
    "EnsureBaseRoles",
    "AuthorizeService",
    "BootstrapAdministrator",
    "CommandContext",
    "CreateRole",
    "UpdateRole",
    "DeleteRole",
    "PermissionRegistry",
    "ReplaceRoleCapabilities",
    "RevokeRoleFromSubject",
]

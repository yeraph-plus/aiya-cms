"""Minimal RBAC public API (see context/spec/kernel.md)."""

from inc.kernel.security import Principal

from .checker import CapabilityChecker, check_capability, require_any_capability, require_capability
from .definitions import (
    ALL_CAPABILITIES,
    ALL_CAPABILITY_ALIASES,
    CORE_CAPABILITIES,
    MODULE_CAPABILITIES,
    ROLE_SEEDS,
    RoleSeed,
)
from .errors import RBAC_001, RBAC_002, RBAC_003, RBAC_004, RBAC_CODES
from .events import RBAC_EVENT_TYPES, RoleAssignedPayload, RoleMembershipReplacedPayload
from .registry import (
    CapabilityDefinition,
    CapabilityRegistry,
    capability_registry,
    register_capabilities,
    register_capability,
    validate_capability_registry,
)
from .schemas import PermissionRead, PolicyContext, RoleAssign, RoleRead, UserRoleSet
from .seed import seed_rbac
from .service import RBACService
from .uow import RBACUnitOfWork

# Explicit wiring at import time keeps the public dependency factory usable in
# small applications; startup can still call validate_capability_registry().
if not capability_registry.aliases():
    capability_registry.register_many(ALL_CAPABILITIES)

__all__ = [
    "ALL_CAPABILITIES",
    "ALL_CAPABILITY_ALIASES",
    "CORE_CAPABILITIES",
    "MODULE_CAPABILITIES",
    "ROLE_SEEDS",
    "RoleSeed",
    "CapabilityDefinition",
    "CapabilityRegistry",
    "capability_registry",
    "register_capability",
    "register_capabilities",
    "validate_capability_registry",
    "CapabilityChecker",
    "check_capability",
    "require_capability",
    "require_any_capability",
    "Principal",
    "PolicyContext",
    "RoleRead",
    "PermissionRead",
    "RoleAssign",
    "RBACService",
    "RBAC_EVENT_TYPES",
    "RoleAssignedPayload",
    "RoleMembershipReplacedPayload",
    "UserRoleSet",
    "RBACUnitOfWork",
    "seed_rbac",
    "RBAC_001",
    "RBAC_002",
    "RBAC_003",
    "RBAC_004",
    "RBAC_CODES",
]

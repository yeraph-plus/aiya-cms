"""Identity component (M1.5): users, login identities, org placeholder.

Public surface for consumers: DTOs + IdentityService + error codes. ORM models
and repositories stay internal to migrations/tests; DTO boundaries are specified in context/spec/kernel.md.
"""

from .errors import IDENTITY_CODES, USER_001, USER_002
from .events import IDENTITY_EVENT_TYPES, UserStatusChangedPayload
from .schemas import UserAdminRead, UserAdminUpdate, UserCreate, UserQuery, UserRead, UserRoleSet
from .service import IdentityService
from .uow import IdentityUnitOfWork

__all__ = [
    "IDENTITY_CODES",
    "IDENTITY_EVENT_TYPES",
    "UserStatusChangedPayload",
    "USER_001",
    "USER_002",
    "IdentityService",
    "IdentityUnitOfWork",
    "UserCreate",
    "UserAdminRead",
    "UserAdminUpdate",
    "UserQuery",
    "UserRead",
    "UserRoleSet",
]

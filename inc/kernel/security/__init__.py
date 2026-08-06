"""Request principal primitives shared by auth and RBAC.

Token and password primitives are intentionally left for M1.4; RBAC only
needs a stable, serialisable principal boundary.
"""

from .errors import AUTH_002, AUTH_003, AUTH_CODES
from .passwords import hash_password, verify_password
from .principal import Principal, get_current_principal
from .tokens import PrincipalClaims, TokenService, hash_refresh

__all__ = [
    "Principal",
    "PrincipalClaims",
    "TokenService",
    "get_current_principal",
    "hash_password",
    "verify_password",
    "hash_refresh",
    "AUTH_002",
    "AUTH_003",
    "AUTH_CODES",
]

"""Authentication flow public API (M1.8)."""

from inc.kernel.security import AUTH_002, AUTH_003
from inc.kernel.security import AUTH_CODES as SECURITY_AUTH_CODES

from .dependencies import get_current_principal
from .errors import (
    AUTH_001,
    AUTH_004,
    AUTH_005,
    AUTH_006,
    AUTH_007,
    AUTH_008,
    AUTH_009,
    AUTH_010,
    AUTH_FLOW_CODES,
)
from .events import AUTH_EVENT_TYPES
from .schemas import (
    AuthMe,
    AuthRegistrationPolicy,
    ForgotPasswordRequest,
    LoginRequest,
    PasswordResetDelivery,
    PasswordResetMailContext,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenPair,
)
from .service import AuthService
from .uow import AuthUnitOfWork

AUTH_CODES = SECURITY_AUTH_CODES + AUTH_FLOW_CODES

__all__ = [
    "AuthService",
    "AuthUnitOfWork",
    "RegisterRequest",
    "AuthRegistrationPolicy",
    "ForgotPasswordRequest",
    "ResetPasswordRequest",
    "PasswordResetMailContext",
    "PasswordResetDelivery",
    "LoginRequest",
    "RefreshRequest",
    "TokenPair",
    "AuthMe",
    "get_current_principal",
    "AUTH_EVENT_TYPES",
    "AUTH_CODES",
    "AUTH_001",
    "AUTH_002",
    "AUTH_003",
    "AUTH_004",
    "AUTH_005",
    "AUTH_006",
    "AUTH_007",
    "AUTH_008",
    "AUTH_009",
    "AUTH_010",
]

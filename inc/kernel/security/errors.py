"""Security/authentication error-code registration."""

from inc.kernel.errors import ErrorCode

AUTH_002 = ErrorCode("AUTH_002", 401, "令牌已过期")
AUTH_003 = ErrorCode("AUTH_003", 401, "令牌无效")

AUTH_CODES: tuple[ErrorCode, ...] = (AUTH_002, AUTH_003)

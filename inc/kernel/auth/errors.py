"""Authentication flow error-code registration."""

from inc.kernel.errors import ErrorCode

AUTH_001 = ErrorCode("AUTH_001", 401, "凭据无效")
AUTH_004 = ErrorCode("AUTH_004", 409, "邮箱已注册")
AUTH_005 = ErrorCode("AUTH_005", 409, "用户名已占用")
AUTH_006 = ErrorCode("AUTH_006", 403, "用户被禁用或已注销")
AUTH_007 = ErrorCode("AUTH_007", 429, "登录尝试超限")

AUTH_008 = ErrorCode("AUTH_008", 403, "registration closed")
AUTH_009 = ErrorCode("AUTH_009", 400, "invalid or expired password reset token")
AUTH_010 = ErrorCode("AUTH_010", 429, "password reset requests are rate limited")

AUTH_FLOW_CODES: tuple[ErrorCode, ...] = (
    AUTH_001,
    AUTH_004,
    AUTH_005,
    AUTH_006,
    AUTH_007,
    AUTH_008,
    AUTH_009,
    AUTH_010,
)

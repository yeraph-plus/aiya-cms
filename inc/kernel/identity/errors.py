"""Identity error codes (see context/spec/kernel.md)."""

from inc.kernel.errors import ErrorCode

USER_001 = ErrorCode("USER_001", 404, "用户不存在")
USER_002 = ErrorCode("USER_002", 409, "不能修改当前用户状态")

IDENTITY_CODES: tuple[ErrorCode, ...] = (USER_001, USER_002)

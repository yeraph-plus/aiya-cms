"""Comment kernel error-code registration."""

from inc.kernel.errors import ErrorCode

COMMENT_001 = ErrorCode("COMMENT_001", 404, "comment not found")
COMMENT_002 = ErrorCode("COMMENT_002", 422, "comment target is missing or not allowed")
COMMENT_003 = ErrorCode("COMMENT_003", 422, "comment depth limit exceeded")
COMMENT_004 = ErrorCode("COMMENT_004", 429, "comment rate limit exceeded")
COMMENT_005 = ErrorCode("COMMENT_005", 409, "comment status transition is invalid")
COMMENT_006 = ErrorCode("COMMENT_006", 404, "comment target type is not registered")

COMMENT_CODES: tuple[ErrorCode, ...] = (
    COMMENT_001,
    COMMENT_002,
    COMMENT_003,
    COMMENT_004,
    COMMENT_005,
    COMMENT_006,
)

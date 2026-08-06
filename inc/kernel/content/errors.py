"""Content kernel error-code registration."""

from inc.kernel.errors import ErrorCode

CONTENT_001 = ErrorCode("CONTENT_001", 404, "内容类型未注册")
CONTENT_002 = ErrorCode("CONTENT_002", 409, "内容 slug 冲突")
CONTENT_003 = ErrorCode("CONTENT_003", 404, "内容不存在")
CONTENT_004 = ErrorCode("CONTENT_004", 409, "内容状态转换非法")
CONTENT_005 = ErrorCode("CONTENT_005", 422, "内容 data 或查询校验失败")

CONTENT_CODES: tuple[ErrorCode, ...] = (
    CONTENT_001,
    CONTENT_002,
    CONTENT_003,
    CONTENT_004,
    CONTENT_005,
)

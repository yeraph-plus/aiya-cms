"""Cache error-code registration."""

from inc.kernel.errors import ErrorCode

CACHE_001 = ErrorCode("CACHE_001", 500, "缓存后端不可用")
CACHE_CODES: tuple[ErrorCode, ...] = (CACHE_001,)

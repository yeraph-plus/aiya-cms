"""Error code value objects and the kernel-wide common codes.

Registered codes live in :data:`ErrorCode` instances; the registry that
tracks them lives in :mod:`inc.kernel.errors.registry`.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ErrorCode:
    """A registered error code: stable string, HTTP status, message template."""

    code: str
    http_status: int
    message_template: str


COMMON_001 = ErrorCode("COMMON_001", 422, "请求参数校验失败")
COMMON_403 = ErrorCode("COMMON_403", 403, "权限不足")
COMMON_404 = ErrorCode("COMMON_404", 404, "资源不存在")
COMMON_409 = ErrorCode("COMMON_409", 409, "状态冲突")
COMMON_429 = ErrorCode("COMMON_429", 429, "请求频率超限")
COMMON_500 = ErrorCode("COMMON_500", 500, "内部错误")

COMMON_CODES: tuple[ErrorCode, ...] = (
    COMMON_001,
    COMMON_403,
    COMMON_404,
    COMMON_409,
    COMMON_429,
    COMMON_500,
)

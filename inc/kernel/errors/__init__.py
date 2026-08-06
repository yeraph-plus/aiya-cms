"""Errors component public API (see context/spec/kernel.md)."""

from .codes import (
    COMMON_001,
    COMMON_403,
    COMMON_404,
    COMMON_409,
    COMMON_429,
    COMMON_500,
    COMMON_CODES,
    ErrorCode,
)
from .exceptions import AppError
from .handlers import (
    ErrorResponse,
    app_error_handler,
    request_validation_handler,
    unhandled_exception_handler,
)
from .registry import (
    clear_registry,
    get_error_code,
    register_error_codes,
    validate_registry,
)

__all__ = [
    "AppError",
    "ErrorCode",
    "ErrorResponse",
    "COMMON_001",
    "COMMON_403",
    "COMMON_404",
    "COMMON_409",
    "COMMON_429",
    "COMMON_500",
    "COMMON_CODES",
    "register_error_codes",
    "clear_registry",
    "validate_registry",
    "get_error_code",
    "app_error_handler",
    "unhandled_exception_handler",
    "request_validation_handler",
]

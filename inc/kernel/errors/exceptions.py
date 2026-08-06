"""The single business exception type."""

from typing import Any

from .codes import ErrorCode
from .registry import ErrorRegistry


class AppError(Exception):
    """Business error carrying a registered :class:`ErrorCode`."""

    def __init__(
        self,
        code: ErrorCode,
        *,
        detail: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        if not ErrorRegistry.has(code.code):
            raise ValueError(f"unregistered error code: {code.code} — register_error_codes() first")
        self.code = code
        self.detail = detail
        self.cause = cause
        super().__init__(code.code)

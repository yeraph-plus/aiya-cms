"""Structured errors and retry classification.

Contract source: context/spec/kernel/foundation.md §2, §3.

A KernelError carries a stable code, a transport-neutral category, a
client-safe message, correlation ids and optional details. Representations
never include details, stack traces or secrets. Concrete codes such as
``content.invalid_transition`` are owned by capabilities; kernel validates
the code shape and defines the shared categories.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

_ERROR_CODE = re.compile(r"^[a-z0-9]+(\.[a-z0-9_]+)+$")


class ErrorCategory(StrEnum):
    """Transport-neutral error category (foundation.md §2)."""

    VALIDATION = "validation"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    RATE_LIMITED = "rate_limited"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    INTERNAL = "internal"


class RetryCategory(StrEnum):
    """Retry classification used by outbox, workflow and task runtimes."""

    TRANSIENT = "transient"
    RATE_LIMITED = "rate_limited"
    CONFLICT = "conflict"
    PERMANENT = "permanent"
    CANCELLED = "cancelled"


_CATEGORY_TO_RETRY: dict[ErrorCategory, RetryCategory] = {
    ErrorCategory.VALIDATION: RetryCategory.PERMANENT,
    ErrorCategory.CONFLICT: RetryCategory.CONFLICT,
    ErrorCategory.NOT_FOUND: RetryCategory.PERMANENT,
    ErrorCategory.UNAUTHORIZED: RetryCategory.PERMANENT,
    ErrorCategory.FORBIDDEN: RetryCategory.PERMANENT,
    ErrorCategory.RATE_LIMITED: RetryCategory.RATE_LIMITED,
    ErrorCategory.DEPENDENCY_UNAVAILABLE: RetryCategory.TRANSIENT,
    ErrorCategory.INTERNAL: RetryCategory.TRANSIENT,
}


def validate_error_code(code: str) -> None:
    """Reject codes that cannot become stable registered error keys."""

    if not _ERROR_CODE.match(code):
        raise ValueError(f"invalid error code {code!r}: expected dotted lowercase key")


def classify_retry(error: BaseException) -> RetryCategory:
    """Map any exception to a retry category; unknown errors are transient."""

    if isinstance(error, KernelError):
        return _CATEGORY_TO_RETRY[error.category]
    return RetryCategory.TRANSIENT


class KernelError(Exception):
    """Base structured error shared by kernel and capabilities."""

    def __init__(
        self,
        *,
        code: str,
        category: ErrorCategory,
        message: str,
        details: Mapping[str, Any] | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        validate_error_code(code)
        super().__init__(message)
        self.code = code
        self.category = category
        self.message = message
        self.details = dict(details) if details else None
        self.request_id = request_id
        self.trace_id = trace_id

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        # Details may contain secrets; never include them in representations.
        return f"KernelError(code={self.code!r}, category={self.category.value!r})"

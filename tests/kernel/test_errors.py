"""Error contract tests (foundation.md §2)."""

from __future__ import annotations

import pytest

from inc.kernel.errors import (
    ErrorCategory,
    KernelError,
    RetryCategory,
    classify_retry,
    validate_error_code,
)


def test_error_code_validation() -> None:
    validate_error_code("content.invalid_transition")
    validate_error_code("kernel.registry_duplicate")
    for bad in ("", "Invalid", "no.dot.hyphen-key", "content.invalid-transition", "a..b"):
        with pytest.raises(ValueError):
            validate_error_code(bad)


def test_kernel_error_carries_fields() -> None:
    error = KernelError(
        code="kernel.registry_duplicate",
        category=ErrorCategory.INTERNAL,
        message="duplicate key",
        details={"key": "x"},
        request_id="req-1",
        trace_id="trace-1",
    )
    assert error.code == "kernel.registry_duplicate"
    assert error.category is ErrorCategory.INTERNAL
    assert str(error) == "duplicate key"
    assert error.details == {"key": "x"}
    assert error.request_id == "req-1"


def test_repr_never_leaks_details() -> None:
    error = KernelError(
        code="kernel.internal",
        category=ErrorCategory.INTERNAL,
        message="boom",
        details={"client_secret": "super-secret", "password": "hunter2"},
    )
    assert "super-secret" not in repr(error)
    assert "hunter2" not in repr(error)
    assert "boom" not in repr(error)


def test_retry_classification_mapping() -> None:
    assert classify_retry(ValueError("x")) is RetryCategory.TRANSIENT
    assert (
        classify_retry(
            KernelError(
                code="content.invalid_transition",
                category=ErrorCategory.VALIDATION,
                message="nope",
            )
        )
        is RetryCategory.PERMANENT
    )
    assert (
        classify_retry(
            KernelError(
                code="kernel.dep",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="down",
            )
        )
        is RetryCategory.TRANSIENT
    )
    assert (
        classify_retry(
            KernelError(
                code="kernel.rate",
                category=ErrorCategory.RATE_LIMITED,
                message="slow down",
            )
        )
        is RetryCategory.RATE_LIMITED
    )
    assert (
        classify_retry(
            KernelError(
                code="kernel.conflict",
                category=ErrorCategory.CONFLICT,
                message="conflict",
            )
        )
        is RetryCategory.CONFLICT
    )

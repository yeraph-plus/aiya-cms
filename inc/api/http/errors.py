"""HTTP error normalization.

Contract source: context/spec/http-openapi.md §3.

Every business error is a stable Error DTO: code, message, request_id and
optional safe details. Category maps to HTTP status; validation errors are
normalized; stack traces, SQL, secrets and provider payloads never leak.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from inc.kernel.errors import ErrorCategory, KernelError

_CATEGORY_STATUS = {
    ErrorCategory.VALIDATION: 422,
    ErrorCategory.CONFLICT: 409,
    ErrorCategory.NOT_FOUND: 404,
    ErrorCategory.UNAUTHORIZED: 401,
    ErrorCategory.FORBIDDEN: 403,
    ErrorCategory.RATE_LIMITED: 429,
    ErrorCategory.DEPENDENCY_UNAVAILABLE: 503,
    ErrorCategory.INTERNAL: 500,
}


def error_body(
    *,
    code: str,
    message: str,
    request_id: str | None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if request_id is not None:
        body["request_id"] = request_id
    if details:
        body["details"] = details
    return body


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def kernel_error_response(request: Request, exc: KernelError) -> JSONResponse:
    status = _CATEGORY_STATUS.get(exc.category, 500)
    return JSONResponse(
        status_code=status,
        content=error_body(
            code=exc.code,
            message=exc.message,
            request_id=_request_id(request),
            details=exc.details or None,
        ),
    )


def validation_error_response(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = []
    for item in exc.errors():
        loc = ".".join(str(part) for part in item.get("loc", ()) if part != "body")
        errors.append(f"{loc}: {item.get('msg', 'invalid')}")
    return JSONResponse(
        status_code=422,
        content=error_body(
            code="kernel.validation_error",
            message="; ".join(errors[:10]),
            request_id=_request_id(request),
        ),
    )


def pydantic_validation_response(request: Request, exc: ValidationError) -> JSONResponse:
    errors = []
    for item in exc.errors():
        loc = ".".join(str(part) for part in item.get("loc", ()) if part != "body")
        errors.append(f"{loc}: {item.get('msg', 'invalid')}")
    return JSONResponse(
        status_code=422,
        content=error_body(
            code="kernel.validation_error",
            message="; ".join(errors[:10]),
            request_id=_request_id(request),
        ),
    )


def internal_error_response(request: Request, exc: Exception) -> JSONResponse:
    from inc.kernel.observability import get_logger  # noqa: PLC0415

    get_logger("api.http").exception("unhandled error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content=error_body(
            code="kernel.internal_error",
            message="internal error",
            request_id=_request_id(request),
        ),
    )

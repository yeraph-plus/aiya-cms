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
from inc.kernel.security.redaction import redact

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
        # KernelError.details may carry secrets; redact before exposing.
        body["details"] = redact(details)
    return body


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def kernel_error_response(request: Request, exc: KernelError) -> JSONResponse:
    status = _CATEGORY_STATUS.get(exc.category, 500)
    response = JSONResponse(
        status_code=status,
        content=error_body(
            code=exc.code,
            message=exc.message,
            request_id=_request_id(request),
            details=exc.details or None,
        ),
    )
    if status == 401:
        response.headers["WWW-Authenticate"] = "Bearer"
    return response


def _validation_errors(exc: RequestValidationError | ValidationError) -> list[str]:
    errors = []
    for item in exc.errors():
        parts = [str(p) for p in item.get("loc", ())]
        if parts and parts[0] == "body":
            parts = parts[1:]
        loc = ".".join(parts)
        # Derive client-safe text from the stable error type, never from the
        # raw msg which can embed SQL fragments, file paths or provider
        # payloads.
        errors.append(f"{loc}: {_client_safe_type(item.get('type', 'invalid'))}")
    return errors


def _client_safe_type(error_type: str) -> str:
    known = {
        "missing": "required",
        "string_too_long": "too long",
        "string_too_short": "too short",
        "string_pattern_mismatch": "invalid format",
        "int_parsing": "invalid integer",
        "bool_parsing": "invalid boolean",
        "uuid_parsing": "invalid identifier",
        "url_parsing": "invalid url",
        "email": "invalid email",
        "value_error": "invalid value",
        "literal_error": "unsupported value",
        "greater_than": "out of range",
        "greater_than_equal": "out of range",
        "less_than": "out of range",
        "less_than_equal": "out of range",
    }
    return known.get(error_type, "invalid value")


def validation_error_response(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_body(
            code="kernel.validation_error",
            message="; ".join(_validation_errors(exc)[:10]),
            request_id=_request_id(request),
        ),
    )


def pydantic_validation_response(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_body(
            code="kernel.validation_error",
            message="; ".join(_validation_errors(exc)[:10]),
            request_id=_request_id(request),
        ),
    )


def internal_error_response(request: Request, exc: Exception) -> JSONResponse:
    from inc.kernel.observability import get_logger  # noqa: PLC0415

    get_logger("api.http").exception(
        "unhandled error",
        exc_info=exc,
        request_id=_request_id(request),
    )
    return JSONResponse(
        status_code=500,
        content=error_body(
            code="kernel.internal_error",
            message="internal error",
            request_id=_request_id(request),
        ),
    )

"""FastAPI exception handlers producing a stable ErrorResponse contract.

Registered by the api composition root (M1.12) and by tests.
"""

from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..logging import get_logger, get_request_id
from .codes import COMMON_001, COMMON_500, ErrorCode
from .exceptions import AppError
from .registry import get_error_code

logger = get_logger("aiya.errors")


class ErrorResponse(BaseModel):
    """Stable error response body: code/message/detail/request_id."""

    code: str
    message: str
    detail: dict[str, Any] | list[Any] | None = None
    request_id: str = ""


def _json(code: ErrorCode, message: str, request_id: str, detail: Any) -> JSONResponse:
    return JSONResponse(
        status_code=code.http_status,
        content=ErrorResponse(
            code=code.code,
            message=message,
            detail=detail,
            request_id=request_id,
        ).model_dump(),
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Render a registered AppError with its registered template and status."""
    code = get_error_code(exc.code.code)
    return _json(code, code.message_template, get_request_id(), exc.detail)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all: log the stack, return COMMON_500 without leaking internals."""
    logger.error(
        "unhandled exception",
        exc_info=(type(exc), exc, exc.__traceback__),
        request_id=get_request_id(),
    )
    return _json(COMMON_500, COMMON_500.message_template, get_request_id(), None)


async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Wrap Pydantic validation errors as COMMON_001 with field error detail."""
    detail = [
        jsonable_encoder({key: value for key, value in error.items() if key != "ctx"})
        for error in exc.errors()
    ]
    return _json(
        COMMON_001,
        COMMON_001.message_template,
        get_request_id(),
        detail,
    )

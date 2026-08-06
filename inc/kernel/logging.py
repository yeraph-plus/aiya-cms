"""Structured logging: one setup entry, one getter, request context.

dev renders colored console lines; prod/test render JSON lines. The
request-scoped ``request_id`` contextvar is set by the api middleware via
:func:`bind_context` and read by error handlers via :func:`get_request_id`.
"""

import contextvars
import logging as stdlib_logging
import sys
from typing import Any, cast

import structlog
from structlog.typing import WrappedLogger

from .config import Settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")

_configured = False


class _CurrentStreamHandler(stdlib_logging.StreamHandler[Any]):
    """Handler that always writes to the *current* sys.stdout.

    Reads sys.stdout at emit time so pytest capsys captures every test's
    output even though the handler is created once (idempotent setup).
    """

    def emit(self, record: stdlib_logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            sys.stdout.write(msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)


def setup_logging(settings: Settings) -> None:
    """Configure structlog once per process; repeated calls are no-ops."""
    global _configured
    if _configured:
        # Test clients and embedding applications may temporarily replace
        # root handlers. Keep the idempotent setup observable without adding
        # duplicate handlers or reconfiguring structlog processors.
        root = stdlib_logging.getLogger()
        root.disabled = False
        root.setLevel(getattr(stdlib_logging, settings.log_level.upper(), stdlib_logging.INFO))
        if not any(isinstance(handler, _CurrentStreamHandler) for handler in root.handlers):
            root.addHandler(_CurrentStreamHandler())
        return
    _configured = True

    level = getattr(stdlib_logging, settings.log_level.upper(), stdlib_logging.INFO)
    root = stdlib_logging.getLogger()
    root.setLevel(level)
    root.addHandler(_CurrentStreamHandler())

    if settings.env == "dev":
        renderer: WrappedLogger = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger for ``name``."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


def bind_context(**kv: str) -> None:
    """Bind key/values into the log context (request_id, principal_id, ...)."""
    if "request_id" in kv:
        request_id_var.set(kv["request_id"])
    structlog.contextvars.bind_contextvars(**kv)


def get_request_id() -> str:
    """Return the current request_id (empty when none bound)."""
    return request_id_var.get()

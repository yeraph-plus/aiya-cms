"""Structured logging with secret redaction.

Contract source: context/spec/kernel/observability.md §1.

Logs carry request/trace/correlation ids, owner, operation and duration;
workflow/activity logs add instance, step and attempt. Secret-bearing keys
are masked in every event dict. Logging failures never change business
transaction results (structlog processors are best-effort).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, MutableMapping
from typing import Any, cast

import structlog

from inc.kernel.security.redaction import redact

_LOG_NAMES_TO_LEVELS: dict[str, int] = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}


def _redact_processor(
    logger: Any,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], redact(dict(event_dict)))


def configure_logging(*, level: str = "INFO", json_output: bool = True) -> None:
    """Configure structlog and the stdlib logging bridge once at boot."""

    logging.basicConfig(
        level=_LOG_NAMES_TO_LEVELS.get(level.upper(), logging.INFO),
        format="%(message)s",
        force=True,
    )
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _redact_processor,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)

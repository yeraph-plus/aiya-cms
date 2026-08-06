"""Secret redaction.

Contract source: context/spec/kernel/foundation.md §1/§5 and
context/spec/kernel/observability.md §1.

Values under secret-ish keys are masked recursively so config, provider
errors and log payloads never leak credentials. Masking is lossy by design:
callers should pass only the fields a diagnostic or log event needs.
"""

from __future__ import annotations

import re
from typing import Any

try:  # pydantic is a hard dependency; guard import for tooling only
    from pydantic import SecretBytes, SecretStr
except ImportError:  # pragma: no cover
    SecretBytes = ()  # type: ignore[assignment,misc]
    SecretStr = ()  # type: ignore[assignment,misc]

_SECRET_KEY = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|apikey|authorization|cookie|"
    r"client[_-]?secret|signature|credential|private[_-]?key|refresh[_-]?token)",  # noqa: S105
    re.IGNORECASE,
)

MASK = "[REDACTED]"


def is_secret_key(key: str) -> bool:
    return _SECRET_KEY.search(key) is not None


def redact(value: Any, *, key: str | None = None, depth: int = 0) -> Any:
    """Return a copy of *value* with secret-bearing values masked."""

    if depth > 16:
        return MASK
    if key is not None and is_secret_key(key):
        return MASK
    if isinstance(value, (SecretStr, SecretBytes)):
        return MASK
    if isinstance(value, dict):
        return {k: redact(v, key=str(k), depth=depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, depth=depth + 1) for v in value]
    return value

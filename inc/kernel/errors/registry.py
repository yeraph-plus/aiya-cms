"""Error code registry: codes are registered before use, duplicates fail fast.

Wiring imports every component's codes and calls :func:`register_error_codes`;
:func:`validate_registry` then fails startup if the canonical set is incomplete.
"""

from collections.abc import Iterable

from .codes import ErrorCode


class ErrorRegistry:
    """Process-wide registry of registered error codes."""

    _codes: dict[str, ErrorCode] = {}

    @classmethod
    def register(cls, *codes: ErrorCode) -> None:
        for code in codes:
            if code.code in cls._codes:
                raise ValueError(f"duplicate error code: {code.code}")
            cls._codes[code.code] = code

    @classmethod
    def has(cls, code: str) -> bool:
        return code in cls._codes

    @classmethod
    def get(cls, code: str) -> ErrorCode:
        return cls._codes[code]

    @classmethod
    def validate(cls, required: Iterable[ErrorCode]) -> None:
        missing = [code.code for code in required if code.code not in cls._codes]
        if missing:
            raise RuntimeError(f"unregistered error codes: {', '.join(sorted(missing))}")

    @classmethod
    def clear(cls) -> None:
        cls._codes.clear()


def register_error_codes(*codes: ErrorCode) -> None:
    """Register error codes; raises on duplicate code string."""
    ErrorRegistry.register(*codes)


def clear_registry() -> None:
    """Reset the registry (tests and startup re-wiring only)."""
    ErrorRegistry.clear()


def validate_registry(required: Iterable[ErrorCode]) -> None:
    """Fail-fast when any required code is missing from the registry."""
    ErrorRegistry.validate(required)


def get_error_code(code: str) -> ErrorCode:
    """Return the registered code; raises KeyError if unknown."""
    return ErrorRegistry.get(code)

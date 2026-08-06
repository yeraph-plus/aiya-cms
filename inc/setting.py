"""Application-context facade for typed runtime-setting reads.

The facade is intentionally bound per request/task; it is not a process-global
settings service locator.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

from inc.kernel.settings import SettingField, SettingsService

_reader: ContextVar[SettingsService | None] = ContextVar("aiya_setting_reader", default=None)


def bind(reader: SettingsService) -> Token[SettingsService | None]:
    return _reader.set(reader)


def reset(token: Token[SettingsService | None]) -> None:
    _reader.reset(token)


async def get[T](field: SettingField[T]) -> T:
    """Resolve a declared field from the current application context."""

    reader = _reader.get()
    if reader is None:
        raise RuntimeError("runtime settings are not bound to the current context")
    return await reader.get_field(field)

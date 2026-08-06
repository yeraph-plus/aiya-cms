"""In-process cache used by tests and as Redis degradation target."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic

from inc.kernel.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class _Entry:
    value: str
    expires_at: float | None


class MemoryCache:
    """Async-safe process-local cache with per-key single-flight locks."""

    def __init__(self) -> None:
        self._values: dict[str, _Entry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def get(self, key: str) -> str | None:
        entry = self._values.get(key)
        if entry is None:
            logger.debug("cache_miss", key=key)
            return None
        if entry.expires_at is not None and entry.expires_at <= monotonic():
            self._values.pop(key, None)
            logger.debug("cache_miss", key=key, reason="expired")
            return None
        logger.debug("cache_hit", key=key)
        return entry.value

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        expires_at = None if ttl is None else monotonic() + max(ttl, 0)
        self._values[key] = _Entry(value, expires_at)

    async def delete(self, key: str) -> None:
        self._values.pop(key, None)

    async def increment(self, key: str, ttl: int) -> int:
        lock = await self._lock_for(key)
        async with lock:
            current = await self.get(key)
            value = int(current or 0) + 1
            await self.set(key, str(value), ttl)
            return value

    async def health(self) -> bool:
        """Memory cache is always available."""
        return True

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._locks_guard:
            return self._locks.setdefault(key, asyncio.Lock())

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Awaitable[str]],
        ttl: int,
    ) -> str:
        cached = await self.get(key)
        if cached is not None:
            return cached
        lock = await self._lock_for(key)
        async with lock:
            cached = await self.get(key)
            if cached is not None:
                return cached
            value = await factory()
            await self.set(key, value, ttl)
            return value

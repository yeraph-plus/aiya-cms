"""Redis-backed cache with transparent MemoryCache degradation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis

from inc.kernel.logging import get_logger

from .memory import MemoryCache

logger = get_logger(__name__)


class RedisCache:
    def __init__(self, client: Redis, *, fallback: MemoryCache | None = None) -> None:
        self._client = client
        self._fallback = fallback or MemoryCache()
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()
        self._degraded = False
        self._warned = False

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._locks_guard:
            return self._locks.setdefault(key, asyncio.Lock())

    async def _mark_unavailable(self, exc: Exception) -> None:
        self._degraded = True
        if not self._warned:
            self._warned = True
            logger.warning("cache_backend_unavailable", backend="redis", error=str(exc))

    async def get(self, key: str) -> str | None:
        if self._degraded:
            return await self._fallback.get(key)
        try:
            value = await self._client.get(key)
        except Exception as exc:  # redis errors must never reach business code
            await self._mark_unavailable(exc)
            return await self._fallback.get(key)
        if value is None:
            logger.debug("cache_miss", key=key)
            return None
        logger.debug("cache_hit", key=key)
        return value.decode() if isinstance(value, bytes) else str(value)

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        if self._degraded:
            await self._fallback.set(key, value, ttl)
            return
        try:
            if ttl is None:
                await self._client.set(key, value)
            else:
                await self._client.set(key, value, ex=max(ttl, 0))
        except Exception as exc:
            await self._mark_unavailable(exc)
            await self._fallback.set(key, value, ttl)

    async def delete(self, key: str) -> None:
        if self._degraded:
            await self._fallback.delete(key)
            return
        try:
            await self._client.delete(key)
        except Exception as exc:
            await self._mark_unavailable(exc)
            await self._fallback.delete(key)

    async def increment(self, key: str, ttl: int) -> int:
        if self._degraded:
            return await self._fallback.increment(key, ttl)
        try:
            pipe = self._client.pipeline(transaction=True)
            pipe.incr(key)
            pipe.expire(key, max(ttl, 0))
            result = await pipe.execute()
            return int(result[0])
        except Exception as exc:
            await self._mark_unavailable(exc)
            return await self._fallback.increment(key, ttl)

    async def health(self) -> bool:
        if self._degraded:
            return False
        try:
            await self._client.ping()
            return True
        except Exception as exc:
            await self._mark_unavailable(exc)
            return False

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Awaitable[str]],
        ttl: int,
    ) -> str:
        if self._degraded:
            return await self._fallback.get_or_set(key, factory, ttl)
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

    async def close(self) -> None:
        await self._client.aclose()

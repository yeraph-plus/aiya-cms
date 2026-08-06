"""Cache contract tests (see context/spec/kernel.md)."""

import asyncio

import pytest

from inc.kernel.cache import MemoryCache, cache_key


async def test_memory_cache_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 100.0
    monkeypatch.setattr("inc.kernel.cache.memory.monotonic", lambda: now)
    cache = MemoryCache()
    await cache.set("k", "v", ttl=5)
    assert await cache.get("k") == "v"
    now = 105.0
    assert await cache.get("k") is None


async def test_memory_cache_get_or_set_is_single_flight() -> None:
    cache = MemoryCache()
    calls = 0

    async def factory() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return "value"

    values = await asyncio.gather(*(cache.get_or_set("same", factory, ttl=30) for _ in range(20)))
    assert values == ["value"] * 20
    assert calls == 1


async def test_memory_cache_increment_is_atomic() -> None:
    cache = MemoryCache()

    values = await asyncio.gather(*(cache.increment("attempts", 60) for _ in range(20)))

    assert sorted(values) == list(range(1, 21))
    assert await cache.get("attempts") == "20"


async def test_memory_cache_delete_and_key_namespace() -> None:
    cache = MemoryCache()
    await cache.set(cache_key("users", "1"), "value", ttl=None)
    assert await cache.get("aiya:users:1") == "value"
    await cache.delete("aiya:users:1")
    assert await cache.get("aiya:users:1") is None
    assert cache_key("users", "1") == "aiya:users:1"

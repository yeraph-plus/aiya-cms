"""Cache protocol and key namespace helper."""

from collections.abc import Awaitable, Callable
from typing import Protocol


class Cache(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl: int | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def increment(self, key: str, ttl: int) -> int: ...

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Awaitable[str]],
        ttl: int,
    ) -> str: ...


def cache_key(*parts: str) -> str:
    """Build a namespaced key and prevent accidental double-prefixing."""

    if not parts or any(not part or not part.strip(":") for part in parts):
        raise ValueError("cache key parts must be non-empty")
    clean = [part.strip(":") for part in parts]
    if clean[0] == "aiya":
        return ":".join(clean)
    return ":".join(("aiya", *clean))

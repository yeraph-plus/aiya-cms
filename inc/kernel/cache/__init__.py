"""Cache abstraction (M1.3)."""

from .errors import CACHE_001, CACHE_CODES
from .factory import build_cache
from .memory import MemoryCache
from .protocol import Cache, cache_key
from .redis import RedisCache

__all__ = [
    "Cache",
    "MemoryCache",
    "RedisCache",
    "build_cache",
    "cache_key",
    "CACHE_001",
    "CACHE_CODES",
]

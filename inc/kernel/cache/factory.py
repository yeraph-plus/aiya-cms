"""Cache backend factory."""

from redis.asyncio import Redis

from inc.kernel.config import Settings
from inc.kernel.logging import get_logger

from .memory import MemoryCache
from .protocol import Cache
from .redis import RedisCache

logger = get_logger(__name__)


def build_cache(settings: Settings) -> Cache:
    """Construct the configured backend; constructor failures fall back to memory."""

    if settings.cache_backend == "memory":
        return MemoryCache()
    try:
        client = Redis.from_url(settings.redis_url, decode_responses=True)
    except Exception as exc:
        logger.warning("cache_backend_unavailable", backend="redis", error=str(exc))
        return MemoryCache()
    return RedisCache(client)

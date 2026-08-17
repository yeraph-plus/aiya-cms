"""Administrator session store expiry and Redis boundary contracts."""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

import pytest

from inc.api.http.admin_session_store import AdminSessionStore


async def test_memory_sessions_expire_and_transactions_are_single_use(clock: Any) -> None:
    store = AdminSessionStore(
        secret="test-admin-session-secret",
        idle_seconds=60,
        absolute_seconds=120,
        clock=clock,
    )

    token, csrf = await store.create("subject-1")
    loaded = await store.load(token)
    assert loaded is not None
    assert loaded.subject_id == "subject-1"
    assert loaded.csrf_token == csrf

    transaction = await store.create_transaction(redirect_uri="http://admin.test/callback")
    assert await store.consume_transaction(transaction.state) == transaction
    assert await store.consume_transaction(transaction.state) is None

    clock.advance(timedelta(seconds=61))
    assert await store.load(token) is None


async def test_configured_redis_failure_does_not_fallback_to_memory(
    monkeypatch: Any,
) -> None:
    from redis.asyncio import Redis

    class BrokenRedis:
        async def set(self, *args: Any, **kwargs: Any) -> None:
            raise ConnectionError("redis unavailable")

    monkeypatch.setattr(Redis, "from_url", lambda *args, **kwargs: BrokenRedis())
    store = AdminSessionStore(secret="test-admin-session-secret", redis_url="redis://broken/0")

    with pytest.raises(ConnectionError, match="redis unavailable"):
        await store.create("subject-1")
    assert store._memory == {}


async def test_redis_readiness_propagates_connection_failure(monkeypatch: Any) -> None:
    from redis.asyncio import Redis

    class BrokenRedis:
        async def ping(self) -> bool:
            raise ConnectionError("redis unavailable")

    monkeypatch.setattr(Redis, "from_url", lambda *args, **kwargs: BrokenRedis())
    store = AdminSessionStore(secret="test-admin-session-secret", redis_url="redis://broken/0")

    with pytest.raises(ConnectionError, match="redis unavailable"):
        await store.check_ready()


def _required_redis_url() -> str:
    """Return the production Redis URL used by the acceptance boundary.

    This test is part of the release gate, so a missing URL is a configuration
    failure rather than a reason to silently skip real Redis coverage.
    """

    value = os.environ.get("AIYA_REDIS_URL")
    if not value:
        pytest.fail("AIYA_REDIS_URL is required for real Redis acceptance coverage")
    return value


async def test_redis_sessions_survive_store_recreation_and_revoke() -> None:
    redis_url = _required_redis_url()
    from redis.asyncio import Redis

    first = AdminSessionStore(secret="shared-secret", redis_url=redis_url)
    second = AdminSessionStore(secret="shared-secret", redis_url=redis_url)
    token, _ = await first.create("subject-redis")
    try:
        loaded = await second.load(token)
        assert loaded is not None
        assert loaded.subject_id == "subject-redis"
    finally:
        await first.revoke(token)
        client = Redis.from_url(redis_url)
        await client.aclose()

"""Redis-backed administrator sessions with an in-memory test fallback."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import asdict, dataclass
from typing import Any

from inc.kernel.time import SYSTEM_CLOCK, Clock


@dataclass(frozen=True, slots=True)
class AdminSessionRecord:
    subject_id: str
    csrf_token: str
    created_at: int
    last_seen: int


@dataclass(frozen=True, slots=True)
class AdminAuthTransaction:
    """One-time PKCE transaction state kept outside the browser."""

    state: str
    nonce: str
    code_verifier: str
    redirect_uri: str
    created_at: int


class AdminSessionStore:
    def __init__(
        self,
        *,
        secret: str,
        idle_seconds: int = 8 * 3600,
        absolute_seconds: int = 14 * 86400,
        redis_url: str | None = None,
        clock: Clock | None = None,
    ) -> None:
        if not secret:
            raise ValueError("admin session secret must not be empty")
        self._secret = secret.encode("utf-8")
        self._idle = idle_seconds
        self._absolute = absolute_seconds
        self._clock = clock or SYSTEM_CLOCK
        self._redis_url = redis_url
        self._memory: dict[str, AdminSessionRecord] = {}
        self._transactions: dict[str, AdminAuthTransaction] = {}
        self._redis: Any | None = None

    def _key(self, token: str) -> str:
        return "aiya:admin-session:" + hashlib.sha256(token.encode()).hexdigest()

    async def _client(self) -> Any | None:
        if not self._redis_url:
            return None
        if self._redis is None:
            from redis.asyncio import Redis

            self._redis = Redis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    async def check_ready(self) -> bool:
        """Probe the configured store; memory fallback is healthy in dev/test."""

        client = await self._client()
        if client is None:
            return True
        await client.ping()
        return True

    async def close(self) -> None:
        if self._redis is not None and hasattr(self._redis, "aclose"):
            await self._redis.aclose()
            self._redis = None

    def _sign(self, value: str) -> str:
        digest = hmac.new(self._secret, value.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{value}.{digest}"

    def _verify(self, token: str) -> str | None:
        value, separator, digest = token.partition(".")
        if not separator or not hmac.compare_digest(
            digest, hmac.new(self._secret, value.encode("utf-8"), hashlib.sha256).hexdigest()
        ):
            return None
        return value

    async def create(self, subject_id: str) -> tuple[str, str]:
        now = int(self._clock.utc_now().timestamp())
        raw = secrets.token_urlsafe(32)
        token = self._sign(raw)
        csrf = secrets.token_urlsafe(24)
        record = AdminSessionRecord(
            subject_id=subject_id, csrf_token=csrf, created_at=now, last_seen=now
        )
        client = await self._client()
        if client is None:
            self._memory[raw] = record
        else:
            import json

            await client.set(self._key(raw), json.dumps(asdict(record)), ex=self._absolute)
        return token, csrf

    async def load(self, token: str | None) -> AdminSessionRecord | None:
        if not token:
            return None
        raw = self._verify(token)
        if raw is None:
            return None
        client = await self._client()
        now = int(self._clock.utc_now().timestamp())
        if client is None:
            record = self._memory.get(raw)
        else:
            import json

            value = await client.get(self._key(raw))
            record = AdminSessionRecord(**json.loads(value)) if value else None
        if (
            record is None
            or now - record.created_at > self._absolute
            or now - record.last_seen > self._idle
        ):
            await self.revoke(token)
            return None
        refreshed = AdminSessionRecord(record.subject_id, record.csrf_token, record.created_at, now)
        if client is None:
            self._memory[raw] = refreshed
        else:
            import json

            remaining = max(1, min(self._idle, self._absolute - (now - record.created_at)))
            await client.set(self._key(raw), json.dumps(asdict(refreshed)), ex=remaining)
        return refreshed

    async def revoke(self, token: str | None) -> None:
        if not token:
            return
        raw = self._verify(token)
        if raw is None:
            return
        client = await self._client()
        if client is None:
            self._memory.pop(raw, None)
        else:
            await client.delete(self._key(raw))

    async def create_transaction(self, *, redirect_uri: str) -> AdminAuthTransaction:
        """Create a short-lived state/nonce/verifier tuple for an auth start."""

        transaction = AdminAuthTransaction(
            state=secrets.token_urlsafe(32),
            nonce=secrets.token_urlsafe(24),
            code_verifier=secrets.token_urlsafe(48),
            redirect_uri=redirect_uri,
            created_at=int(self._clock.utc_now().timestamp()),
        )
        client = await self._client()
        if client is None:
            self._transactions[transaction.state] = transaction
        else:
            import json

            await client.set(
                self._transaction_key(transaction.state),
                json.dumps(asdict(transaction)),
                ex=600,
            )
        return transaction

    async def consume_transaction(self, state: str) -> AdminAuthTransaction | None:
        """Atomically consume a transaction; replay returns ``None``."""

        if not state:
            return None
        client = await self._client()
        if client is None:
            transaction = self._transactions.pop(state, None)
        else:
            import json

            key = self._transaction_key(state)
            # Redis GETDEL is available on supported Redis versions.  Keep a
            # small fallback for older test doubles.
            value = await client.getdel(key) if hasattr(client, "getdel") else await client.get(key)
            if value is not None and not hasattr(client, "getdel"):
                await client.delete(key)
            transaction = AdminAuthTransaction(**json.loads(value)) if value else None
        now = int(self._clock.utc_now().timestamp())
        if transaction is None or now - transaction.created_at > 600:
            return None
        return transaction

    def _transaction_key(self, state: str) -> str:
        return "aiya:admin-auth-transaction:" + hashlib.sha256(state.encode()).hexdigest()

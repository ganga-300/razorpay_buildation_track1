"""Idempotency keys for money actions.

A retried `create_order` must never produce a second charge. Three layers guard
that, deliberately overlapping:

1. **This store** (Redis when configured) reserves the key before the provider
   call, so a concurrent retry sees the reservation and refuses rather than
   racing.
2. **A unique index** on `orders.idempotency_key` in the database, which holds
   even if the store is unavailable or has been flushed.
3. **A lookup** of the existing order on replay, so a repeat returns the
   original order instead of an error.

Redis is optional. Without `REDIS_URL` the process-local fallback is used, which
is correct for a single worker and documented as such — the database index is
what makes the multi-worker case safe regardless.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Protocol

from app.config import settings

logger = logging.getLogger(__name__)

# How long a key stays reserved. Long enough to outlive a slow provider call and
# a retry, short enough that a crashed request does not block the key forever.
DEFAULT_TTL_SECONDS = 900

IN_FLIGHT = "__in_flight__"


class IdempotencyStore(Protocol):
    async def reserve(self, key: str, ttl: int = DEFAULT_TTL_SECONDS) -> bool:
        """True if this caller won the reservation, False if it already existed."""
        ...

    async def get(self, key: str) -> str | None: ...

    async def record(self, key: str, value: str, ttl: int = DEFAULT_TTL_SECONDS) -> None:
        """Attach the result (an order id) to a key already reserved."""
        ...

    async def release(self, key: str) -> None:
        """Drop a reservation so a genuine retry can proceed after a failure."""
        ...


class MemoryIdempotencyStore:
    """Process-local fallback. Correct for one worker; not shared across them."""

    def __init__(self) -> None:
        self._values: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    def _purge(self) -> None:
        now = time.monotonic()
        for key in [k for k, (_, exp) in self._values.items() if exp <= now]:
            del self._values[key]

    async def reserve(self, key: str, ttl: int = DEFAULT_TTL_SECONDS) -> bool:
        async with self._lock:
            self._purge()
            if key in self._values:
                return False
            self._values[key] = (IN_FLIGHT, time.monotonic() + ttl)
            return True

    async def get(self, key: str) -> str | None:
        async with self._lock:
            self._purge()
            entry = self._values.get(key)
            return entry[0] if entry else None

    async def record(self, key: str, value: str, ttl: int = DEFAULT_TTL_SECONDS) -> None:
        async with self._lock:
            self._values[key] = (value, time.monotonic() + ttl)

    async def release(self, key: str) -> None:
        async with self._lock:
            self._values.pop(key, None)


class RedisIdempotencyStore:
    """Redis-backed store. `SET NX` makes the reservation atomic across workers."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._redis: object | None = None

    async def _client(self):  # type: ignore[no-untyped-def]
        if self._redis is None:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(self._url, decode_responses=True)
        return self._redis

    async def reserve(self, key: str, ttl: int = DEFAULT_TTL_SECONDS) -> bool:
        client = await self._client()
        return bool(await client.set(key, IN_FLIGHT, nx=True, ex=ttl))  # type: ignore[attr-defined]

    async def get(self, key: str) -> str | None:
        client = await self._client()
        return await client.get(key)  # type: ignore[attr-defined]

    async def record(self, key: str, value: str, ttl: int = DEFAULT_TTL_SECONDS) -> None:
        client = await self._client()
        await client.set(key, value, ex=ttl)  # type: ignore[attr-defined]

    async def release(self, key: str) -> None:
        client = await self._client()
        await client.delete(key)  # type: ignore[attr-defined]


_store: IdempotencyStore | None = None


def get_store() -> IdempotencyStore:
    """Process-wide store: Redis when configured, memory otherwise."""
    global _store
    if _store is None:
        if settings.redis_url:
            logger.info("Idempotency: using Redis at %s", settings.redis_url)
            _store = RedisIdempotencyStore(settings.redis_url)
        else:
            logger.warning(
                "Idempotency: REDIS_URL unset, using the in-process store. "
                "Correct for a single worker; the unique index on "
                "orders.idempotency_key covers the multi-worker case."
            )
            _store = MemoryIdempotencyStore()
    return _store


def reset_store() -> None:
    """Drop the cached store. Used by tests."""
    global _store
    _store = None

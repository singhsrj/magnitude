"""Everything Magnitude keeps in Redis (Upstash).

  profile:{player} serialized profile JSON                      30s   best-effort cache
  rl:{key}         fixed-window rate-limit counters             60s   best-effort, fails open

Both are best-effort: Redis errors are swallowed and the database answers instead, so an Upstash blip
slows things down instead of breaking them. Upstash bills per command, so related commands
are pipelined and TTLs are always set. (Phase 4 needs no Redis for correctness: sessions live in Postgres.)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

log = logging.getLogger("cache")


class Cache:
    def __init__(self, redis: Redis, *, profile_ttl: int) -> None:
        self.redis = redis
        self.profile_ttl = profile_ttl

    # ---- profile (best-effort)
    async def get_profile(self, player_id: Any) -> str | None:
        try:
            return await self.redis.get(f"profile:{player_id}")
        except RedisError as exc:
            log.warning("profile cache read failed: %s", exc)
            return None

    async def put_profile(self, player_id: Any, body: str) -> None:
        try:
            await self.redis.set(f"profile:{player_id}", body, ex=self.profile_ttl)
        except RedisError as exc:
            log.warning("profile cache write failed: %s", exc)

    async def drop_profile(self, player_id: Any) -> None:
        try:
            await self.redis.delete(f"profile:{player_id}")
        except RedisError as exc:
            log.warning("profile cache invalidate failed: %s", exc)

    # ---- rate limiting (fails open)
    async def hit(self, key: str, window_seconds: int) -> int | None:
        """Count one request in a fixed window. Returns the count, or None if Redis is unavailable.

        SET NX EX creates the counter with its TTL already attached, so a crash between commands
        can never leave a counter that never expires.
        """
        try:
            async with self.redis.pipeline(transaction=False) as pipe:
                pipe.set(key, 0, ex=window_seconds, nx=True)
                pipe.incr(key)
                results = await pipe.execute()
            return int(results[1])
        except RedisError as exc:
            log.warning("rate limiter unavailable, allowing request: %s", exc)
            return None

    async def ping(self) -> bool:
        try:
            return bool(await self.redis.ping())
        except RedisError:
            return False

"""Everything Magnitude keeps in Redis (Upstash).

  prob:{id}        a problem we issued, with its answer         30s   required for correctness
  profile:{player} serialized profile JSON                      30s   best-effort cache
  daily:{date}     the day's 10 problems, with answers          36h   best-effort cache
  rl:{key}         fixed-window rate-limit counters             60s   best-effort, fails open

Required keys let errors propagate (the route turns them into 503). Best-effort keys swallow
Redis errors and fall back to the database or the problem service, so an Upstash blip
slows things down instead of breaking them. Upstash bills per command, so related commands
are pipelined and TTLs are always set.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

log = logging.getLogger("cache")


class Cache:
    def __init__(self, redis: Redis, *, problem_ttl: int, profile_ttl: int, daily_ttl: int) -> None:
        self.redis = redis
        self.problem_ttl = problem_ttl
        self.profile_ttl = profile_ttl
        self.daily_ttl = daily_ttl

    # ---- issued problems (required)
    async def put_problem(self, problem_id: str, record: dict[str, Any]) -> None:
        await self.redis.set(f"prob:{problem_id}", json.dumps(record), ex=self.problem_ttl)

    async def take_problem(self, problem_id: str) -> dict[str, Any] | None:
        """Fetch and delete in one step, so a problem can be answered exactly once."""
        raw = await self.redis.getdel(f"prob:{problem_id}")
        return json.loads(raw) if raw else None

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

    # ---- daily set (best-effort)
    async def get_daily(self, day: str) -> list[dict[str, Any]] | None:
        try:
            raw = await self.redis.get(f"daily:{day}")
            return json.loads(raw) if raw else None
        except (RedisError, ValueError) as exc:
            log.warning("daily cache read failed: %s", exc)
            return None

    async def put_daily(self, day: str, problems: list[dict[str, Any]]) -> None:
        try:
            await self.redis.set(f"daily:{day}", json.dumps(problems), ex=self.daily_ttl)
        except RedisError as exc:
            log.warning("daily cache write failed: %s", exc)

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

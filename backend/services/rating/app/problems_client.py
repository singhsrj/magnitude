from __future__ import annotations

import logging
from typing import Protocol

import httpx

from magnitude_engine import Expr, Problem

log = logging.getLogger("problems-client")


class UpstreamError(Exception):
    """The problem service couldn't be reached or answered badly."""


class ProblemSource(Protocol):
    async def generate(self, skill: str, target_rating: float) -> Problem: ...
    async def daily(self, day: str) -> list[Problem]: ...
    async def healthy(self) -> bool: ...
    async def aclose(self) -> None: ...


def problem_from_json(d: dict) -> Problem:
    return Problem(
        id=d["id"],
        skill=d["skill"],
        left=Expr(d["left"]["text"], d["left"]["value"]),
        right=Expr(d["right"]["text"], d["right"]["value"]),
        rating=d["rating"],
        answer=d["answer"],
    )


class HttpProblemClient:
    """Talks to the problem service over HTTP with a short timeout and one retry."""

    def __init__(self, base_url: str, api_key: str, *, timeout: float = 3.0, attempts: int = 2) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, headers={"X-Internal-Key": api_key}, timeout=timeout)
        self._attempts = attempts

    async def _request(self, method: str, url: str, **kwargs) -> dict:
        last: Exception | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                resp = await self._client.request(method, url, **kwargs)
                if resp.status_code >= 500:
                    raise UpstreamError(f"problem service returned {resp.status_code}")
                resp.raise_for_status()
                return resp.json()
            except (httpx.TransportError, UpstreamError) as exc:
                last = exc
                log.warning("problem service call failed (attempt %d/%d): %s", attempt, self._attempts, exc)
            except httpx.HTTPStatusError as exc:  # 4xx: our bug, retrying won't help
                raise UpstreamError(f"problem service rejected the request: {exc.response.status_code}") from exc
        raise UpstreamError("problem service unavailable") from last

    async def generate(self, skill: str, target_rating: float) -> Problem:
        data = await self._request("POST", "/internal/problems", json={"skill": skill, "target_rating": target_rating})
        return problem_from_json(data)

    async def daily(self, day: str) -> list[Problem]:
        data = await self._request("GET", f"/internal/daily/{day}")
        return [problem_from_json(p) for p in data["problems"]]

    async def healthy(self) -> bool:
        try:
            resp = await self._client.get("/healthz")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()

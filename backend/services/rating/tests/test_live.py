"""Runs against a REAL stack (Postgres row locks, Redis), not SQLite. Skipped unless LIVE_API_URL is set:

    docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
    LIVE_API_URL=http://localhost:8000 pytest tests/test_live.py -v

Each test signs up a player, and sign-ups are limited per IP (SIGNUP_LIMIT_PER_HOUR, 10 by default): clear the
local counters between runs with `docker compose ... exec redis redis-cli flushall`, or raise the limit.
"""
import asyncio
import os

import httpx
import pytest

from tests.test_sync import Browser, assert_profile_matches, daily_events, now_ms, utc_day

LIVE = os.environ.get("LIVE_API_URL")
pytestmark = pytest.mark.skipif(not LIVE, reason="set LIVE_API_URL to run against a live stack")

FAST = [250, 300, 400, 500, 600]  # short think times: the ticket is brand new, so `at` can't be far in the past


@pytest.fixture
async def live():
    async with httpx.AsyncClient(base_url=LIVE, timeout=30) as c:
        r = await c.post("/v1/players")
        assert r.status_code == 201, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c


async def new_browser(c, n_hint=40, **kw):
    r = await c.post("/v1/sessions")
    assert r.status_code == 201, r.text
    return Browser(r.json(), start_ms=now_ms() - n_hint * 700, think=FAST, **kw)


async def post(c, events):
    return await c.post("/v1/sync", json={"events": events})


async def test_live_session_and_daily_match_local_play(live):
    b = await new_browser(live, 60)
    events = b.play(40)
    r = await post(live, events)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rejected"] == [] and len(body["acked"]) == 40
    assert_profile_matches(body["profile"], b)
    assert [h["at"] for h in body["profile"]["history"]] == [e["at"] for e in events]
    r = await post(live, daily_events(utc_day(now_ms())))
    assert r.json()["rejected"] == [] and r.json()["profile"]["rounds"] == 50
    assert (await live.get("/v1/profile")).json() == r.json()["profile"]


async def test_live_concurrent_identical_syncs_apply_each_round_once(live):
    """The player-row lock serializes both requests: both succeed, nothing is counted twice."""
    b = await new_browser(live)
    events = b.play(20)
    results = await asyncio.gather(*[post(live, events) for _ in range(6)])
    assert [r.status_code for r in results] == [200] * 6
    assert all(r.json()["rejected"] == [] for r in results)
    assert_profile_matches((await live.get("/v1/profile")).json(), b)


async def test_live_concurrent_batches_of_one_session_in_order(live):
    """Two batches racing: the lock decides the order. Whichever runs second may see a gap if it ran first,
    but a retry of the rejected part must never double count or corrupt the rating."""
    b = await new_browser(live)
    events = b.play(20)
    first, second = await asyncio.gather(post(live, events[:10]), post(live, events[10:]))
    assert first.status_code == 200 and second.status_code == 200
    final = (await post(live, events)).json()  # a full retry settles everything that wasn't broken
    rejected = {x["reason"] for x in first.json()["rejected"] + second.json()["rejected"]}
    if not rejected:
        assert_profile_matches(final["profile"], b)
    else:
        assert rejected <= {"gap", "session_broken"}  # a lost race is reported, never silently mis-applied


async def test_live_import_then_play(live):
    from tests.test_sync import local_profile  # noqa: PLC0415

    local = local_profile()
    async with httpx.AsyncClient(base_url=LIVE, timeout=30) as c:
        r = await c.post("/v1/players", json={"import": local})
        assert r.status_code == 201, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        got = (await c.get("/v1/profile")).json()
        assert got["rounds"] == 342 and got["daily"] == local["daily"]
        for day, stat in local["days"].items():
            assert got["days"][day] == stat, day
        assert len(got["history"]) == len(local["history"])

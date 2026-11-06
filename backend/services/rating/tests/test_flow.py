"""Accounts, the profile and its cache, rate limits and health. (Playing is covered in test_sync.py.)"""
from app.models import Round  # noqa: F401  (imported so the tables exist for create_all)
from tests.helpers import signup
from tests.test_sync import Browser, sync, ticket


# ------------------------------------------------------------------ auth
async def test_requests_need_a_token(client):
    assert (await client.get("/v1/profile")).status_code == 401
    assert (await client.get("/v1/profile", headers={"Authorization": "Bearer nope"})).status_code == 401
    assert (await client.post("/v1/sessions")).status_code == 401
    assert (await client.post("/v1/sync", json={"events": []})).status_code == 401


async def test_token_is_not_stored_in_clear(client, engine):
    from sqlalchemy import select
    from app.models import Player

    headers, _ = await signup(client)
    token = headers["Authorization"].split()[1]
    async with engine.connect() as conn:
        rows = (await conn.execute(select(Player.token_hash))).scalars().all()
    assert token not in rows and len(rows[0]) == 64


async def test_removed_per_round_endpoints_are_gone(client):
    """Phase 4 replaced them with /v1/sessions + /v1/sync."""
    headers, _ = await signup(client)
    for method, path in [("post", "/v1/rounds/next"), ("post", "/v1/rounds/answer"), ("get", "/v1/daily/2026-11-06")]:
        assert (await getattr(client, method)(path, headers=headers)).status_code in (404, 405), path


# ------------------------------------------------------------------ profile + cache
async def test_profile_has_the_shape_the_frontend_expects(client):
    headers, _ = await signup(client)
    b = Browser(await ticket(client, headers))
    await sync(client, headers, b.play(3))
    profile = (await client.get("/v1/profile", headers=headers)).json()
    assert set(profile) == {"rating", "peak", "skills", "streak", "bestStreak", "rounds", "history", "days", "daily"}
    assert set(profile["skills"]) == {"multiplication", "percentages", "fractions", "powers"}
    assert set(profile["history"][0]) == {"at", "skill", "correct", "timeMs", "delta", "problemRating"}
    assert profile["rounds"] == 3 and sum(d["rounds"] for d in profile["days"].values()) == 3


async def test_profile_is_cached_then_refreshed_by_a_sync(client, redis):
    headers, player_id = await signup(client)
    first = await client.get("/v1/profile", headers=headers)
    second = await client.get("/v1/profile", headers=headers)
    assert first.headers["x-cache"] == "miss" and second.headers["x-cache"] == "hit"
    assert await redis.exists(f"profile:{player_id}") == 1

    b = Browser(await ticket(client, headers))
    r = await sync(client, headers, b.play(2))
    # the sync returns the fresh profile and leaves it in the cache, so the next GET is correct and cheap
    third = await client.get("/v1/profile", headers=headers)
    assert third.headers["x-cache"] == "hit" and third.json()["rounds"] == 2 == r.json()["profile"]["rounds"]


# ------------------------------------------------------------------ limits & health
async def test_rate_limit_returns_429(make_client):
    client = await make_client(rate_limit_per_minute=3)
    headers, _ = await signup(client)
    codes = [(await client.get("/v1/profile", headers=headers)).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]


async def test_signup_is_rate_limited(make_client):
    client = await make_client(signup_limit_per_hour=2)
    codes = [(await client.post("/v1/players")).status_code for _ in range(3)]
    assert codes == [201, 201, 429]


async def test_readiness_reports_each_dependency(client):
    r = await client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"redis": True, "database": True}

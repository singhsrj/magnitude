import json

import pytest

from app.models import Round  # noqa: F401  (imported so the tables exist for create_all)
from magnitude_engine import daily_set
from tests.conftest import today


async def signup(client):
    r = await client.post("/v1/players")
    assert r.status_code == 201
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}, body["playerId"]


async def issue(client, headers):
    r = await client.post("/v1/rounds/next", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def secret(redis, problem_id):
    raw = await redis.get(f"prob:{problem_id}")
    return json.loads(raw) if raw else None


def other(side):
    return "right" if side == "left" else "left"


async def answer(client, headers, problem_id, choice, time_ms=900):
    return await client.post(
        "/v1/rounds/answer", headers=headers, json={"problemId": problem_id, "choice": choice, "timeMs": time_ms, "localDate": today()}
    )


# ------------------------------------------------------------------ auth
async def test_requests_need_a_token(client):
    assert (await client.get("/v1/profile")).status_code == 401
    assert (await client.get("/v1/profile", headers={"Authorization": "Bearer nope"})).status_code == 401
    assert (await client.post("/v1/rounds/next")).status_code == 401


async def test_token_is_not_stored_in_clear(client, engine):
    from sqlalchemy import select
    from app.models import Player

    headers, _ = await signup(client)
    token = headers["Authorization"].split()[1]
    async with engine.connect() as conn:
        rows = (await conn.execute(select(Player.token_hash))).scalars().all()
    assert token not in rows and len(rows[0]) == 64


# ------------------------------------------------------------------ practice rounds
async def test_public_problem_does_not_leak_the_answer(client):
    headers, _ = await signup(client)
    problem = await issue(client, headers)
    assert set(problem) == {"id", "skill", "left", "right", "rating", "expiresInMs"}
    assert set(problem["left"]) == {"text"}


async def test_fast_correct_answer_raises_rating(client, redis):
    headers, _ = await signup(client)
    problem = await issue(client, headers)
    rec = await secret(redis, problem["id"])
    r = await answer(client, headers, problem["id"], rec["answer"], time_ms=700)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["correct"] is True and out["delta"] > 0
    assert out["rating"] > 1200 and out["streak"] == 1 and out["rounds"] == 1
    assert set(out["values"]) == {"left", "right"}


async def test_wrong_answer_lowers_rating_and_resets_streak(client, redis):
    headers, _ = await signup(client)
    p1 = await issue(client, headers)
    await answer(client, headers, p1["id"], (await secret(redis, p1["id"]))["answer"])
    p2 = await issue(client, headers)
    rec = await secret(redis, p2["id"])
    out = (await answer(client, headers, p2["id"], other(rec["answer"]))).json()
    assert out["correct"] is False and out["delta"] < 0 and out["streak"] == 0


async def test_timeout_counts_as_a_miss(client, redis):
    headers, _ = await signup(client)
    problem = await issue(client, headers)
    out = (await answer(client, headers, problem["id"], None, time_ms=8000)).json()
    assert out["correct"] is False and out["delta"] < 0


async def test_a_problem_can_only_be_answered_once(client, redis):
    headers, _ = await signup(client)
    problem = await issue(client, headers)
    choice = (await secret(redis, problem["id"]))["answer"]
    assert (await answer(client, headers, problem["id"], choice)).status_code == 200
    assert (await answer(client, headers, problem["id"], choice)).status_code == 404


async def test_expired_problem_is_rejected(client, redis):
    headers, _ = await signup(client)
    problem = await issue(client, headers)
    await redis.delete(f"prob:{problem['id']}")
    assert (await answer(client, headers, problem["id"], "left")).status_code == 404


async def test_players_cannot_answer_each_others_problems(client, redis):
    a, _ = await signup(client)
    b, _ = await signup(client)
    problem = await issue(client, a)
    assert (await answer(client, b, problem["id"], "left")).status_code == 404


async def test_implausible_local_date_is_rejected(client, redis):
    headers, _ = await signup(client)
    problem = await issue(client, headers)
    r = await client.post("/v1/rounds/answer", headers=headers, json={"problemId": problem["id"], "choice": "left", "timeMs": 900, "localDate": "2020-01-01"})
    assert r.status_code == 422


# ------------------------------------------------------------------ profile + cache
async def test_profile_has_the_shape_the_frontend_expects(client, redis):
    headers, _ = await signup(client)
    p = await issue(client, headers)
    await answer(client, headers, p["id"], (await secret(redis, p["id"]))["answer"])
    profile = (await client.get("/v1/profile", headers=headers)).json()
    assert set(profile) == {"rating", "peak", "skills", "streak", "bestStreak", "rounds", "history", "days", "daily"}
    assert set(profile["skills"]) == {"multiplication", "percentages", "fractions", "powers"}
    assert set(profile["history"][0]) == {"at", "skill", "correct", "timeMs", "delta", "problemRating"}
    assert profile["rounds"] == 1 and profile["days"][today()] == {"rounds": 1, "correct": 1}


async def test_profile_is_cached_then_invalidated_by_an_answer(client, redis):
    headers, player_id = await signup(client)
    first = await client.get("/v1/profile", headers=headers)
    second = await client.get("/v1/profile", headers=headers)
    assert first.headers["x-cache"] == "miss" and second.headers["x-cache"] == "hit"
    assert await redis.exists(f"profile:{player_id}") == 1

    p = await issue(client, headers)
    await answer(client, headers, p["id"], "left")
    assert await redis.exists(f"profile:{player_id}") == 0
    third = await client.get("/v1/profile", headers=headers)
    assert third.headers["x-cache"] == "miss" and third.json()["rounds"] == 1


# ------------------------------------------------------------------ daily set
def daily_answers():
    return [p.answer for p in daily_set(today())]


async def test_daily_set_hides_answers_and_is_cached(client, redis):
    headers, _ = await signup(client)
    r = await client.get(f"/v1/daily/{today()}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["problems"]) == 10 and body["answered"] == 0 and body["result"] is None
    assert "answer" not in json.dumps(body)
    assert await redis.exists(f"daily:{today()}") == 1


async def test_daily_must_be_answered_in_order(client):
    headers, _ = await signup(client)
    r = await client.post(f"/v1/daily/{today()}/answer", headers=headers, json={"index": 3, "choice": "left", "timeMs": 900})
    assert r.status_code == 409


async def test_full_daily_set_records_a_result_once(client):
    headers, _ = await signup(client)
    answers = daily_answers()
    last = None
    for i, a in enumerate(answers):
        choice = a if i < 8 else other(a)  # 8 right, 2 wrong
        r = await client.post(f"/v1/daily/{today()}/answer", headers=headers, json={"index": i, "choice": choice, "timeMs": 1200})
        assert r.status_code == 200, r.text
        assert r.json()["complete"] is (i == 9)
        last = r.json()
    assert last["result"] == {"correct": 8, "total": 10, "timeMs": 12000}
    assert last["ratingDelta"] is not None

    again = await client.post(f"/v1/daily/{today()}/answer", headers=headers, json={"index": 0, "choice": "left", "timeMs": 900})
    assert again.status_code == 409

    day = (await client.get(f"/v1/daily/{today()}", headers=headers)).json()
    assert day["answered"] == 10 and day["result"]["correct"] == 8
    profile = (await client.get("/v1/profile", headers=headers)).json()
    assert profile["daily"][today()]["correct"] == 8 and profile["rounds"] == 10


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
    assert r.json() == {"redis": True, "problem_service": True, "database": True}

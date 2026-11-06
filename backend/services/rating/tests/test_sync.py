"""Phase 4: sessions + /v1/sync. The test 'browser' plays with the Python engine, exactly as the real one
will play with the TypeScript engine, and the server must end up with the same profile."""
import asyncio
import random
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.models import GameSession, Round  # noqa: F401  (imported so the tables exist for create_all)
from magnitude_engine import (
    DAILY_LENGTH, DEFAULT_RATING, SKILLS, daily_problem, next_gen_skills, normalize_time, session_problem, update_player,
)
from tests import helpers
from tests.helpers import signup


def now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def utc_day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


class Browser:
    """Plays offline like the app: local ratings via the engine, one event per answer."""

    def __init__(self, ticket: dict, skills: dict[str, float] | None = None, rating: float = DEFAULT_RATING, start_ms: int | None = None, think: list[int] | None = None):
        self.think = think or [180, 420, 800, 1500, 3000, 6500]
        self.session_id = ticket["sessionId"]
        self.seed = ticket["seed"]
        self.rating = rating
        self.skills = dict(skills or {s: DEFAULT_RATING for s in SKILLS})
        self.gen = dict(self.skills)
        self.start_skills = dict(self.skills)
        self.index = 0
        self.clock = start_ms if start_ms is not None else now_ms() - 20 * 60_000  # played over the last 20 min
        self.rng = random.Random(7)
        self.streak = self.best = self.rounds = 0
        self.peak = rating
        self.deltas: list[float] = []

    def play(self, n: int, mode: str = "mixed") -> list[dict]:
        events = []
        for _ in range(n):
            p = session_problem(self.seed, self.index, self.gen)
            roll = self.rng.random()
            outcome = "right" if mode == "right" else ("right" if roll < 0.7 else "wrong" if roll < 0.9 else "timeout")
            choice = None if outcome == "timeout" else (p.answer if outcome == "right" else ("right" if p.answer == "left" else "left"))
            time_ms = 8000 if choice is None else normalize_time(self.rng.choice(self.think))
            correct = choice is not None and choice == p.answer
            self.clock += time_ms + 50
            ev = {
                "kind": "practice", "sessionId": self.session_id, "index": self.index, "choice": choice, "timeMs": time_ms,
                "at": self.clock, "localDate": utc_day(self.clock), "problemId": p.id, "skill": p.skill,
                "problemRating": p.rating, "correct": correct,
            }
            if self.index == 0:
                ev["startSkills"] = dict(self.start_skills)
            events.append(ev)
            self._apply(p, correct, time_ms)
            self.index += 1
        return events

    def _apply(self, p, correct: bool, time_ms: int) -> None:
        overall = update_player(self.rating, p.rating, correct, time_ms)
        self.rating = overall.next
        self.peak = max(self.peak, self.rating)
        self.skills[p.skill] = update_player(self.skills[p.skill], p.rating, correct, time_ms).next
        self.gen = next_gen_skills(self.gen, p.skill, p.rating, correct, time_ms)
        self.streak = self.streak + 1 if correct else 0
        self.best = max(self.best, self.streak)
        self.rounds += 1
        self.deltas.append(overall.delta)


async def ticket(client, headers) -> dict:
    """A ticket as if it had been fetched an hour ago (honest play takes minutes, and `at` must follow issue)."""
    r = await client.post("/v1/sessions", headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    async with helpers.ENGINE["engine"].begin() as conn:
        await conn.execute(
            update(GameSession).where(GameSession.id == uuid.UUID(body["sessionId"]))
            .values(issued_at=datetime.now(timezone.utc) - timedelta(hours=1))
        )
    return body


async def sync(client, headers, events):
    return await client.post("/v1/sync", headers=headers, json={"events": events})


def assert_profile_matches(profile: dict, b: Browser) -> None:
    assert profile["rounds"] == b.rounds
    assert profile["rating"] == pytest.approx(b.rating, abs=1e-9)
    assert profile["peak"] == pytest.approx(b.peak, abs=1e-9)
    assert profile["streak"] == b.streak and profile["bestStreak"] == b.best
    for s in SKILLS:
        assert profile["skills"][s] == pytest.approx(b.skills[s], abs=1e-9), s
    assert [h["delta"] for h in profile["history"]] == pytest.approx(b.deltas[-200:], abs=1e-9)


# ------------------------------------------------------------------ sessions
async def test_session_ticket(client):
    headers, _ = await signup(client)
    t = await ticket(client, headers)
    assert set(t) == {"sessionId", "seed", "expiresAt"}
    assert 0 <= t["seed"] < 2**32 and t["expiresAt"] > now_ms()
    assert (await ticket(client, headers))["sessionId"] != t["sessionId"]
    assert (await client.post("/v1/sessions")).status_code == 401


async def test_sessions_are_rate_limited(make_client):
    client = await make_client(session_limit_per_minute=3)
    headers, _ = await signup(client)
    codes = [(await client.post("/v1/sessions", headers=headers)).status_code for _ in range(5)]
    assert codes == [201, 201, 201, 429, 429]


# ------------------------------------------------------------------ happy path
async def test_synced_session_matches_local_play_exactly(client):
    headers, _ = await signup(client)
    b = Browser(await ticket(client, headers))
    events = b.play(50)
    r = await sync(client, headers, events)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["acked"]) == 50 and body["rejected"] == []
    assert_profile_matches(body["profile"], b)
    # history timestamps survive the round trip to the millisecond
    assert [h["at"] for h in body["profile"]["history"]] == [e["at"] for e in events]
    # GET /v1/profile agrees (and the sync refreshed the cache)
    assert (await client.get("/v1/profile", headers=headers)).json() == body["profile"]


async def test_batches_in_several_requests(client):
    headers, _ = await signup(client)
    b = Browser(await ticket(client, headers))
    events = b.play(30)
    for i in range(0, 30, 5):
        r = await sync(client, headers, events[i : i + 5])
        assert r.status_code == 200 and r.json()["rejected"] == []
    assert_profile_matches(r.json()["profile"], b)


async def test_retried_batch_is_not_counted_twice(client):
    headers, _ = await signup(client)
    b = Browser(await ticket(client, headers))
    events = b.play(12)
    first = (await sync(client, headers, events)).json()
    again = (await sync(client, headers, events)).json()
    assert len(again["acked"]) == 12 and again["rejected"] == []  # duplicates are acknowledged...
    assert again["profile"] == first["profile"]  # ...but change nothing
    assert_profile_matches(again["profile"], b)


async def test_overlapping_batches(client):
    headers, _ = await signup(client)
    b = Browser(await ticket(client, headers))
    events = b.play(10)
    await sync(client, headers, events[:6])
    r = (await sync(client, headers, events[3:])).json()  # 3 old + 4 new
    assert len(r["acked"]) == 7 and r["rejected"] == []
    assert_profile_matches(r["profile"], b)


async def test_second_session_continues_from_server_ratings(client):
    headers, _ = await signup(client)
    b1 = Browser(await ticket(client, headers))
    await sync(client, headers, b1.play(20))
    # the next visit starts from the ratings the browser now holds
    b2 = Browser(await ticket(client, headers), skills=b1.skills, rating=b1.rating, start_ms=b1.clock + 5_000)  # b1 played 20 minutes ago
    b2.peak, b2.streak, b2.best, b2.rounds = b1.peak, b1.streak, b1.best, b1.rounds
    b2.deltas = list(b1.deltas)
    r = await sync(client, headers, b2.play(15))
    assert r.json()["rejected"] == []
    assert_profile_matches(r.json()["profile"], b2)


# ------------------------------------------------------------------ rejections
async def test_gap_rejects_and_breaks_the_session(client):
    headers, _ = await signup(client)
    b = Browser(await ticket(client, headers))
    events = b.play(6)
    r = (await sync(client, headers, events[:2] + events[3:])).json()
    assert [a["index"] for a in r["acked"]] == [0, 1]
    assert [(x["index"], x["reason"]) for x in r["rejected"]] == [(3, "gap"), (4, "session_broken"), (5, "session_broken")]
    # the missing round arriving later no longer helps: the session is broken
    late = (await sync(client, headers, [events[2]])).json()
    assert [x["reason"] for x in late["rejected"]] == ["session_broken"]


async def test_fingerprint_mismatch_breaks_only_that_session(client):
    headers, _ = await signup(client)
    good = Browser(await ticket(client, headers))
    bad = Browser(await ticket(client, headers), start_ms=now_ms() - 10 * 60_000)
    bad_events = bad.play(4)
    bad_events[2]["problemId"] = "multiplication-forged"
    r = (await sync(client, headers, bad_events + good.play(5))).json()
    assert [(x["index"], x["reason"]) for x in r["rejected"]] == [(2, "mismatch"), (3, "session_broken")]
    assert len(r["acked"]) == 2 + 5
    assert r["profile"]["rounds"] == 2 + 5


async def test_wrong_problem_rating_is_a_mismatch(client):
    headers, _ = await signup(client)
    b = Browser(await ticket(client, headers))
    events = b.play(2)
    events[1]["problemRating"] += 1
    r = (await sync(client, headers, events)).json()
    assert [(x["index"], x["reason"]) for x in r["rejected"]] == [(1, "mismatch")]


async def test_client_cannot_claim_a_correct_answer(client):
    headers, _ = await signup(client)
    b = Browser(await ticket(client, headers))
    ev = b.play(1)[0]
    ev["choice"] = "right" if ev["choice"] == "left" or ev["choice"] is None else "left"
    ev["correct"] = True  # a lie: the server grades from `choice`
    r = (await sync(client, headers, [ev])).json()
    p = session_problem(b.seed, 0, b.start_skills)
    assert r["profile"]["streak"] == (1 if ev["choice"] == p.answer else 0)


async def test_unknown_and_foreign_sessions(client):
    h1, _ = await signup(client)
    h2, _ = await signup(client)
    b = Browser(await ticket(client, h1))
    events = b.play(2)
    r = (await sync(client, h2, events)).json()  # someone else's session
    assert {x["reason"] for x in r["rejected"]} == {"unknown_session"} and r["acked"] == []
    forged = [dict(events[0], sessionId="00000000-0000-4000-8000-000000000000")]
    assert (await sync(client, h1, forged)).json()["rejected"][0]["reason"] == "unknown_session"


async def test_expired_session(client, engine):
    headers, _ = await signup(client)
    b = Browser(await ticket(client, headers))
    events = b.play(3)
    async with engine.begin() as conn:
        await conn.execute(update(GameSession).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
    r = (await sync(client, headers, events)).json()
    assert r["rejected"][0]["reason"] == "expired"


async def test_bad_start_skills(client):
    headers, _ = await signup(client)
    missing = Browser(await ticket(client, headers))
    ev = missing.play(1)[0]
    ev.pop("startSkills")
    assert (await sync(client, headers, [ev])).json()["rejected"][0]["reason"] == "bad_start"

    far = Browser(await ticket(client, headers), skills={s: 2200.0 for s in SKILLS})  # server says 1200
    assert (await sync(client, headers, far.play(1))).json()["rejected"][0]["reason"] == "bad_start"


async def test_think_times_cannot_exceed_wall_clock_time(client):
    headers, _ = await signup(client)
    b = Browser(await ticket(client, headers))
    events = b.play(8)
    for e in events:  # claims 8 s per round, but the timestamps say rounds were 0.8 s apart
        e["timeMs"] = 8000
        e["choice"] = None
        e["correct"] = False
    first_ok = (await sync(client, headers, events)).json()
    assert any(x["reason"] == "implausible_time" for x in first_ok["rejected"])


async def test_answers_from_the_future_are_rejected(client):
    headers, _ = await signup(client)
    b = Browser(await ticket(client, headers), start_ms=now_ms() + 3_600_000)
    r = (await sync(client, headers, b.play(1))).json()
    assert r["rejected"][0]["reason"] == "implausible_time"


async def test_local_date_must_match_the_moment_of_the_answer(client):
    headers, _ = await signup(client)
    b = Browser(await ticket(client, headers))
    ev = b.play(1)[0]
    ev["localDate"] = (datetime.now(timezone.utc) - timedelta(days=5)).date().isoformat()
    assert (await sync(client, headers, [ev])).json()["rejected"][0]["reason"] == "bad_date"


async def test_a_late_sync_is_fine(client, engine):
    """Played 3 days ago while offline, synced now."""
    headers, _ = await signup(client)
    b = Browser(await ticket(client, headers), start_ms=now_ms() - 3 * 86_400_000)
    events = b.play(20)
    async with engine.begin() as conn:  # the ticket was issued 4 days ago and has 3 days left
        await conn.execute(update(GameSession).values(
            issued_at=datetime.now(timezone.utc) - timedelta(days=4), expires_at=datetime.now(timezone.utc) + timedelta(days=3)))
    r = (await sync(client, headers, events)).json()
    assert r["rejected"] == [] and len(r["acked"]) == 20
    assert_profile_matches(r["profile"], b)
    assert len(r["profile"]["days"]) >= 1


# ------------------------------------------------------------------ request limits
async def test_batch_size_limits(client):
    headers, _ = await signup(client)
    b = Browser(await ticket(client, headers))
    ev = b.play(1)[0]
    assert (await sync(client, headers, [])).status_code == 422
    assert (await sync(client, headers, [ev] * 201)).status_code == 422
    assert (await sync(client, headers, [ev] * 200)).status_code == 200  # 199 duplicates are just acked


async def test_sync_needs_a_token_and_valid_shape(client):
    assert (await client.post("/v1/sync", json={"events": []})).status_code == 401
    headers, _ = await signup(client)
    assert (await sync(client, headers, [{"kind": "nope"}])).status_code == 422


async def test_cors_preflight_is_cacheable(client):
    r = await client.options(
        "/v1/sync",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"},
    )
    assert r.status_code == 200 and r.headers["access-control-max-age"] == "86400"


async def test_cors_origin_regex_allows_preview_deploys(make_client):
    c = await make_client(cors_origins="https://magnitude.vercel.app", cors_origin_regex=r"^https://magnitude(-[a-z0-9-]+)?\.vercel\.app$")
    pre = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"}
    for origin in ("https://magnitude.vercel.app", "https://magnitude-git-main-suraj.vercel.app"):
        r = await c.options("/v1/sync", headers={"Origin": origin, **pre})
        assert r.status_code == 200 and r.headers["access-control-allow-origin"] == origin
    r = await c.options("/v1/sync", headers={"Origin": "https://evil.vercel.app", **pre})
    assert r.status_code == 400


# ------------------------------------------------------------------ daily set through sync
def daily_events(day: str, n: int = DAILY_LENGTH, wrong_at: set[int] = frozenset(), start_ms: int | None = None) -> list[dict]:
    clock = start_ms if start_ms is not None else now_ms() - 30_000
    out = []
    for i in range(n):
        p = daily_problem(day, i)
        choice = ("right" if p.answer == "left" else "left") if i in wrong_at else p.answer
        clock += 1000
        out.append({
            "kind": "daily", "date": day, "index": i, "choice": choice, "timeMs": 900, "at": clock,
            "problemId": p.id, "skill": p.skill, "problemRating": p.rating, "correct": i not in wrong_at,
        })
    return out


async def test_full_daily_set_via_sync_records_one_result(client):
    headers, _ = await signup(client)
    day = utc_day(now_ms())
    r = (await sync(client, headers, daily_events(day, wrong_at={3}))).json()
    assert r["rejected"] == [] and len(r["acked"]) == DAILY_LENGTH
    assert r["profile"]["daily"][day] == {"correct": 9, "total": 10, "timeMs": 9000}
    assert r["profile"]["rounds"] == 10
    again = (await sync(client, headers, daily_events(day))).json()  # replaying the whole set changes nothing
    assert len(again["acked"]) == 10 and again["rejected"] == []
    assert again["profile"] == r["profile"]


async def test_daily_must_arrive_in_order(client):
    headers, _ = await signup(client)
    day = utc_day(now_ms())
    ev = daily_events(day)
    r = (await sync(client, headers, [ev[1]])).json()
    assert r["rejected"][0]["reason"] == "gap" and r["profile"]["rounds"] == 0
    r = (await sync(client, headers, ev[:4])).json()
    assert r["profile"]["rounds"] == 4 and day not in r["profile"]["daily"]  # not finished yet
    r = (await sync(client, headers, ev[4:])).json()
    assert day in r["profile"]["daily"]


async def test_forged_daily_problem_is_rejected(client):
    headers, _ = await signup(client)
    day = utc_day(now_ms())
    ev = daily_events(day)
    ev[0]["problemRating"] += 5
    assert (await sync(client, headers, ev[:1])).json()["rejected"][0]["reason"] == "mismatch"


async def test_daily_and_practice_in_one_batch(client):
    headers, _ = await signup(client)
    b = Browser(await ticket(client, headers))
    practice = b.play(5)
    day = utc_day(now_ms())
    r = (await sync(client, headers, practice + daily_events(day, start_ms=now_ms() - 20_000))).json()
    assert r["rejected"] == [] and r["profile"]["rounds"] == 15


# ------------------------------------------------------------------ one-time import of a local profile
def local_profile(n_history: int = 30) -> dict:
    base = now_ms() - 10 * 86_400_000
    history = []
    rating = 1300.0
    for i in range(n_history):
        at = base + i * 3_600_000
        delta = 4.5 if i % 3 else -6.25
        history.append({
            "at": at, "skill": SKILLS[i % 4], "correct": bool(i % 3), "timeMs": 900 + i, "delta": delta,
            "problemRating": 1250 + i, "localDate": utc_day(at),
        })
        rating += delta
    days_seen: dict[str, list[int]] = {}
    for h in history:
        d = days_seen.setdefault(h["localDate"], [0, 0])
        d[0] += 1
        d[1] += 1 if h["correct"] else 0
    # an older day the last-30 history doesn't cover: 12 rounds, 9 correct
    old_day = utc_day(base - 3 * 86_400_000)
    days = {k: {"rounds": v[0], "correct": v[1]} for k, v in days_seen.items()}
    days[old_day] = {"rounds": 12, "correct": 9}
    return {
        "rating": rating, "peak": rating + 20, "skills": {s: 1250.0 + 10 * i for i, s in enumerate(SKILLS)},
        "streak": 2, "bestStreak": 9, "rounds": 342, "history": history, "days": days,
        "daily": {utc_day(base): {"correct": 8, "total": 10, "timeMs": 31_000}},
    }


async def test_signup_without_a_body_still_works(client):
    r = await client.post("/v1/players")
    assert r.status_code == 201
    r = await client.post("/v1/players", json={})
    assert r.status_code == 201


async def test_import_a_local_profile_once_at_signup(client):
    local = local_profile()
    r = await client.post("/v1/players", json={"import": local})
    assert r.status_code == 201, r.text
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    got = (await client.get("/v1/profile", headers=headers)).json()
    assert got["rating"] == pytest.approx(local["rating"]) and got["peak"] == pytest.approx(local["peak"])
    assert got["skills"] == local["skills"]
    assert (got["streak"], got["bestStreak"], got["rounds"]) == (2, 9, 342)
    assert got["daily"] == local["daily"]
    # history comes back as it went in (placeholder rows for older days stay out of it)
    assert [(h["at"], h["skill"], h["correct"], h["timeMs"]) for h in got["history"]] == \
        [(h["at"], h["skill"], h["correct"], h["timeMs"]) for h in local["history"]]
    assert [h["delta"] for h in got["history"]] == pytest.approx([h["delta"] for h in local["history"]])
    # per-day counts, including the day only the placeholder rows cover, match what the browser had
    for day, stat in local["days"].items():
        assert got["days"][day] == stat, day


async def test_play_continues_after_an_import(client):
    local = local_profile()
    r = await client.post("/v1/players", json={"import": local})
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    b = Browser(await ticket(client, headers), skills=local["skills"], rating=local["rating"])
    r = (await sync(client, headers, b.play(10))).json()
    assert r["rejected"] == [] and r["profile"]["rounds"] == 342 + 10
    assert r["profile"]["rating"] == pytest.approx(b.rating, abs=1e-9)


async def test_bad_imports_are_rejected(client):
    good = local_profile(3)
    assert (await client.post("/v1/players", json={"import": {**good, "rating": 99999}})).status_code == 422
    assert (await client.post("/v1/players", json={"import": {**good, "skills": {"multiplication": 1200}}})).status_code == 422
    assert (await client.post("/v1/players", json={"import": {**good, "history": good["history"] * 100}})).status_code == 422

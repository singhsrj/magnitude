"""Replays a browser's offline play against the Python engine (Phase 4).

The browser plays from a server-issued seed with no network calls, then sends what happened in batches.
For every event we rebuild the problem the browser saw (same seed, same engine), grade the answer ourselves,
and apply Elo to the locked player row. The client's claims (`problemId`, `problemRating`, `correct`) are only a
fingerprint: if our rebuilt problem differs, the event is rejected.

Rejecting a practice event breaks its session: later rounds depend on it, so they can't be verified either.
Daily events and other sessions are unaffected. Duplicates are acknowledged without being applied again,
which makes retries safe.
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from magnitude_engine import (
    DAILY_LENGTH,
    SESSION_MAX_ROUNDS,
    Problem,
    daily_problem,
    next_gen_skills,
    normalize_time,
    session_problem,
)

from . import schemas, service
from .models import GameSession, Player, Round
from .rules import (
    SESSION_TTL,
    as_utc,
    at_plausible,
    local_date_matches,
    ms_to_datetime,
    session_time_plausible,
    start_skills_plausible,
)

log = logging.getLogger("sync")

# A daily answer older than this can't be synced (a little longer than a session ticket's lifetime).
DAILY_MAX_AGE = SESSION_TTL


async def create_session(db: AsyncSession, player_id: uuid.UUID, now: datetime) -> GameSession:
    gs = GameSession(
        id=uuid.uuid4(),
        player_id=player_id,
        seed=secrets.randbits(32),
        issued_at=now,
        expires_at=now + SESSION_TTL,
        next_index=0,
        time_sum_ms=0,
        status="open",
    )
    db.add(gs)
    return gs


class Replayer:
    """One sync request. The caller has locked the player row and commits afterwards."""

    def __init__(self, db: AsyncSession, player: Player, now: datetime) -> None:
        self.db = db
        self.player = player
        self.now = now
        self.acked: list[schemas.EventRef] = []
        self.rejected: list[schemas.RejectedEvent] = []
        self._sessions: dict[uuid.UUID, GameSession | None] = {}
        self._daily_counts: dict[date, int] = {}

    async def run(self, events: list[schemas.PracticeEvent | schemas.DailyEvent]) -> None:
        for ev in events:
            if ev.kind == "practice":
                await self._practice(ev)
            else:
                await self._daily(ev)

    # ------------------------------------------------------------------ helpers
    def _ack(self, ev) -> None:
        self.acked.append(_ref(schemas.EventRef, ev))

    def _reject(self, ev, reason: str) -> None:
        self.rejected.append(_ref(schemas.RejectedEvent, ev, reason=reason))

    def _break(self, gs: GameSession, ev, reason: str) -> None:
        gs.status = "broken"
        self._reject(ev, reason)

    async def _load_session(self, session_id: uuid.UUID) -> GameSession | None:
        if session_id not in self._sessions:
            result = await self.db.execute(
                select(GameSession).where(GameSession.id == session_id, GameSession.player_id == self.player.id)
            )
            self._sessions[session_id] = result.scalar_one_or_none()
        return self._sessions[session_id]

    async def _daily_count(self, day: date) -> int:
        if day not in self._daily_counts:
            result = await self.db.execute(
                select(func.count()).select_from(Round).where(
                    Round.player_id == self.player.id, Round.local_date == day, Round.mode == "daily"
                )
            )
            self._daily_counts[day] = int(result.scalar_one())
        return self._daily_counts[day]

    # ------------------------------------------------------------------ practice
    async def _practice(self, ev: schemas.PracticeEvent) -> None:
        gs = await self._load_session(ev.session_id)
        if gs is None:
            return self._reject(ev, "unknown_session")
        if ev.index < gs.next_index:
            return self._ack(ev)  # already applied (a retried batch)
        if gs.status == "broken":
            return self._reject(ev, "session_broken")
        if self.now > as_utc(gs.expires_at):
            return self._break(gs, ev, "expired")
        if ev.index >= SESSION_MAX_ROUNDS:
            return self._break(gs, ev, "out_of_range")
        if ev.index > gs.next_index:
            return self._break(gs, ev, "gap")

        at = ms_to_datetime(ev.at)
        time_ms = normalize_time(ev.time_ms)

        if ev.index == 0:
            if ev.start_skills is None or not start_skills_plausible(ev.start_skills, self.player.skills):
                return self._break(gs, ev, "bad_start")
            gen = {k: float(v) for k, v in ev.start_skills.items()}
            round_zero_start = ms_to_datetime(ev.at - time_ms)
        else:
            gen = gs.gen_skills or {}
            round_zero_start = gs.first_at

        if not at_plausible(at, self.now, gs.issued_at):
            return self._break(gs, ev, "implausible_time")
        if not local_date_matches(ev.local_date, at):
            return self._break(gs, ev, "bad_date")
        time_sum = gs.time_sum_ms + time_ms
        if not session_time_plausible(time_sum, round_zero_start, at, ev.index + 1):
            return self._break(gs, ev, "implausible_time")

        problem = session_problem(gs.seed, ev.index, gen)
        if not self._fingerprint_ok(problem, ev, f"session {gs.id} round {ev.index}"):
            return self._break(gs, ev, "mismatch")

        correct = ev.choice is not None and ev.choice == problem.answer
        service.apply_outcome(
            self.db,
            self.player,
            skill=problem.skill,
            problem_rating=problem.rating,
            correct=correct,
            time_ms=time_ms,
            problem_id=problem.id,
            mode="practice",
            local_date=ev.local_date,
            at=at,
            session_id=gs.id,
            round_index=ev.index,
        )
        gs.gen_skills = next_gen_skills(gen, problem.skill, problem.rating, correct, time_ms)
        gs.next_index = ev.index + 1
        gs.time_sum_ms = time_sum
        if ev.index == 0:
            gs.first_at = round_zero_start
        gs.expires_at = self.now + SESSION_TTL  # a session in use stays valid for another week of offline play
        self._ack(ev)

    # ------------------------------------------------------------------ daily set
    async def _daily(self, ev: schemas.DailyEvent) -> None:
        if ev.index >= DAILY_LENGTH:
            return self._reject(ev, "out_of_range")
        answered = await self._daily_count(ev.date)
        if ev.index < answered:
            return self._ack(ev)
        if ev.index > answered:
            return self._reject(ev, "gap")

        at = ms_to_datetime(ev.at)
        if not at_plausible(at, self.now, self.now - DAILY_MAX_AGE):
            return self._reject(ev, "implausible_time")
        if not local_date_matches(ev.date, at):
            return self._reject(ev, "bad_date")

        problem = daily_problem(ev.date.isoformat(), ev.index)
        if not self._fingerprint_ok(problem, ev, f"daily {ev.date} #{ev.index}"):
            return self._reject(ev, "mismatch")

        correct = ev.choice is not None and ev.choice == problem.answer
        service.apply_outcome(
            self.db,
            self.player,
            skill=problem.skill,
            problem_rating=problem.rating,
            correct=correct,
            time_ms=normalize_time(ev.time_ms),
            problem_id=problem.id,
            mode="daily",
            local_date=ev.date,
            daily_index=ev.index,
            at=at,
        )
        self._daily_counts[ev.date] = answered + 1
        if ev.index == DAILY_LENGTH - 1:
            await self.db.flush()  # finish_daily sums the rounds with a query
            await service.finish_daily(self.db, self.player, ev.date)
        self._ack(ev)

    # ------------------------------------------------------------------ fingerprint
    @staticmethod
    def _fingerprint_ok(problem: Problem, ev, where: str) -> bool:
        if problem.id == ev.problem_id and problem.rating == ev.problem_rating:
            return True
        # The browser and this engine disagree about what the problem was: an engine parity bug, or tampering.
        log.error(
            "replay mismatch at %s: client saw id=%r rating=%r, engine built id=%r rating=%r",
            where, ev.problem_id, ev.problem_rating, problem.id, problem.rating,
        )
        return False


def _ref(cls, ev, **extra):
    if ev.kind == "practice":
        return cls(kind="practice", session_id=ev.session_id, index=ev.index, **extra)
    return cls(kind="daily", date=ev.date, index=ev.index, **extra)


async def replay(
    db: AsyncSession, player: Player, events: list[schemas.PracticeEvent | schemas.DailyEvent], now: datetime
) -> tuple[list[schemas.EventRef], list[schemas.RejectedEvent]]:
    """Replays `events` in order against the (locked) player. The caller commits."""
    replayer = Replayer(db, player, now)
    await replayer.run(events)
    return replayer.acked, replayer.rejected

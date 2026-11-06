"""Domain logic: players, applying a round to a rating, building the profile. Talks to the DB only."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from magnitude_engine import DEFAULT_RATING, EloUpdate, update_player

from . import schemas
from .rules import datetime_to_ms, ms_to_datetime
from .models import DailyResult, Player, Round, default_skills, utcnow


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def to_ms(dt: datetime) -> int:
    return datetime_to_ms(dt)  # integer arithmetic: int(ts * 1000) can be 1 ms off


def _iso_date(key: str) -> date | None:
    try:
        return date.fromisoformat(key)
    except ValueError:
        return None


def import_profile(session: AsyncSession, player: Player, data: schemas.ProfileImport) -> None:
    """One-time import of a pre-Phase-4 browser profile (decision 1 in PHASE_4.md). Not verified: it can't be.

    Stats go on the player row. History becomes `rounds` rows. Day counts and the day streak come from rounds
    too, so days the last-200 history doesn't cover get placeholder rows (mode "imported"), which the profile's
    history and the daily set both ignore.
    """
    player.rating, player.peak = data.rating, max(data.peak, data.rating)
    player.skills = {s: float(v) for s, v in data.skills.items()}
    player.streak, player.best_streak, player.rounds = data.streak, max(data.best_streak, data.streak), data.rounds
    player.imported = True

    seen: dict[date, list[int]] = {}  # day -> [rounds, correct] already covered by real history rows
    rating = data.rating
    for rec in reversed(data.history):  # newest first, so rating_after steps back through the deltas
        at = ms_to_datetime(rec.at)
        day = rec.local_date
        counted = seen.setdefault(day, [0, 0])
        counted[0] += 1
        counted[1] += 1 if rec.correct else 0
        session.add(Round(
            player_id=player.id, at=at, skill=rec.skill, correct=rec.correct, time_ms=rec.time_ms, delta=rec.delta,
            rating_after=rating, problem_rating=rec.problem_rating, problem_id="imported", mode="practice", local_date=day,
        ))
        rating -= rec.delta
    for key, stat in data.days.items():
        day = _iso_date(key)
        if day is None:
            continue
        have = seen.get(day, [0, 0])
        for i in range(max(0, stat.rounds - have[0])):
            session.add(Round(
                player_id=player.id, at=datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc),
                skill="multiplication", correct=i < stat.correct - have[1], time_ms=0, delta=0.0, rating_after=data.rating,
                problem_rating=0, problem_id="imported", mode="imported", local_date=day,
            ))
    for key, res in data.daily.items():
        day = _iso_date(key)
        if day is not None:
            session.add(DailyResult(player_id=player.id, day=day, correct=res.correct, total=res.total, time_ms=res.time_ms))


async def create_player(session: AsyncSession, imported: schemas.ProfileImport | None = None) -> tuple[Player, str]:
    token = secrets.token_urlsafe(32)
    player = Player(
        id=uuid.uuid4(),
        token_hash=hash_token(token),
        rating=DEFAULT_RATING,
        peak=DEFAULT_RATING,
        streak=0,
        best_streak=0,
        rounds=0,
        skills=default_skills(),
    )
    session.add(player)
    if imported is not None:
        await session.flush()  # the rounds below reference the player row
        import_profile(session, player, imported)
    await session.commit()
    return player, token


async def find_player_by_token(session: AsyncSession, token: str) -> Player | None:
    result = await session.execute(select(Player).where(Player.token_hash == hash_token(token)))
    return result.scalar_one_or_none()


async def lock_player(session: AsyncSession, player_id: uuid.UUID) -> Player:
    """Reload the player row with FOR UPDATE so two answers can't update one rating at the same time."""
    result = await session.execute(
        select(Player).where(Player.id == player_id).with_for_update().execution_options(populate_existing=True)
    )
    return result.scalar_one()


def apply_outcome(
    session: AsyncSession,
    player: Player,
    *,
    skill: str,
    problem_rating: int,
    correct: bool,
    time_ms: int,
    problem_id: str,
    mode: str,
    local_date,
    daily_index: int | None = None,
    at: datetime | None = None,
    session_id: uuid.UUID | None = None,
    round_index: int | None = None,
) -> EloUpdate:
    """Updates the (locked) player in memory and queues the round row. The caller commits."""
    overall = update_player(player.rating, problem_rating, correct, time_ms)
    per_skill = update_player(player.skills[skill], problem_rating, correct, time_ms)

    player.rating = overall.next
    player.peak = max(player.peak, overall.next)
    player.skills = {**player.skills, skill: per_skill.next}  # new dict so the JSON column is saved
    player.streak = player.streak + 1 if correct else 0
    player.best_streak = max(player.best_streak, player.streak)
    player.rounds += 1

    session.add(
        Round(
            player_id=player.id,
            skill=skill,
            correct=correct,
            time_ms=time_ms,
            delta=overall.delta,
            rating_after=overall.next,
            problem_rating=problem_rating,
            problem_id=problem_id,
            mode=mode,
            local_date=local_date,
            daily_index=daily_index,
            session_id=session_id,
            round_index=round_index,
            **({"at": at} if at is not None else {}),
        )
    )
    return overall


async def finish_daily(session: AsyncSession, player: Player, day) -> tuple[schemas.DailyResultOut, float]:
    """Called after the 10th daily round has been flushed. Records the set's result."""
    row = (
        await session.execute(
            select(
                func.count(),
                func.sum(case((Round.correct, 1), else_=0)),
                func.sum(Round.time_ms),
                func.sum(Round.delta),
            ).where(Round.player_id == player.id, Round.local_date == day, Round.mode == "daily")
        )
    ).one()
    total, correct, time_ms, delta = int(row[0]), int(row[1] or 0), int(row[2] or 0), float(row[3] or 0.0)
    session.add(DailyResult(player_id=player.id, day=day, correct=correct, total=total, time_ms=time_ms))
    return schemas.DailyResultOut(correct=correct, total=total, time_ms=time_ms), delta


async def build_profile(session: AsyncSession, player: Player) -> schemas.ProfileOut:
    history_rows = (
        (
            await session.execute(
                select(Round)
                .where(Round.player_id == player.id, Round.mode != "imported")
                .order_by(Round.at.desc(), Round.id.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    since = utcnow().date() - timedelta(days=62)
    day_rows = (
        await session.execute(
            select(Round.local_date, func.count(), func.sum(case((Round.correct, 1), else_=0)))
            .where(Round.player_id == player.id, Round.local_date >= since)
            .group_by(Round.local_date)
        )
    ).all()
    daily_rows = (
        (
            await session.execute(
                select(DailyResult).where(DailyResult.player_id == player.id).order_by(DailyResult.day.desc()).limit(60)
            )
        )
        .scalars()
        .all()
    )
    return schemas.ProfileOut(
        rating=player.rating,
        peak=player.peak,
        skills=dict(player.skills),
        streak=player.streak,
        best_streak=player.best_streak,
        rounds=player.rounds,
        history=[
            schemas.RoundRecordOut(
                at=to_ms(r.at), skill=r.skill, correct=r.correct, time_ms=r.time_ms, delta=r.delta, problem_rating=r.problem_rating
            )
            for r in reversed(history_rows)  # oldest first, like the frontend expects
        ],
        days={d.isoformat(): schemas.DayStatOut(rounds=int(n), correct=int(c or 0)) for d, n, c in day_rows},
        daily={
            r.day.isoformat(): schemas.DailyResultOut(correct=r.correct, total=r.total, time_ms=r.time_ms) for r in daily_rows
        },
    )

"""Domain logic: players, applying a round to a rating, building the profile. Talks to the DB only."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from magnitude_engine import DEFAULT_RATING, EloUpdate, update_player

from . import schemas
from .models import DailyResult, Player, Round, default_skills, utcnow


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:  # SQLite drops tzinfo; everything we store is UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


async def create_player(session: AsyncSession) -> tuple[Player, str]:
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
        )
    )
    return overall


def answer_out(player: Player, update: EloUpdate, *, correct: bool, answer: str, left: float, right: float) -> dict:
    return {
        "correct": correct,
        "answer": answer,
        "values": schemas.Revealed(left=left, right=right),
        "delta": update.delta,
        "expected": update.expected,
        "score": update.score,
        "rating": player.rating,
        "peak": player.peak,
        "streak": player.streak,
        "skills": dict(player.skills),
        "rounds": player.rounds,
    }


async def daily_answered_count(session: AsyncSession, player_id: uuid.UUID, day) -> int:
    result = await session.execute(
        select(func.count()).select_from(Round).where(Round.player_id == player_id, Round.local_date == day, Round.mode == "daily")
    )
    return int(result.scalar_one())


async def daily_result(session: AsyncSession, player_id: uuid.UUID, day) -> DailyResult | None:
    result = await session.execute(select(DailyResult).where(DailyResult.player_id == player_id, DailyResult.day == day))
    return result.scalar_one_or_none()


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
                select(Round).where(Round.player_id == player.id).order_by(Round.at.desc(), Round.id.desc()).limit(200)
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

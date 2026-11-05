from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, SmallInteger, String, Uuid, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from magnitude_engine import DEFAULT_RATING, SKILLS

# JSONB on Postgres, plain JSON elsewhere (the tests run on SQLite).
JSONType = JSON().with_variant(JSONB(), "postgresql")
BigPK = BigInteger().with_variant(Integer(), "sqlite")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def default_skills() -> dict[str, float]:
    return {s: DEFAULT_RATING for s in SKILLS}


class Base(DeclarativeBase):
    pass


class Player(Base):
    """One anonymous player per device. `token_hash` is the SHA-256 of the bearer token."""

    __tablename__ = "players"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    rating: Mapped[float] = mapped_column(Float, default=DEFAULT_RATING)
    peak: Mapped[float] = mapped_column(Float, default=DEFAULT_RATING)
    streak: Mapped[int] = mapped_column(Integer, default=0)
    best_streak: Mapped[int] = mapped_column(Integer, default=0)
    rounds: Mapped[int] = mapped_column(Integer, default=0)
    skills: Mapped[dict[str, float]] = mapped_column(JSONType, default=default_skills)


class Round(Base):
    __tablename__ = "rounds"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    player_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("players.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    skill: Mapped[str] = mapped_column(String(16))
    correct: Mapped[bool] = mapped_column(Boolean)
    time_ms: Mapped[int] = mapped_column(Integer)
    delta: Mapped[float] = mapped_column(Float)
    rating_after: Mapped[float] = mapped_column(Float)
    problem_rating: Mapped[int] = mapped_column(Integer)
    problem_id: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(8))  # "practice" | "daily"
    local_date: Mapped[date] = mapped_column(Date)  # the player's own calendar day
    daily_index: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    __table_args__ = (
        Index("ix_rounds_player_at", "player_id", "at"),
        Index("ix_rounds_player_local_date", "player_id", "local_date"),
        # A daily problem can only be answered once per player per day.
        Index(
            "uq_rounds_daily",
            "player_id", "local_date", "daily_index",
            unique=True,
            postgresql_where=text("mode = 'daily'"),
            sqlite_where=text("mode = 'daily'"),
        ),
    )


class DailyResult(Base):
    __tablename__ = "daily_results"

    player_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("players.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    correct: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    time_ms: Mapped[int] = mapped_column(Integer)

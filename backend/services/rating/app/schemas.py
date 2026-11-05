"""Wire formats. JSON is camelCase so the Next.js app can use the responses as its Profile type unchanged."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from magnitude_engine import Side, Skill


class Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---- players
class PlayerCreated(Wire):
    player_id: UUID
    token: str


# ---- problems (public: never contains the answer or the values)
class PublicExpr(Wire):
    text: str


class PublicProblem(Wire):
    id: str
    skill: Skill
    left: PublicExpr
    right: PublicExpr
    rating: int
    expires_in_ms: int


class DailyProblemPublic(Wire):
    index: int
    id: str
    skill: Skill
    left: PublicExpr
    right: PublicExpr
    rating: int


# ---- answering
class AnswerIn(Wire):
    problem_id: str = Field(min_length=1, max_length=64)
    choice: Side | None = None  # null = the player ran out of time
    time_ms: int = Field(ge=0, le=120_000)
    local_date: date


class DailyAnswerIn(Wire):
    index: int = Field(ge=0, le=9)
    choice: Side | None = None
    time_ms: int = Field(ge=0, le=120_000)


class Revealed(Wire):
    left: float
    right: float


class AnswerOut(Wire):
    correct: bool
    answer: Side
    values: Revealed
    delta: float
    expected: float
    score: float
    rating: float
    peak: float
    streak: int
    skills: dict[str, float]
    rounds: int


class DailyResultOut(Wire):
    correct: int
    total: int
    time_ms: int


class DailyAnswerOut(AnswerOut):
    index: int
    complete: bool
    result: DailyResultOut | None = None
    rating_delta: float | None = None


class DailySetOut(Wire):
    date: str
    problems: list[DailyProblemPublic]
    answered: int
    result: DailyResultOut | None = None


# ---- profile (same shape as `Profile` in lib/engine/types.ts)
class RoundRecordOut(Wire):
    at: int  # ms since epoch
    skill: Skill
    correct: bool
    time_ms: int
    delta: float
    problem_rating: int


class DayStatOut(Wire):
    rounds: int
    correct: int


class ProfileOut(Wire):
    rating: float
    peak: float
    skills: dict[str, float]
    streak: int
    best_streak: int
    rounds: int
    history: list[RoundRecordOut]
    days: dict[str, DayStatOut]
    daily: dict[str, DailyResultOut]

"""Wire formats. JSON is camelCase so the Next.js app can use the responses as its Profile type unchanged."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from magnitude_engine import SKILLS, Side, Skill


Day = date  # fields named `date` would otherwise shadow the type inside their own class body


class Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---- players
class PlayerCreated(Wire):
    player_id: UUID
    token: str


class DailyResultOut(Wire):
    correct: int
    total: int
    time_ms: int


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


# ---------------------------------------------------------------- Phase 4: sessions and sync
class SessionTicket(Wire):
    session_id: UUID
    seed: int
    expires_at: int  # ms since epoch


class _EventBase(Wire):
    choice: Side | None = None  # null = the player ran out of time
    time_ms: int = Field(ge=0, le=120_000)  # whole ms; the server normalizes it exactly like the client did
    at: int = Field(ge=0)  # client clock, ms since epoch, when the answer was given
    # What the client believes the problem was. The server recomputes it and rejects on a difference.
    problem_id: str = Field(min_length=1, max_length=64)
    skill: Skill
    problem_rating: int
    correct: bool  # informational only: the server grades from `choice`


class PracticeEvent(_EventBase):
    kind: Literal["practice"]
    session_id: UUID
    index: int = Field(ge=0, le=100_000)
    start_skills: dict[str, float] | None = None  # round 0 only
    local_date: date


class DailyEvent(_EventBase):
    kind: Literal["daily"]
    date: Day
    index: int = Field(ge=0, le=100)


SyncEvent = Annotated[Union[PracticeEvent, DailyEvent], Field(discriminator="kind")]

RejectReason = Literal[
    "unknown_session", "expired", "session_broken", "gap", "mismatch", "bad_start",
    "implausible_time", "bad_date", "out_of_range",
]


class SyncIn(Wire):
    events: list[SyncEvent] = Field(min_length=1, max_length=200)


class EventRef(Wire):
    kind: Literal["practice", "daily"]
    session_id: UUID | None = None  # practice
    date: Day | None = None  # daily
    index: int


class RejectedEvent(EventRef):
    reason: RejectReason


class SyncOut(Wire):
    acked: list[EventRef]  # includes duplicates: the server already had them
    rejected: list[RejectedEvent]
    profile: ProfileOut


# ---- one-time import of a pre-Phase-4 browser profile
class ImportedRound(RoundRecordOut):
    """A history record plus the player's local calendar day, which only the browser can compute."""

    local_date: Day


class ProfileImport(Wire):
    """A browser profile from before Phase 4 (same shape as `Profile` in lib/engine/types.ts). Taken as-is, once."""

    rating: float = Field(ge=0, le=4000)
    peak: float = Field(ge=0, le=4000)
    skills: dict[Skill, float]
    streak: int = Field(ge=0, le=1_000_000)
    best_streak: int = Field(ge=0, le=1_000_000)
    rounds: int = Field(ge=0, le=10_000_000)
    @field_validator("skills")
    @classmethod
    def _all_skills(cls, v: dict[Skill, float]) -> dict[Skill, float]:
        if set(v) != set(SKILLS) or not all(0 <= x <= 4000 for x in v.values()):
            raise ValueError("skills must hold all four skills, each between 0 and 4000")
        return v

    history: list[ImportedRound] = Field(default_factory=list, max_length=200)
    days: dict[str, DayStatOut] = Field(default_factory=dict, max_length=400)
    daily: dict[str, DailyResultOut] = Field(default_factory=dict, max_length=400)


class PlayerCreateIn(Wire):
    import_profile: ProfileImport | None = Field(default=None, alias="import")

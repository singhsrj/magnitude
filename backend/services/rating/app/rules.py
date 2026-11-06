"""Game rules that don't need a database or Redis. Pure functions, easy to test."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Mapping

from magnitude_engine import SKILLS

# ---- Phase 4 (offline play + sync) tolerances
SESSION_TTL = timedelta(days=7)  # unused ticket lifetime, and how long after play its events are accepted
FUTURE_SLACK = timedelta(seconds=60)  # the client clock may run a little ahead of ours
START_SKILL_TOLERANCE = 300  # a session's declared starting skills vs. the server's
TIME_SLACK_PER_ROUND_MS = 2000  # the sum of think times may exceed wall-clock time by this much per round

# ---------------------------------------------------------------------------- Phase 4: sync plausibility
def ms_to_datetime(ms: int) -> datetime:
    """Exact (integer) conversion: going through float seconds would lose a millisecond now and then."""
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=ms)


def as_utc(dt: datetime) -> datetime:
    """SQLite drops tzinfo; everything we store is UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def datetime_to_ms(dt: datetime) -> int:
    return (as_utc(dt) - datetime(1970, 1, 1, tzinfo=timezone.utc)) // timedelta(milliseconds=1)


def at_plausible(at: datetime, now: datetime, not_before: datetime | None = None) -> bool:
    """An answer can't be from the future, or from before its session was issued."""
    if at > now + FUTURE_SLACK:
        return False
    return not_before is None or at >= as_utc(not_before) - FUTURE_SLACK


def local_date_matches(local_date: date, at: datetime) -> bool:
    """The player's calendar day is within one day of the UTC day of the moment they answered."""
    return abs((local_date - as_utc(at).date()).days) <= 1


def start_skills_plausible(declared: Mapping[str, float], server: Mapping[str, float]) -> bool:
    """A session's starting skills must be close to the server's (they only steer problem difficulty)."""
    try:
        return all(abs(float(declared[s]) - float(server[s])) <= START_SKILL_TOLERANCE for s in SKILLS)
    except (KeyError, TypeError, ValueError):
        return False


def session_time_plausible(time_sum_ms: int, round_zero_start: datetime, at: datetime, rounds: int) -> bool:
    """Think times can't add up to more time than actually passed since round 0 began."""
    elapsed_ms = (as_utc(at) - as_utc(round_zero_start)) // timedelta(milliseconds=1)
    return time_sum_ms <= elapsed_ms + TIME_SLACK_PER_ROUND_MS * rounds

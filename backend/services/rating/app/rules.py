"""Game rules that don't need a database or Redis. Pure functions, easy to test."""
from __future__ import annotations

from datetime import date, timedelta

from magnitude_engine import ROUND_LIMIT_MS

MIN_TIME_MS = 120
# Server-observed time includes network travel both ways, so allow this much before
# treating the client's own (smaller) clock as suspicious.
LATENCY_SLACK_MS = 2000


def effective_time_ms(client_ms: int, server_elapsed_ms: float | None) -> int:
    """Time used for scoring.

    The client measures its own think time, which is the fair number. But a client could claim
    a fast time it didn't earn, so it can't be lower than what the server observed minus slack.
    """
    t = min(max(client_ms, MIN_TIME_MS), ROUND_LIMIT_MS)
    if server_elapsed_ms is not None:
        t = max(t, min(ROUND_LIMIT_MS, int(server_elapsed_ms) - LATENCY_SLACK_MS))
    return t


def timed_out(choice: str | None, server_elapsed_ms: float | None) -> bool:
    if choice is None:
        return True
    return server_elapsed_ms is not None and server_elapsed_ms > ROUND_LIMIT_MS + LATENCY_SLACK_MS


def local_date_ok(client_date: date, utc_today: date) -> bool:
    """A client's local day is within one day of UTC's (timezones run from UTC-12 to UTC+14)."""
    return abs((client_date - utc_today).days) <= 1


def days_back(today: date, n: int) -> date:
    return today - timedelta(days=n)

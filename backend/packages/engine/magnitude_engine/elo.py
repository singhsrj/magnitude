"""Elo with a speed-adjusted outcome. Mirrors lib/engine/elo.ts."""
from __future__ import annotations

from dataclasses import dataclass
import math

from .jsmath import clamp

DEFAULT_RATING = 1200.0
K_FACTOR = 24
TIME_FAST_MS = 800
TIME_SLOW_MS = 6000
ROUND_LIMIT_MS = 8000
TARGET_WIN_RATE = 0.7


def expected_score(player: float, problem: float) -> float:
    return 1 / (1 + math.pow(10, (problem - player) / 400))


def outcome_score(correct: bool, time_ms: float) -> float:
    if not correct:
        return 0.0
    speed = clamp((TIME_SLOW_MS - time_ms) / (TIME_SLOW_MS - TIME_FAST_MS), 0, 1)
    return 0.7 + 0.3 * speed


def target_problem_rating(player: float, target_win: float = TARGET_WIN_RATE) -> float:
    return player + 400 * math.log10((1 - target_win) / target_win)


@dataclass(frozen=True)
class EloUpdate:
    next: float
    delta: float
    expected: float
    score: float


def update_player(player: float, problem: float, correct: bool, time_ms: float) -> EloUpdate:
    expected = expected_score(player, problem)
    score = outcome_score(correct, time_ms)
    delta = K_FACTOR * (score - expected)
    return EloUpdate(next=player + delta, delta=delta, expected=expected, score=score)

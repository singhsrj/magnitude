"""Seeded daily set. Mirrors lib/engine/daily.ts."""
from __future__ import annotations

from .problems import generate_problem
from .rng import mulberry32
from .types import SKILLS, Problem

DAILY_LENGTH = 10
_TARGETS = [1000, 1050, 1100, 1200, 1250, 1300, 1400, 1450, 1550, 1650]
_M = 0xFFFFFFFF


def daily_seed(key: str) -> int:
    """FNV-1a over the UTF-16 code units of the date key (ASCII here, so ord() matches charCodeAt)."""
    h = 2166136261
    for ch in key:
        h ^= ord(ch)
        h = (h * 16777619) & _M
    return h & _M


def daily_problem(key: str, index: int) -> Problem:
    seed = daily_seed(key)
    return generate_problem(
        SKILLS[(seed + index) % len(SKILLS)],
        _TARGETS[index],
        mulberry32((seed ^ (((index + 1) * 0x9E3779B1) & _M)) & _M),
    )


def daily_set(key: str) -> list[Problem]:
    return [daily_problem(key, i) for i in range(DAILY_LENGTH)]

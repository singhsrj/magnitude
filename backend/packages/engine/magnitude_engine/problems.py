"""Problem generation. Mirrors lib/engine/problems.ts step for step.

The order and number of rng() draws must match the TypeScript version exactly,
otherwise the same seed produces different problems. Change both or neither,
and regenerate the golden vectors (npm run golden).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from .jsmath import base36, clamp, js_round
from .rng import Rng, pick, rand_int
from .types import Expr, Problem, Side, Skill

_SUP = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def _sup(n: int) -> str:
    return str(n).translate(_SUP)


SKILL_OFFSET: dict[str, int] = {"multiplication": 0, "percentages": -40, "fractions": 30, "powers": 60}


@dataclass(frozen=True)
class _Candidate:
    left: Expr
    right: Expr
    size: float


def difficulty(skill: str, size: float, left: float, right: float) -> int:
    hi = max(abs(left), abs(right))
    gap = abs(left - right) / hi
    closeness = min(-math.log10(max(gap, 0.0005)) * 200, 700)
    return js_round(600 + SKILL_OFFSET[skill] + size * 140 + closeness)


_A_TIERS = [(3, 19), (12, 99), (101, 499), (101, 999)]
_B_TIERS = [(3, 9), (12, 99), (12, 99), (101, 299)]


def _multiplication(rng: Rng) -> _Candidate:
    t = rand_int(rng, 0, len(_A_TIERS) - 1)
    a = rand_int(rng, *_A_TIERS[t])
    b = rand_int(rng, *_B_TIERS[t])
    v1 = a * b
    spread = max(2, js_round(a * 0.15))
    jitter = pick(rng, [0, 1, 2, 3, 6, 12])
    c = max(3, a + rand_int(rng, -spread, spread))
    d = max(3, js_round(v1 / c) + rand_int(rng, -jitter, jitter))
    return _Candidate(Expr(f"{a} × {b}", v1), Expr(f"{c} × {d}", c * d), math.log10(max(v1, c * d)))


def _percentages(rng: Rng) -> _Candidate:
    tier = rand_int(rng, 0, 2)

    def pct() -> int:
        return rand_int(rng, 1, 99) if tier == 2 else rand_int(rng, 1, 19) * 5

    def base() -> int:
        if tier == 0:
            return rand_int(rng, 2, 40) * 10
        if tier == 1:
            return rand_int(rng, 25, 999)
        return rand_int(rng, 120, 1999)

    x = pct()
    n = base()
    v1 = (x * n) / 100
    if rng() < 0.5:
        off = pick(rng, [-0.2, -0.08, -0.03, -0.01, 0.01, 0.03, 0.08, 0.2])
        n2 = max(1, js_round(v1 * (1 + off)))
        right = Expr(str(n2), n2)
    else:
        y = pct()
        m = base()
        right = Expr(f"{y}% of {m}", (y * m) / 100)
    return _Candidate(Expr(f"{x}% of {n}", v1), right, math.log10(n) + tier * 0.4)


def _fractions(rng: Rng) -> _Candidate:
    t = rand_int(rng, 0, 2)
    max_den = [12, 24, 60][t]
    b = rand_int(rng, 3, max_den)
    a = rand_int(rng, 1, b - 1)
    d = rand_int(rng, 3, max_den)
    jit = pick(rng, [0, 1, 2])
    if rng() < 0.7:
        c = int(clamp(js_round((a / b) * d) + rand_int(rng, -jit, jit), 1, d - 1))
    else:
        c = rand_int(rng, 1, d - 1)
    return _Candidate(Expr(f"{a}/{b}", a / b), Expr(f"{c}/{d}", c / d), math.log10(b * d) + t * 0.3)


def _powers(rng: Rng) -> _Candidate:
    t = rand_int(rng, 0, 2)
    max_base = [9, 12, 16][t]
    max_exp = [5, 7, 9][t]
    a = rand_int(rng, 2, max_base)
    m = rand_int(rng, 2, max_exp)
    v1 = a**m
    n = rand_int(rng, 2, max_exp)
    if rng() < 0.7:
        b = max(2, js_round(float(v1) ** (1 / n)) + rand_int(rng, -1, 1))
    else:
        b = rand_int(rng, 2, max_base)
    v2 = b**n
    return _Candidate(Expr(f"{a}{_sup(m)}", v1), Expr(f"{b}{_sup(n)}", v2), math.log10(max(v1, v2)) * 0.7)


_MAKE: dict[str, Callable[[Rng], _Candidate]] = {
    "multiplication": _multiplication,
    "percentages": _percentages,
    "fractions": _fractions,
    "powers": _powers,
}


def generate_problem(skill: Skill, target_rating: float, rng: Rng) -> Problem:
    """Sample candidates and keep the one whose difficulty is closest to the target."""
    best: tuple[_Candidate, int, float] | None = None
    valid = 0
    attempts = 0
    while attempts < 512 and valid < 64:
        attempts += 1
        cand = _MAKE[skill](rng)
        hi = max(abs(cand.left.value), abs(cand.right.value))
        if abs(cand.left.value - cand.right.value) / hi < 0.0005:
            continue  # too close to call
        valid += 1
        rating = difficulty(skill, cand.size, cand.left.value, cand.right.value)
        dist = abs(rating - target_rating)
        if best is None or dist < best[2]:
            best = (cand, rating, dist)
    if best is None:
        raise RuntimeError(f"could not generate a {skill} problem")

    cand, rating, _ = best
    swap = rng() < 0.5
    left, right = (cand.right, cand.left) if swap else (cand.left, cand.right)
    answer: Side = "left" if left.value > right.value else "right"
    return Problem(
        id=f"{skill}-{base36(int(rng() * 1e9))}",
        skill=skill,
        left=left,
        right=right,
        rating=rating,
        answer=answer,
    )

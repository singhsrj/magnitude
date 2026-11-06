"""Skill selection. Mirrors pickSkill in lib/engine/session.ts."""
from __future__ import annotations

from typing import Mapping

from .elo import target_problem_rating, update_player
from .jsmath import js_round
from .problems import generate_problem
from .rng import Rng, mulberry32
from .types import SKILLS, Problem, Skill

SESSION_MAX_ROUNDS = 500
_M = 0xFFFFFFFF


def pick_skill(rng: Rng, skills: Mapping[str, float]) -> Skill:
    """Weaker skills come up more often, but every skill stays in rotation."""
    avg = sum(skills[s] for s in SKILLS) / len(SKILLS)
    weights = [1 + min(2.0, max(0.0, (avg - skills[s]) / 150)) for s in SKILLS]
    roll = rng() * sum(weights)
    for i, s in enumerate(SKILLS):
        roll -= weights[i]
        if roll <= 0:
            return s
    return SKILLS[-1]


def round_rng(seed: int, index: int) -> Rng:
    """One generator per round. Mirrors roundRng: seed ^ Math.imul(index + 1, 0x9e3779b1)."""
    return mulberry32((seed ^ (((index + 1) * 0x9E3779B1) & _M)) & _M)


def round_skills(skills: Mapping[str, float]) -> dict[str, int]:
    """Ratings as whole numbers (Math.round), so problem choice never depends on float noise."""
    return {s: js_round(skills[s]) for s in SKILLS}


def session_problem(seed: int, index: int, gen: Mapping[str, float]) -> Problem:
    """Problem `index` of a practice session. Mirrors sessionProblem in lib/engine/session.ts."""
    rng = round_rng(seed, index)
    rounded = round_skills(gen)
    skill = pick_skill(rng, rounded)
    target = js_round(target_problem_rating(rounded[skill]))
    return generate_problem(skill, target, rng)


def next_gen_skills(gen: Mapping[str, float], skill: str, problem_rating: float, correct: bool, time_ms: float) -> dict[str, float]:
    """Generation skills after a round (floats are kept; rounded only when a problem is picked)."""
    out = dict(gen)
    out[skill] = update_player(gen[skill], problem_rating, correct, time_ms).next
    return out

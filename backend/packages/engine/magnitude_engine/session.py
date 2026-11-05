"""Skill selection. Mirrors pickSkill in lib/engine/session.ts."""
from __future__ import annotations

from typing import Mapping

from .rng import Rng
from .types import SKILLS, Skill


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

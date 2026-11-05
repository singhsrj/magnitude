from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Skill = Literal["multiplication", "percentages", "fractions", "powers"]
SKILLS: tuple[Skill, ...] = ("multiplication", "percentages", "fractions", "powers")
Side = Literal["left", "right"]


@dataclass(frozen=True)
class Expr:
    text: str
    value: float


@dataclass(frozen=True)
class Problem:
    id: str
    skill: Skill
    left: Expr
    right: Expr
    rating: int
    answer: Side

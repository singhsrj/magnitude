from __future__ import annotations

from pydantic import BaseModel, Field

from magnitude_engine import Problem, Side, Skill


class ExprOut(BaseModel):
    text: str
    value: float


class ProblemOut(BaseModel):
    """Internal view of a problem: includes the answer, so it must never reach a browser."""

    id: str
    skill: Skill
    left: ExprOut
    right: ExprOut
    rating: int
    answer: Side

    @classmethod
    def from_engine(cls, p: Problem) -> "ProblemOut":
        return cls(
            id=p.id,
            skill=p.skill,
            left=ExprOut(text=p.left.text, value=p.left.value),
            right=ExprOut(text=p.right.text, value=p.right.value),
            rating=p.rating,
            answer=p.answer,
        )


class GenerateIn(BaseModel):
    skill: Skill
    target_rating: float = Field(ge=0, le=4000)


class DailySetOut(BaseModel):
    date: str
    problems: list[ProblemOut]

from __future__ import annotations

import logging
import random
import secrets
import time
from dataclasses import asdict
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from magnitude_engine import DAILY_LENGTH, ROUND_LIMIT_MS, Expr, Problem, pick_skill, target_problem_rating

from . import schemas, service
from .deps import current_player, enforce_limit, get_session
from .models import Player
from .problems_client import UpstreamError, problem_from_json
from .rules import effective_time_ms, local_date_ok, timed_out

log = logging.getLogger("routes")
router = APIRouter()
v1 = APIRouter(prefix="/v1")


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _check_local_date(day: date) -> None:
    if not local_date_ok(day, _utc_today()):
        raise HTTPException(status_code=422, detail="date is too far from today")


def _public(expr: Expr) -> schemas.PublicExpr:
    return schemas.PublicExpr(text=expr.text)


async def _load_daily(request: Request, key: str) -> list[Problem]:
    """The day's problems with answers: Redis first, problem service on a miss."""
    state = request.app.state
    cached = await state.cache.get_daily(key)
    if cached:
        return [problem_from_json(p) for p in cached]
    try:
        problems = await state.problems.daily(key)
    except UpstreamError:
        raise HTTPException(status_code=503, detail="problem service unavailable") from None
    await state.cache.put_daily(key, [asdict(p) for p in problems])
    return problems


# ---------------------------------------------------------------- players & profile
@v1.post("/players", status_code=201, response_model=schemas.PlayerCreated)
async def sign_up(request: Request, session: AsyncSession = Depends(get_session)):
    """Anonymous account for this device. The token is shown once; the server keeps only its hash."""
    ip = request.client.host if request.client else "unknown"
    await enforce_limit(request, f"signup:{ip}", request.app.state.settings.signup_limit_per_hour, 3600)
    player, token = await service.create_player(session)
    return schemas.PlayerCreated(player_id=player.id, token=token)


@v1.get("/profile", response_model=schemas.ProfileOut)
async def get_profile(request: Request, player: Player = Depends(current_player), session: AsyncSession = Depends(get_session)):
    cache = request.app.state.cache
    cached = await cache.get_profile(player.id)
    if cached:
        return Response(content=cached, media_type="application/json", headers={"X-Cache": "hit"})
    profile = await service.build_profile(session, player)
    body = profile.model_dump_json(by_alias=True)
    await cache.put_profile(player.id, body)
    return Response(content=body, media_type="application/json", headers={"X-Cache": "miss"})


# ---------------------------------------------------------------- practice rounds
@v1.post("/rounds/next", response_model=schemas.PublicProblem)
async def next_round(request: Request, player: Player = Depends(current_player)):
    state = request.app.state
    skill = pick_skill(random.random, player.skills)
    target = target_problem_rating(player.skills[skill])
    try:
        problem = await state.problems.generate(skill, target)
    except UpstreamError:
        raise HTTPException(status_code=503, detail="problem service unavailable") from None

    # Our own opaque id: the engine's id is guessable and only needs to be unique per problem.
    problem_id = secrets.token_urlsafe(12)
    record = {
        "playerId": str(player.id),
        "skill": problem.skill,
        "rating": problem.rating,
        "answer": problem.answer,
        "left": problem.left.value,
        "right": problem.right.value,
        "issuedAt": time.time() * 1000,
    }
    try:
        await state.cache.put_problem(problem_id, record)
    except RedisError:
        raise HTTPException(status_code=503, detail="cache unavailable") from None

    return schemas.PublicProblem(
        id=problem_id,
        skill=problem.skill,
        left=_public(problem.left),
        right=_public(problem.right),
        rating=problem.rating,
        expires_in_ms=state.settings.problem_ttl_seconds * 1000,
    )


@v1.post("/rounds/answer", response_model=schemas.AnswerOut)
async def answer_round(
    body: schemas.AnswerIn,
    request: Request,
    player: Player = Depends(current_player),
    session: AsyncSession = Depends(get_session),
):
    state = request.app.state
    _check_local_date(body.local_date)
    try:
        record = await state.cache.take_problem(body.problem_id)  # also deletes it: one answer per problem
    except RedisError:
        raise HTTPException(status_code=503, detail="cache unavailable") from None
    if record is None or record["playerId"] != str(player.id):
        raise HTTPException(status_code=404, detail="problem expired or unknown")

    elapsed_ms = time.time() * 1000 - record["issuedAt"]
    time_ms = effective_time_ms(body.time_ms, elapsed_ms)
    correct = (not timed_out(body.choice, elapsed_ms)) and body.choice == record["answer"]

    locked = await service.lock_player(session, player.id)
    update = service.apply_outcome(
        session,
        locked,
        skill=record["skill"],
        problem_rating=record["rating"],
        correct=correct,
        time_ms=time_ms,
        problem_id=body.problem_id,
        mode="practice",
        local_date=body.local_date,
    )
    await session.commit()
    await state.cache.drop_profile(player.id)
    return schemas.AnswerOut(
        **service.answer_out(locked, update, correct=correct, answer=record["answer"], left=record["left"], right=record["right"])
    )


# ---------------------------------------------------------------- daily set
@v1.get("/daily/{day}", response_model=schemas.DailySetOut)
async def get_daily(day: date, request: Request, player: Player = Depends(current_player), session: AsyncSession = Depends(get_session)):
    _check_local_date(day)
    problems = await _load_daily(request, day.isoformat())
    answered = await service.daily_answered_count(session, player.id, day)
    done = await service.daily_result(session, player.id, day)
    return schemas.DailySetOut(
        date=day.isoformat(),
        problems=[
            schemas.DailyProblemPublic(index=i, id=p.id, skill=p.skill, left=_public(p.left), right=_public(p.right), rating=p.rating)
            for i, p in enumerate(problems)
        ],
        answered=answered,
        result=schemas.DailyResultOut(correct=done.correct, total=done.total, time_ms=done.time_ms) if done else None,
    )


@v1.post("/daily/{day}/answer", response_model=schemas.DailyAnswerOut)
async def answer_daily(
    day: date,
    body: schemas.DailyAnswerIn,
    request: Request,
    player: Player = Depends(current_player),
    session: AsyncSession = Depends(get_session),
):
    state = request.app.state
    _check_local_date(day)
    problems = await _load_daily(request, day.isoformat())
    problem = problems[body.index]

    locked = await service.lock_player(session, player.id)  # serializes concurrent submissions
    answered = await service.daily_answered_count(session, player.id, day)
    if answered >= DAILY_LENGTH:
        raise HTTPException(status_code=409, detail="today's set is already complete")
    if body.index != answered:
        raise HTTPException(status_code=409, detail=f"answer in order: next is problem {answered}")

    time_ms = effective_time_ms(body.time_ms, None)
    correct = body.choice is not None and body.choice == problem.answer
    update = service.apply_outcome(
        session,
        locked,
        skill=problem.skill,
        problem_rating=problem.rating,
        correct=correct,
        time_ms=time_ms,
        problem_id=problem.id,
        mode="daily",
        local_date=day,
        daily_index=body.index,
    )
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="that daily problem was already answered") from None

    complete = body.index == DAILY_LENGTH - 1
    result, rating_delta = (await service.finish_daily(session, locked, day)) if complete else (None, None)
    await session.commit()
    await state.cache.drop_profile(player.id)
    return schemas.DailyAnswerOut(
        **service.answer_out(locked, update, correct=correct, answer=problem.answer, left=problem.left.value, right=problem.right.value),
        index=body.index,
        complete=complete,
        result=result,
        rating_delta=rating_delta,
    )


# ---------------------------------------------------------------- health
@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readyz(request: Request, response: Response) -> dict[str, bool]:
    """Checks each dependency; 503 if any is down. Use this for deploy health checks, not healthz."""
    state = request.app.state
    checks = {"redis": await state.cache.ping(), "problem_service": await state.problems.healthy(), "database": False}
    try:
        async with state.session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as exc:  # noqa: BLE001 - any failure means "not ready"
        log.warning("database readiness check failed: %s", exc)
    if not all(checks.values()):
        response.status_code = 503
    return checks


router.include_router(v1)

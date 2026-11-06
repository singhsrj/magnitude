from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from . import schemas, service, sync
from .deps import current_player, enforce_limit, get_session
from .models import Player, utcnow
from .rules import datetime_to_ms

log = logging.getLogger("routes")
router = APIRouter()
v1 = APIRouter(prefix="/v1")


# ---------------------------------------------------------------- players & profile
@v1.post("/players", status_code=201, response_model=schemas.PlayerCreated)
async def sign_up(
    request: Request, body: schemas.PlayerCreateIn | None = None, session: AsyncSession = Depends(get_session)
):
    """Anonymous account for this device. The token is shown once; the server keeps only its hash.

    The body is optional: `{"import": <Profile>}` carries a pre-Phase-4 browser profile, accepted once, unverified."""
    ip = request.client.host if request.client else "unknown"
    await enforce_limit(request, f"signup:{ip}", request.app.state.settings.signup_limit_per_hour, 3600)
    player, token = await service.create_player(session, body.import_profile if body else None)
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


# ---------------------------------------------------------------- offline play + sync
@v1.post("/sessions", status_code=201, response_model=schemas.SessionTicket)
async def new_session(request: Request, player: Player = Depends(current_player), db: AsyncSession = Depends(get_session)):
    """A ticket (id + seed) for one offline practice session. The browser keeps a couple in reserve."""
    await enforce_limit(request, f"sess:{player.id}", request.app.state.settings.session_limit_per_minute, 60)
    gs = await sync.create_session(db, player.id, utcnow())
    await db.commit()
    return schemas.SessionTicket(session_id=gs.id, seed=gs.seed, expires_at=datetime_to_ms(gs.expires_at))


@v1.post("/sync", response_model=schemas.SyncOut)
async def sync_events(
    body: schemas.SyncIn,
    request: Request,
    player: Player = Depends(current_player),
    db: AsyncSession = Depends(get_session),
):
    """Replays the browser's offline rounds. One transaction, one lock on the player row, idempotent."""
    locked = await service.lock_player(db, player.id)  # serializes concurrent syncs
    acked, rejected = await sync.replay(db, locked, body.events, utcnow())
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="conflicting sync, retry") from None
    cache = request.app.state.cache
    await cache.drop_profile(player.id)
    profile = await service.build_profile(db, locked)
    await cache.put_profile(player.id, profile.model_dump_json(by_alias=True))
    return schemas.SyncOut(acked=acked, rejected=rejected, profile=profile)


# ---------------------------------------------------------------- health
@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readyz(request: Request, response: Response) -> dict[str, bool]:
    """Checks each dependency; 503 if any is down. Use this for deploy health checks, not healthz."""
    state = request.app.state
    checks = {"redis": await state.cache.ping(), "database": False}
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

from __future__ import annotations

from typing import AsyncIterator

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from . import service
from .models import Player


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


async def enforce_limit(request: Request, key: str, limit: int, window_seconds: int) -> None:
    count = await request.app.state.cache.hit(key, window_seconds)
    if count is not None and count > limit:
        raise HTTPException(status_code=429, detail="too many requests", headers={"Retry-After": str(window_seconds)})


async def current_player(
    request: Request,
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
) -> Player:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    player = await service.find_player_by_token(session, token.strip())
    if player is None:
        raise HTTPException(status_code=401, detail="unknown token", headers={"WWW-Authenticate": "Bearer"})
    await enforce_limit(request, f"rl:{player.id}", request.app.state.settings.rate_limit_per_minute, 60)
    return player

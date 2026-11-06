from __future__ import annotations

from typing import AsyncIterator

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from . import service
from .clerk import ClerkAuthError, looks_like_jwt
from .models import Player


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


async def enforce_limit(request: Request, key: str, limit: int, window_seconds: int) -> None:
    count = await request.app.state.cache.hit(key, window_seconds)
    if count is not None and count > limit:
        raise HTTPException(status_code=429, detail="too many requests", headers={"Retry-After": str(window_seconds)})


def bearer(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    return token.strip()


async def clerk_user_id(request: Request, token: str) -> str:
    """The Clerk user a session token belongs to, or a 401."""
    verifier = request.app.state.clerk
    if verifier is None:
        raise HTTPException(
            status_code=401, detail="account sign-in isn't enabled on this server", headers={"WWW-Authenticate": "Bearer"}
        )
    try:
        return await verifier.verify(token)
    except ClerkAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc), headers={"WWW-Authenticate": "Bearer"}) from None


async def current_player(
    request: Request,
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
) -> Player:
    """A device token (anonymous) or a Clerk session token (signed in); both end at the same kind of player row."""
    token = bearer(authorization)
    if looks_like_jwt(token):
        user_id = await clerk_user_id(request, token)
        player = await service.find_player_by_clerk(session, user_id)
        if player is None:
            raise HTTPException(status_code=401, detail="account not linked", headers={"WWW-Authenticate": "Bearer"})
    else:
        player = await service.find_player_by_token(session, token)
        if player is None:
            raise HTTPException(status_code=401, detail="unknown token", headers={"WWW-Authenticate": "Bearer"})
    await enforce_limit(request, f"rl:{player.id}", request.app.state.settings.rate_limit_per_minute, 60)
    return player

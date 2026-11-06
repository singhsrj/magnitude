from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from .cache import Cache
from .clerk import ClerkVerifier, issuer_from_publishable_key
from .config import Settings
from .db import make_engine, make_session_factory
from .routes import router


def create_app(
    settings: Settings | None = None,
    *,
    engine: AsyncEngine | None = None,
    redis: Redis | None = None,
    clerk: ClerkVerifier | None = None,
) -> FastAPI:
    """App factory. Tests inject a SQLite engine and fakeredis."""
    settings = settings or Settings()
    logging.basicConfig(level=settings.log_level)

    if engine is None:
        engine = make_engine(settings.database_url)
    if redis is None:
        redis = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
            health_check_interval=30,
        )
    if clerk is None:
        issuer = settings.clerk_issuer or (
            issuer_from_publishable_key(settings.clerk_publishable_key) if settings.clerk_publishable_key else None
        )
        if issuer:
            clerk = ClerkVerifier(
                issuer,
                jwks_url=settings.clerk_jwks_url,
                origins=settings.cors_origin_list,
                origin_regex=settings.cors_origin_regex,
            )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await redis.aclose()
        await engine.dispose()

    app = FastAPI(title="Magnitude rating service", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.clerk = clerk  # None: only device tokens are accepted
    app.state.session_factory = make_session_factory(engine)
    app.state.cache = Cache(redis, profile_ttl=settings.profile_cache_seconds)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=settings.cors_origin_regex or None,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,  # bearer tokens, not cookies
        max_age=86400,  # let browsers cache the preflight instead of repeating it before every POST
    )
    app.include_router(router)
    return app

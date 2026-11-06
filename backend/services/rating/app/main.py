from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from .cache import Cache
from .config import Settings
from .db import make_engine, make_session_factory
from .routes import router


def create_app(
    settings: Settings | None = None,
    *,
    engine: AsyncEngine | None = None,
    redis: Redis | None = None,
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
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await redis.aclose()
        await engine.dispose()

    app = FastAPI(title="Magnitude rating service", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = make_session_factory(engine)
    app.state.cache = Cache(redis, profile_ttl=settings.profile_cache_seconds)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,  # bearer tokens, not cookies
        max_age=86400,  # let browsers cache the preflight instead of repeating it before every POST
    )
    app.include_router(router)
    return app

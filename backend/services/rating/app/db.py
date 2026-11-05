from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .dburl import prepare_database_url


def make_engine(database_url: str) -> AsyncEngine:
    url, connect_args = prepare_database_url(database_url)
    kwargs: dict = {"connect_args": connect_args}
    if url.startswith("postgresql"):
        # Neon scales to zero and PgBouncer drops idle connections: check before use, recycle often,
        # and keep the pool small (the pooler multiplexes for us).
        kwargs.update(pool_size=5, max_overflow=5, pool_pre_ping=True, pool_recycle=300)
    return create_async_engine(url, **kwargs)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)

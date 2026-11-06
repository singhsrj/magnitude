from datetime import datetime, timezone

import fakeredis
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.main import create_app
from app.models import Base
from tests import helpers


def make_settings(**overrides) -> Settings:
    base = dict(database_url="sqlite+aiosqlite://", redis_url="redis://unused", rate_limit_per_minute=1000)
    base.update(overrides)
    return Settings(**base)


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@pytest_asyncio.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.flushall()
    await r.aclose()


@pytest_asyncio.fixture
async def engine():
    e = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with e.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield e
    await e.dispose()


@pytest_asyncio.fixture
async def make_client(engine, redis):
    """Factory so a test can build an app with its own settings."""
    clients = []

    async def build(clerk=None, **overrides) -> AsyncClient:
        app = create_app(make_settings(**overrides), engine=engine, redis=redis, clerk=clerk)
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(c)
        return c

    yield build
    for c in clients:
        await c.aclose()


@pytest_asyncio.fixture
async def client(make_client):
    return await make_client()


@pytest_asyncio.fixture(autouse=True)
async def _expose_engine(engine):
    helpers.ENGINE["engine"] = engine
    yield
    helpers.ENGINE.clear()

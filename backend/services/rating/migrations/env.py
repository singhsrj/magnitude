"""Alembic environment. Runs migrations over asyncpg.

Uses DIRECT_DATABASE_URL (Neon's unpooled host) when set. PgBouncer in transaction mode,
which is what the -pooler host is, is a poor fit for schema changes.
"""
from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.dburl import prepare_database_url
from app.models import Base

settings = Settings()
url, connect_args = prepare_database_url(settings.direct_database_url or settings.database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(url, poolclass=pool.NullPool, connect_args=connect_args)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())

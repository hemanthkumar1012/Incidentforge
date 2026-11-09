"""Database engine helpers (async for services, sync for CLIs/migrations)."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


def make_async_engine(url: str, *, pool_size: int = 5, max_overflow: int = 5) -> AsyncEngine:
    return create_async_engine(
        url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=5,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


def make_sync_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})

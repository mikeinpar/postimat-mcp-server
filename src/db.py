"""Database access: a lazily-created asyncpg connection pool plus a tiny helper.

Kept deliberately thin: the pool is created on first use and reused thereafter.
Everything above this layer works with plain lists of dicts, never with the
driver directly.
"""
from __future__ import annotations

import asyncio
from typing import Any

import asyncpg

from .config import settings

_pool: asyncpg.Pool | None = None
_lock = asyncio.Lock()


async def get_pool() -> asyncpg.Pool:
    """Return the shared pool, creating it once (double-checked under a lock)."""
    global _pool
    if _pool is None:
        async with _lock:
            if _pool is None:
                _pool = await asyncpg.create_pool(
                    dsn=settings.database_url, min_size=1, max_size=5
                )
    return _pool


async def fetch(query: str, *args: Any) -> list[dict]:
    """Run a parameterized SELECT and return rows as a list of dicts.

    Args are always passed separately from the SQL string ($1, $2, …) so values
    can never be interpolated into the query, so there is no SQL injection surface.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *args)
        return [dict(row) for row in rows]

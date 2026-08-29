"""Shared test fixtures.

The DB-backed tests run against a Postgres loaded with schema.sql + seed.sql,
the same pair docker-compose uses, so `docker compose up` then `pytest` works
with no extra setup. DATABASE_URL points at it (defaults to the compose values).

If no Postgres is reachable, those tests are skipped rather than failed: the
pure-logic and auth tests still run anywhere.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault(
    "DATABASE_URL", "postgresql://postimat:postimat@localhost:5432/content_saas"
)

from src import db  # noqa: E402  (import after DATABASE_URL is set)


@pytest.fixture(scope="session")
async def pool():
    """A live pool, or skip the whole DB-backed suite if Postgres is not up."""
    try:
        pool = await db.get_pool()
        await pool.fetchval("SELECT 1")
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres not reachable at DATABASE_URL: {exc}")
    yield pool
    await pool.close()

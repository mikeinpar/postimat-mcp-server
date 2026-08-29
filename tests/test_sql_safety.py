"""Values reach Postgres as bound parameters, never as SQL text.

Two layers are checked: `db.fetch` itself, and a tool called with hostile input.
After each attempt the tables are still there — the point of the exercise.
"""
import pytest

from src import db, queries

pytestmark = pytest.mark.usefixtures("pool")

HOSTILE = "O'Brien'; DROP TABLE channels; --"


async def _tables_intact() -> bool:
    rows = await db.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    names = {r["tablename"] for r in rows}
    return {"channels", "sources", "posts_queue"} <= names


async def test_quoted_string_is_data_not_sql():
    rows = await db.fetch("SELECT $1::text AS value", HOSTILE)
    assert rows[0]["value"] == HOSTILE, "the string must come back byte for byte"
    assert await _tables_intact()


async def test_hostile_period_does_not_break_a_tool():
    result = await queries.get_publications(1, HOSTILE)
    assert result["period"] == "7 days", "unparseable period falls back to the default"
    assert isinstance(result["count"], int)
    assert await _tables_intact()


async def test_non_integer_channel_id_is_rejected_by_the_driver():
    """channel_id is typed as int all the way down; a string that looks like SQL
    fails as a type error at the driver instead of being interpolated."""
    with pytest.raises(Exception):
        await db.fetch("SELECT id FROM channels WHERE id = $1", "1 OR 1=1")
    assert await _tables_intact()

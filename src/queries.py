"""Business logic: all SQL and all input parsing live here.

This module knows nothing about MCP. It takes plain Python arguments and returns
plain Python data. server.py wraps these functions as tools; you could just as
easily call them from a REST handler or a CLI. That separation is the whole point
of the "thin protocol layer" design.

This server is an ADMIN / operator tool for the service owner. It reads across
ALL channels of every client. There is no per-user scoping (that would be a
separate per-customer product with per-user identity). Access is gated by a
single admin token in the transport layer (see auth.py).

All queries target the PUBLICATION contour of content_saas: channels, sources,
posts_queue. Reads only; every value is passed as a bound parameter, never
interpolated into SQL. Time windows look backward over the log (`now() - interval`).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from . import db

# ── Input parsing ────────────────────────────────────────────────────────────

# Named windows the model is likely to produce, mapped to a Postgres interval.
_NAMED_PERIODS = {
    "today": "1 day",
    "day": "1 day",
    "24h": "24 hours",
    "week": "7 days",
    "this_week": "7 days",
    "7d": "7 days",
    "month": "30 days",
    "this_month": "30 days",
    "30d": "30 days",
}

# Loose form like "14d" or "48h".
_RELATIVE_RE = re.compile(r"^(\d{1,3})\s*(d|h)$")

_DEFAULT_INTERVAL = "7 days"


def resolve_interval(period: str | None) -> str:
    """Turn a fuzzy period string into a safe Postgres interval literal.

    Anything unrecognized falls back to the default window rather than erroring:
    an agent should get *some* useful answer, not a stack trace.
    """
    if not period:
        return _DEFAULT_INTERVAL
    key = period.strip().lower()
    if key in _NAMED_PERIODS:
        return _NAMED_PERIODS[key]
    m = _RELATIVE_RE.match(key)
    if m:
        amount, unit = m.groups()
        return f"{amount} {'days' if unit == 'd' else 'hours'}"
    return _DEFAULT_INTERVAL


def _jsonable(rows: list[dict]) -> list[dict]:
    """Make asyncpg rows JSON-safe: datetimes -> ISO 8601 strings."""
    out = []
    for row in rows:
        out.append(
            {
                k: (v.isoformat() if isinstance(v, (datetime, date)) else v)
                for k, v in row.items()
            }
        )
    return out


# ── Tool implementations ─────────────────────────────────────────────────────
# Channels are addressed by numeric `channel_id`. The agent gets ids from
# list_channels() and passes them to the other tools. Nobody types a channel
# name. `title` is a display field only.


async def list_channels() -> dict[str, Any]:
    """Every channel in the service, so the admin can pick one to drill into."""
    rows = await db.fetch(
        """
        SELECT
            c.id, c.title, c.user_id,
            CASE WHEN c.tg_chat_id IS NOT NULL THEN 'TG' ELSE 'MAX' END AS platform,
            c.status, c.is_active,
            (c.status = 'approved' AND c.is_active) AS publishes
        FROM channels c
        ORDER BY c.id
        """
    )
    return {"count": len(rows), "channels": _jsonable(rows)}


async def get_channel_config(channel_id: int) -> dict[str, Any]:
    """A channel's publishing config: schedule, platform, gates, prompts, sources.

    This is where the real scheduling model lives: `posting_hours` ('HH:MM' times
    of day) plus `timezone`, and whether the channel actually publishes right now
    (`status='approved' AND is_active`).
    """
    rows = await db.fetch(
        """
        SELECT
            c.id, c.title, c.user_id, c.status, c.is_active,
            (c.status = 'approved' AND c.is_active) AS publishes,
            CASE WHEN c.tg_chat_id IS NOT NULL THEN 'TG' ELSE 'MAX' END AS platform,
            c.posting_hours, c.timezone, c.last_publish_date_hour,
            c.filter_prompt, c.generation_prompt, c.allowed_domains
        FROM channels c
        WHERE c.id = $1
        """,
        channel_id,
    )
    if not rows:
        return {"channel_id": channel_id, "found": False}

    config = _jsonable(rows)[0]
    sources = await db.fetch(
        "SELECT source_url, last_processed_id FROM sources WHERE channel_id = $1 ORDER BY id",
        channel_id,
    )
    config["sources"] = _jsonable(sources)
    config["found"] = True
    return config


async def get_channel_summary(channel_id: int, period: str = "7d") -> dict[str, Any]:
    """Operational summary for a channel over `period`, mirroring the Digest job:
    counts of SUCCESS / FAILED* / SKIPPED* plus a success rate. There is no audience
    reach here, because the service doesn't collect it.
    """
    interval = resolve_interval(period)

    meta = await db.fetch(
        """
        SELECT id, title, status, is_active,
               (status = 'approved' AND is_active) AS publishes
        FROM channels WHERE id = $1
        """,
        channel_id,
    )
    if not meta:
        return {"channel_id": channel_id, "found": False}

    summary = await db.fetch(
        """
        SELECT
            count(*)                                          AS attempts,
            count(*) FILTER (WHERE q.status = 'SUCCESS')      AS success,
            count(*) FILTER (WHERE q.status LIKE 'FAILED%')   AS failed,
            count(*) FILTER (WHERE q.status LIKE 'SKIPPED%')  AS skipped,
            round(
                100.0 * count(*) FILTER (WHERE q.status = 'SUCCESS')
                / nullif(count(*), 0), 1
            )                                                 AS success_rate_pct,
            max(q.created_at) FILTER (WHERE q.status = 'SUCCESS') AS last_success_at
        FROM posts_queue q
        WHERE q.channel_id = $1
          AND q.created_at >= now() - $2::interval
        """,
        channel_id,
        interval,
    )
    row = _jsonable(summary)[0]
    row.update(_jsonable(meta)[0])
    row.update(period=interval, found=True)
    return row


async def get_publications(channel_id: int, period: str = "7d") -> dict[str, Any]:
    """Log of publish attempts for a channel over the last `period` (any status)."""
    interval = resolve_interval(period)
    rows = await db.fetch(
        """
        SELECT q.id, q.status, q.source_url, q.published_post_id,
               q.payload->>'final_text' AS text,
               q.payload->>'title'      AS title,
               CASE
                   WHEN nullif(q.payload->>'video_url', '') IS NOT NULL THEN 'video'
                   WHEN nullif(q.payload->>'image_url', '') IS NOT NULL THEN 'photo'
                   ELSE NULL
               END AS media,
               q.created_at
        FROM posts_queue q
        WHERE q.channel_id = $1
          AND q.created_at >= now() - $2::interval
        ORDER BY q.created_at DESC
        """,
        channel_id,
        interval,
    )
    return {
        "channel_id": channel_id,
        "period": interval,
        "count": len(rows),
        "publications": _jsonable(rows),
    }


async def get_errors(channel_id: int, period: str = "7d") -> dict[str, Any]:
    """Publications that failed for the channel over `period`, with the reason.

    Failures are posts_queue rows whose status starts with FAILED. The human
    reason lives in payload->>'error'; the status itself says *where* it failed
    (FAILED_PARSER = source parsing, FAILED_SEND = delivery, FAILED = no route).
    """
    interval = resolve_interval(period)
    rows = await db.fetch(
        """
        SELECT q.id, q.status, q.source_url,
               q.payload->>'error'      AS reason,
               q.payload->>'final_text' AS text,
               q.created_at
        FROM posts_queue q
        WHERE q.channel_id = $1
          AND q.status LIKE 'FAILED%'
          AND q.created_at >= now() - $2::interval
        ORDER BY q.created_at DESC
        """,
        channel_id,
        interval,
    )
    return {
        "channel_id": channel_id,
        "period": interval,
        "count": len(rows),
        "errors": _jsonable(rows),
    }

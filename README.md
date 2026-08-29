# postimat-mcp-server

[![tests](https://github.com/mikeinpar/postimat-mcp-server/actions/workflows/tests.yml/badge.svg)](https://github.com/mikeinpar/postimat-mcp-server/actions/workflows/tests.yml)

An MCP (Model Context Protocol) server that exposes a small, read-only set of
tools over the PostgreSQL database (`content_saas`) of a neuro auto-posting
service: a system that parses source channels, generates posts with an LLM, and
publishes them to Telegram and MAX channels on a per-channel schedule.

It is an admin tool for the service owner. It reads across all channels, so the
operator can inspect the pipeline from an agent (Claude Desktop, Claude Code, or
any MCP client) in plain language:

> *"List my channels."*
> *"What got published to channel 2 in the last 24 hours?"*
> *"How is channel 1 configured, when does it post and from what sources?"*
> *"What failed to publish for channel 2 this week and why?"*

…without writing SQL. The agent lists channels first, the operator picks one, and
the other tools take that channel's `channel_id`. Nobody types a channel name.
The agent picks a tool, the server runs a parameterized query, and the data comes
back structured.

> The service itself (the n8n workflows that parse, generate, and publish) lives in a separate repo:
> [mikeinpar/postimat-n8n](https://github.com/mikeinpar/postimat-n8n). This server reads the database those workflows write to.

> **Scope, honestly.** This is an admin tool for one caller, the service owner,
> not a per-customer feature, so a single admin token is the right gate and there
> is no per-user scoping. It models the publication contour of the real service
> (tables `channels`, `sources`, `posts_queue`); the messenger-bot and onboarding
> side (users, sessions, FSM logs) is out of scope. The service logs its *own
> actions*, so there are no audience analytics here: no views, no reactions, no
> reach. This is a portfolio demo of the MCP integration pattern, not a
> production service. It ships with schema and realistic fake data, so it runs on
> clone.

---

## How the real service schedules posts

There is no queue of future posts. Each channel carries its schedule as
`posting_hours`, a list of `'HH:MM'` times of day it should publish, plus a
`timezone`.

```
Dispatcher (cron, every minute)
  └─ SELECT channels WHERE status='approved' AND is_active=true
  └─ keep those whose current hour matches a slot in posting_hours
       AND whose last_publish_date_hour slot ('YYYY-MM-DD_HH') isn't taken
  └─ for each: Worker-Core → parse sources → AI filter → AI rewrite → publish
       └─ Publisher-TG / Publisher-MAX → write outcome to posts_queue
       └─ mark channels.last_publish_date_hour = current hour  (anti-duplicate)
```

So `posts_queue` is the log of outcomes (`SUCCESS` / `FAILED*` / `SKIPPED*`), and
the tools below read that log plus the channel configuration.

---

## Architecture in one line

Thin protocol layer, business logic separate. `server.py` only *declares* tools
and shapes responses; all SQL and period-parsing lives in
[`src/queries.py`](src/queries.py). Swap the transport or the client and the
business logic doesn't move.

```
MCP client ──HTTP──▶ server.py (tool declarations, bearer auth)
                        │
                        ▼
                     queries.py  (SQL + period logic)   ◀── business logic
                        │
                        ▼
                     db.py (asyncpg pool) ──▶ PostgreSQL (content_saas)
```

---

## Tools

All tools are read-only. Channels are addressed by numeric `channel_id`, which
the agent gets from `list_channels()`; `title` is a display field only. `period`
accepts `today`, `24h`, `7d`, `30d`, or `Nd` / `Nh`, and looks backward over the
log.

| Tool | What it answers | Example prompt |
|------|-----------------|----------------|
| `list_channels()` | Every channel: id, title, platform, status, on/off. Start here | *"List my channels."* |
| `get_channel_config(channel_id)` | Schedule (posting hours, tz), platform, on/off gates, AI prompts, parsed sources | *"How is channel 1 set up and when does it post?"* |
| `get_channel_summary(channel_id, period)` | Success / failed / skipped counts and success rate (Digest-style) | *"How's channel 1 doing this week?"* |
| `get_publications(channel_id, period)` | Log of publish attempts (any status) with text & media | *"Show what channel 2 published in the last 24h."* |
| `get_errors(channel_id, period)` | Failed publications: where they failed and why | *"What failed for channel 2 this week and why?"* |

Each tool has a typed signature and a description, so the client renders a proper
JSON schema and the model knows exactly what to pass.

---

## Run it locally in 3 steps

### Option A. Docker (recommended, zero local Postgres)

```bash
# 1. Copy env template (defaults already work with docker-compose)
cp .env.example .env

# 2. Bring up Postgres (auto-loads schema.sql + seed.sql) and the MCP server
docker compose up --build

# 3. The server is now on http://localhost:8000/mcp
```

The Postgres container runs `schema.sql` then `seed.sql` on first boot, so
there's log data immediately.

### Option B. Local venv and your own Postgres

Requires Python 3.10 or newer (the `mcp` SDK needs it) and a running Postgres.

```bash
# 1. Install deps
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Create the DB and load schema + seed
createdb content_saas
psql content_saas -f schema.sql
psql content_saas -f seed.sql

# 3. Point .env at your DB and run
cp .env.example .env            # edit DATABASE_URL if needed
python -m src.server
```

---

## Connect it to a client

The server speaks streamable HTTP at `/mcp` and expects a bearer token
(`MCP_BEARER_TOKEN` from your `.env`; the example value is `dev-secret-token`).

### Claude Code

```bash
claude mcp add --transport http postimat http://localhost:8000/mcp \
  --header "Authorization: Bearer dev-secret-token"
```

### Claude Desktop

Add to `claude_desktop_config.json` (macOS:
`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "postimat": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer dev-secret-token"
      }
    }
  }
}
```

Restart the client, and the five tools show up. Ask it about a channel.

---

## Schema

Three tables, see [`schema.sql`](schema.sql):

- `channels`, the target channels. Publishing has two gates: `status`
  (`approved` by admin) and `is_active` (on/off by user), and the cron publishes
  only when both hold. The table carries the schedule (`posting_hours`,
  `timezone`), the anti-duplicate slot (`last_publish_date_hour`), the
  per-channel AI prompts, and is on exactly one platform (`tg_chat_id` XOR
  `max_chat_id`).
- `sources`, the source channels the worker parses for each channel
  (`source_url`, `last_processed_id` dedup cursor). Up to 10 per channel.
- `posts_queue`, the outcome log: one row per publish attempt, with `status`
  (`SUCCESS` / `FAILED` / `FAILED_PARSER` / `FAILED_SEND` / `SKIPPED%`) and a
  `payload` (jsonb) holding the built item: `final_text`, `title`, `image_url` /
  `video_url`, and, for parser failures, the `error`. There are no reach columns,
  because the service doesn't have that data.

Seed data ([`seed.sql`](seed.sql)) uses timestamps relative to `now()`, so the
log is always recent and the demo looks alive no matter when you clone it.

---

## Security

- All credentials come from the environment, see [`.env.example`](.env.example).
  No real secrets in the repo, and `.gitignore` keeps `.env` out of git.
- A single admin bearer token guards the HTTP transport. Because this is an
  operator tool with exactly one caller (the service owner, allowed to read all
  channels), a shared admin secret is the correct gate rather than a stand-in for
  user identity. In production, harden it with operator OAuth, an IP allowlist,
  and rotation. See [`src/auth.py`](src/auth.py).
- Read-only by design: every query is a `SELECT` with parameterized arguments and
  no string interpolation, so the tools can't mutate or inject.

---

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
docker compose up -d db            # or point DATABASE_URL at your own Postgres
pytest
```

The suite covers the three things this server actually promises.

Tool contracts ([`tests/test_tools.py`](tests/test_tools.py)): each of the five
tools is called against the seeded database and checked for the keys a client
reads, the two publishing gates, and the arithmetic in the summary. A
`channel_id` that does not exist returns `found: false` rather than raising.

SQL safety ([`tests/test_sql_safety.py`](tests/test_sql_safety.py),
[`tests/test_periods.py`](tests/test_periods.py)): a string carrying a quote and
a `DROP TABLE` comes back as data, an unparseable `period` falls back to the
default window, and the tables are still standing afterwards.

Auth ([`tests/test_auth.py`](tests/test_auth.py)): a missing, malformed or wrong
bearer token gets a 401 and never reaches the app behind the middleware.

The period and auth tests need no database. The DB-backed ones skip themselves,
rather than fail, when `DATABASE_URL` points at nothing.

CI runs the same commands on every push: see
[`.github/workflows/tests.yml`](.github/workflows/tests.yml).

---

## What's next

Things I'd add to take this from demo to production:

- Write tools with human-in-the-loop confirmation, for example `retry_failed` and
  `toggle_channel`, gated behind an MCP elicitation or confirm step.
- A per-customer variant. If clients, not just the admin, should query their own
  channels, that needs per-user identity: OAuth 2.1 tokens whose subject scopes
  every query by `user_id`, with ownership checks on `channel_id`. That is a
  different product from this admin tool.
- Text and semantic search: a `search_publications` tool over the generated text,
  later upgraded to pgvector embeddings.
- Observability: structured logging, query timing, and rate limits per token.

---

## Project layout

```
postimat-mcp-server/
├── README.md
├── requirements.txt
├── .env.example          # config template, copy to .env
├── .gitignore            # keeps .env and venv out of git
├── docker-compose.yml    # Postgres (auto-seeded) + the server
├── Dockerfile
├── schema.sql            # tables: channels, sources, posts_queue
├── seed.sql              # realistic fake data, relative to now()
├── pytest.ini            # test config (asyncio mode, import path)
├── requirements-dev.txt  # test dependencies
├── .github/workflows/
│   └── tests.yml         # CI: Postgres service, schema + seed, pytest
├── tests/
│   ├── conftest.py       # shared pool fixture, skips if no Postgres
│   ├── test_tools.py     # response shape of all five tools
│   ├── test_periods.py   # period parsing and its fallback
│   ├── test_sql_safety.py# parameterization holds under hostile input
│   └── test_auth.py      # bearer token: 401 vs pass-through
└── src/
    ├── __init__.py
    ├── config.py         # loads env into a small settings object
    ├── db.py             # asyncpg connection pool + fetch helper
    ├── queries.py        # BUSINESS LOGIC: SQL + period parsing
    ├── auth.py           # bearer-token ASGI middleware (stub)
    └── server.py         # PROTOCOL LAYER: MCP tool declarations
```

-- postimat-mcp-server — database schema
-- This mirrors the PUBLICATION contour of the real service (DB: content_saas),
-- reconstructed from the workflows' SQL nodes. The bot/onboarding contour
-- (users, bot_sessions, *_log, ...) is intentionally out of scope — this demo is
-- about reading publishing activity, not the messenger UX.
--
-- Scheduling model (important): there is NO table of "future posts". Each channel
-- carries a schedule as `posting_hours` — a list of 'HH:MM' times of day. A
-- dispatcher runs every minute and, for each active+approved channel whose current
-- hour matches a slot in `posting_hours` and whose `last_publish_date_hour` slot
-- isn't taken yet, kicks off a worker. `posts_queue` is the LOG of what that
-- produced.
--
-- Loaded automatically by docker-compose on first boot (see docker-compose.yml).

BEGIN;

-- The channels the service publishes to. Central table, two independent gates:
--   status='approved' (set by admin)  AND  is_active=true (toggled by user)
-- Only when BOTH hold does the cron actually publish.
CREATE TABLE IF NOT EXISTS channels (
    id                     SERIAL PRIMARY KEY,
    user_id                INTEGER NOT NULL,        -- owner (users table is out of scope here)
    -- A channel lives on exactly one platform: Telegram XOR MAX.
    tg_chat_id             BIGINT,
    max_chat_id            BIGINT,
    title                  TEXT    NOT NULL,
    -- Admin moderation gate.
    status                 TEXT    NOT NULL DEFAULT 'moderation'
                           CHECK (status IN ('moderation', 'approved', 'rejected')),
    -- User on/off gate.
    is_active              BOOLEAN NOT NULL DEFAULT false,
    -- THE SCHEDULE: times of day ('HH:MM') when this channel should post.
    posting_hours          TEXT[]  NOT NULL DEFAULT '{}',
    timezone               TEXT    NOT NULL DEFAULT 'Europe/Moscow',
    -- Anti-duplicate slot lock, format 'YYYY-MM-DD_HH'. Set after a publish so the
    -- same hour-slot can't fire twice.
    last_publish_date_hour TEXT,
    -- Per-channel AI prompts.
    filter_prompt          TEXT,
    generation_prompt      TEXT,
    -- Domains the worker is allowed to pull media/links from.
    allowed_domains        TEXT[],
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- A channel is either TG or MAX, never both, never neither.
    CONSTRAINT chk_single_platform CHECK (
        (tg_chat_id IS NOT NULL) <> (max_chat_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_channels_active ON channels (is_active, status);

-- Source channels the worker parses to build content for a channel. Max 10/channel.
CREATE TABLE IF NOT EXISTS sources (
    id                SERIAL PRIMARY KEY,
    channel_id        INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    user_id           INTEGER NOT NULL,
    source_url        TEXT    NOT NULL,          -- e.g. https://t.me/s/some_source
    last_processed_id INTEGER,                   -- dedup cursor: last seen source post id
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sources_channel ON sources (channel_id);

-- The log of every publish attempt AND the queue of failures.
-- `payload` (jsonb) holds the full built item: generated text, media, source, etc.
-- Status prefixes: SUCCESS | FAILED (no route) | FAILED_PARSER | FAILED_SEND | SKIPPED%
CREATE TABLE IF NOT EXISTS posts_queue (
    id                SERIAL PRIMARY KEY,
    channel_id        INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    source_url        TEXT,
    origin_post_id    INTEGER,                   -- id of the source post it was built from
    published_post_id TEXT,                      -- Telegram/MAX message id on success
    status            TEXT    NOT NULL,          -- see prefixes above
    payload           JSONB   NOT NULL DEFAULT '{}',
    scheduled_time    TIMESTAMPTZ,               -- when the publish was attempted
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pq_channel_created ON posts_queue (channel_id, created_at);
CREATE INDEX IF NOT EXISTS idx_pq_status          ON posts_queue (status);

COMMIT;

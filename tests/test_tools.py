"""Every tool returns the shape the MCP client is promised, on seed.sql data.

These are contract tests, not assertions about particular rows: the seed data can
grow, but the keys a client reads must not disappear. Where the seed does pin a
fact worth protecting (channel 3 is switched off, channel 2 has a parser failure)
the test says so.
"""
import pytest

from src import queries

pytestmark = pytest.mark.usefixtures("pool")

ACTIVE_CHANNEL = 1
FAILING_CHANNEL = 2
DISABLED_CHANNEL = 3
MISSING_CHANNEL = 999_999


async def test_list_channels_shape():
    result = await queries.list_channels()
    assert result["count"] == len(result["channels"])
    assert result["count"] > 0

    channel = result["channels"][0]
    assert {"id", "title", "user_id", "platform", "status", "is_active", "publishes"} <= channel.keys()
    assert channel["platform"] in {"TG", "MAX"}
    assert isinstance(channel["publishes"], bool)


async def test_publishes_reflects_both_gates():
    """`publishes` is approved AND active, not either one. The seed's disabled
    channel is approved, so a broken gate would show up here."""
    channels = {c["id"]: c for c in (await queries.list_channels())["channels"]}
    off = channels[DISABLED_CHANNEL]
    assert off["status"] == "approved"
    assert off["is_active"] is False
    assert off["publishes"] is False


async def test_get_channel_config_shape():
    config = await queries.get_channel_config(ACTIVE_CHANNEL)
    assert config["found"] is True
    assert {"posting_hours", "timezone", "filter_prompt", "generation_prompt", "sources"} <= config.keys()
    assert isinstance(config["posting_hours"], list)
    assert config["sources"], "seeded channel should have sources"
    assert {"source_url", "last_processed_id"} <= config["sources"][0].keys()


async def test_get_channel_summary_shape_and_arithmetic():
    summary = await queries.get_channel_summary(ACTIVE_CHANNEL, "30d")
    assert summary["found"] is True
    assert {"attempts", "success", "failed", "skipped", "success_rate_pct"} <= summary.keys()
    assert summary["attempts"] == summary["success"] + summary["failed"] + summary["skipped"]
    assert 0 <= float(summary["success_rate_pct"]) <= 100


async def test_get_publications_shape():
    result = await queries.get_publications(ACTIVE_CHANNEL, "30d")
    assert result["count"] == len(result["publications"])
    assert result["count"] > 0

    row = result["publications"][0]
    assert {"id", "status", "source_url", "text", "title", "media", "created_at"} <= row.keys()
    assert row["media"] in {"photo", "video", None}
    assert isinstance(row["created_at"], str), "timestamps must be JSON-safe ISO strings"


async def test_get_errors_returns_only_failures_with_a_reason():
    result = await queries.get_errors(FAILING_CHANNEL, "30d")
    assert result["count"] > 0
    for row in result["errors"]:
        assert row["status"].startswith("FAILED")
    assert any(row["reason"] for row in result["errors"])


async def test_period_narrows_the_window():
    wide = await queries.get_publications(ACTIVE_CHANNEL, "30d")
    narrow = await queries.get_publications(ACTIVE_CHANNEL, "24h")
    assert narrow["count"] <= wide["count"]
    assert narrow["period"] == "24 hours"


async def test_missing_channel_is_reported_not_raised():
    """An agent passing a channel_id that does not exist should get an answer,
    not an exception surfaced as a tool error."""
    assert (await queries.get_channel_config(MISSING_CHANNEL))["found"] is False
    assert (await queries.get_channel_summary(MISSING_CHANNEL))["found"] is False
    assert (await queries.get_publications(MISSING_CHANNEL))["count"] == 0
    assert (await queries.get_errors(MISSING_CHANNEL))["count"] == 0

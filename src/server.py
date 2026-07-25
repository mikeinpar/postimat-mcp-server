"""MCP protocol layer — declares the tools and runs the HTTP transport.

This file is intentionally *thin*. Each function below is a one-liner that
delegates to src/queries.py; its real job is to declare the tool's name, typed
signature, and description so the MCP client can build a JSON schema and the
model knows what to pass. All actual work — SQL, period parsing — lives in
queries.py. That is the "thin protocol layer, business logic separate" split.

This is an ADMIN tool for the service operator: it reads the publication contour
(channel config & schedule, the publish log, failures) across ALL channels. The
agent lists channels first, then drills into one by `channel_id` — nobody types a
channel name. Access is gated by a single admin bearer token (see auth.py).

Run it:  python -m src.server   (serves streamable HTTP at http://HOST:PORT/mcp)
"""
from __future__ import annotations

from typing import Annotated

import uvicorn
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from . import queries
from .auth import BearerAuthMiddleware
from .config import settings

# stateless_http=True keeps each request self-contained — the simplest mode for
# remote HTTP clients. The tools are served at `/mcp`.
mcp = FastMCP(
    "postimat",
    host=settings.host,
    port=settings.port,
    stateless_http=True,
)


# ── Tool declarations ────────────────────────────────────────────────────────
# @mcp.tool() turns a typed function into an MCP tool. The type hints + the
# Field descriptions become the tool's JSON schema; the docstring becomes the
# tool description the model reads.


@mcp.tool()
async def list_channels() -> dict:
    """List every channel in the service (id, title, platform, status, on/off).

    Start here: the admin picks a channel, then the other tools take its channel_id."""
    return await queries.list_channels()


@mcp.tool()
async def get_channel_config(
    channel_id: Annotated[int, Field(description="Channel id from list_channels")],
) -> dict:
    """Get a channel's publishing setup: posting hours, timezone, platform, on/off
    gates, AI prompts, and the source channels it parses."""
    return await queries.get_channel_config(channel_id)


@mcp.tool()
async def get_channel_summary(
    channel_id: Annotated[int, Field(description="Channel id from list_channels")],
    period: Annotated[str, Field(description="Look-back window: 'today', '7d', '30d', or 'Nd'/'Nh'")] = "7d",
) -> dict:
    """Summarize publishing for a channel: success / failed / skipped counts and rate."""
    return await queries.get_channel_summary(channel_id, period)


@mcp.tool()
async def get_publications(
    channel_id: Annotated[int, Field(description="Channel id from list_channels")],
    period: Annotated[str, Field(description="Look-back window: 'today', '24h', '7d', '30d', or 'Nd'/'Nh'")] = "7d",
) -> dict:
    """List the service's publish attempts for a channel in the period (any status)."""
    return await queries.get_publications(channel_id, period)


@mcp.tool()
async def get_errors(
    channel_id: Annotated[int, Field(description="Channel id from list_channels")],
    period: Annotated[str, Field(description="Look-back window: 'today', '7d', '30d', or 'Nd'/'Nh'")] = "7d",
) -> dict:
    """List publications that failed for a channel, with where they failed and why."""
    return await queries.get_errors(channel_id, period)


# ── Transport ────────────────────────────────────────────────────────────────


def main() -> None:
    # Build the streamable-HTTP ASGI app, then wrap it in the admin bearer-auth stub.
    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuthMiddleware, token=settings.bearer_token)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()

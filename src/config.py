"""Configuration: everything comes from the environment, nothing is hardcoded.

Values are read once at import time into a small frozen `settings` object so the
rest of the code never touches os.environ directly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Load .env if present (a no-op in production where real env vars are injected).
load_dotenv()


@dataclass(frozen=True)
class Settings:
    # Postgres connection string, e.g. postgresql://user:pass@host:5432/postimat
    database_url: str
    # Shared bearer token for the HTTP transport. A stub for real auth (see auth.py).
    bearer_token: str
    # Where the HTTP server binds.
    host: str
    port: int


settings = Settings(
    database_url=os.environ.get(
        "DATABASE_URL", "postgresql://postimat:postimat@localhost:5432/content_saas"
    ),
    bearer_token=os.environ.get("MCP_BEARER_TOKEN", "dev-secret-token"),
    host=os.environ.get("MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("MCP_PORT", "8000")),
)

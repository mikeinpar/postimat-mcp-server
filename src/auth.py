"""Bearer-token auth for the HTTP transport.

This is a pure-ASGI middleware (not BaseHTTPMiddleware) so it doesn't buffer or
break the streamable-HTTP / SSE responses the MCP transport relies on. It checks
a single admin token before letting a request reach the MCP app.

── Why one shared token is the RIGHT model here ──────────────────────────────
This MCP server is an ADMIN / operator tool for the service owner, not a
per-customer feature. There is exactly one caller — the admin — who is allowed to
read across all channels, so a single admin secret is the correct gate, not a
stand-in for user identity. (A per-customer product would instead need per-user
tokens whose identity scopes every query — a different design entirely.)
In production, harden this admin token with OAuth for the operator, an IP
allowlist, and rotation; the check itself stays the same shape.
"""
from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

_UNAUTHORIZED = (
    b'{"error": "unauthorized", "detail": "Missing or invalid bearer token"}'
)


class BearerAuthMiddleware:
    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Only guard HTTP requests; let lifespan/websocket events pass through.
        if scope["type"] != "http" or not self.token:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        provided = headers.get(b"authorization", b"").decode()

        if provided != f"Bearer {self.token}":
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate", b"Bearer"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": _UNAUTHORIZED})
            return

        await self.app(scope, receive, send)

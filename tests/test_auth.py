"""Bearer auth on the HTTP transport.

The middleware is pure ASGI, so it is tested by wrapping a trivial inner app:
no MCP server and no database needed. What matters is that a request without a
valid token never reaches the app behind it.
"""
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from src.auth import BearerAuthMiddleware

TOKEN = "test-token"


def _client(token: str = TOKEN) -> TestClient:
    async def ok(request):
        return PlainTextResponse("reached the app")

    app = Starlette(routes=[Route("/mcp", ok)])
    app.add_middleware(BearerAuthMiddleware, token=token)
    return TestClient(app)


def test_valid_token_reaches_the_app():
    r = _client().get("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert r.text == "reached the app"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": ""},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": TOKEN},              # right value, missing scheme
        {"Authorization": f"bearer {TOKEN}"},  # scheme is case-sensitive here
    ],
    ids=["missing", "empty", "no-value", "wrong", "no-scheme", "lowercase-scheme"],
)
def test_bad_token_is_rejected_with_401(headers):
    r = _client().get("/mcp", headers=headers)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert r.json()["error"] == "unauthorized"
    assert "reached the app" not in r.text


def test_empty_configured_token_disables_the_gate():
    """An unset MCP_BEARER_TOKEN means no gate. That is documented behaviour, so it
    is pinned by a test rather than left to be discovered in production."""
    r = _client(token="").get("/mcp")
    assert r.status_code == 200

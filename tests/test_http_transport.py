"""Tests for the Streamable HTTP transport and its bearer-token gate.

These exercise the real FastMCP app in-process with Starlette's TestClient, so they cover the
whole path a remote client (claude.ai, the Claude mobile app) takes: HTTP request, auth check,
MCP JSON-RPC handling. No network and no ESPN calls are involved.
"""

import pytest
from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient

import espn_fantasy_basketball as entry
from espn_fantasy_basketball_mcp import http_transport
from espn_fantasy_basketball_mcp.http_transport import (
    HEALTH_PATH,
    MIN_TOKEN_LENGTH,
    HttpConfig,
    build_http_app,
    token_matches,
)

TOKEN = "unit-test-token-0123456789abcdefghijklmnopqrstuvwxyz"
assert len(TOKEN) >= MIN_TOKEN_LENGTH

MCP_PATH = "/mcp"
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": "2025-06-18",
}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    },
}
TOOLS_LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


def _auth(token: str = TOKEN) -> dict[str, str]:
    return {**MCP_HEADERS, "Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- config


class TestHttpConfig:
    def test_token_is_required(self):
        with pytest.raises(ValueError, match="MCP_AUTH_TOKEN is required"):
            HttpConfig.from_env({})

    def test_blank_token_is_rejected(self):
        with pytest.raises(ValueError, match="MCP_AUTH_TOKEN is required"):
            HttpConfig.from_env({"MCP_AUTH_TOKEN": "   "})

    def test_short_token_is_rejected(self):
        with pytest.raises(ValueError, match=f"at least {MIN_TOKEN_LENGTH} characters"):
            HttpConfig.from_env({"MCP_AUTH_TOKEN": "too-short"})

    def test_defaults_bind_to_loopback(self):
        cfg = HttpConfig.from_env({"MCP_AUTH_TOKEN": TOKEN})
        assert cfg == HttpConfig(host="127.0.0.1", port=8000, token=TOKEN)

    def test_host_and_port_overrides(self):
        cfg = HttpConfig.from_env({"MCP_AUTH_TOKEN": TOKEN, "MCP_HOST": "0.0.0.0", "PORT": "8080"})
        assert (cfg.host, cfg.port) == ("0.0.0.0", 8080)

    def test_port_takes_precedence_over_mcp_port(self):
        cfg = HttpConfig.from_env({"MCP_AUTH_TOKEN": TOKEN, "PORT": "8080", "MCP_PORT": "9000"})
        assert cfg.port == 8080

    def test_mcp_port_is_a_fallback(self):
        cfg = HttpConfig.from_env({"MCP_AUTH_TOKEN": TOKEN, "MCP_PORT": "9000"})
        assert cfg.port == 9000

    @pytest.mark.parametrize("port", ["abc", "0", "70000", "-1"])
    def test_invalid_port_is_rejected(self, port):
        with pytest.raises(ValueError, match="PORT"):
            HttpConfig.from_env({"MCP_AUTH_TOKEN": TOKEN, "PORT": port})

    def test_reads_process_environment_by_default(self, monkeypatch):
        monkeypatch.setenv("MCP_AUTH_TOKEN", TOKEN)
        monkeypatch.setenv("PORT", "8123")
        monkeypatch.delenv("MCP_HOST", raising=False)
        monkeypatch.delenv("MCP_PORT", raising=False)
        assert HttpConfig.from_env() == HttpConfig(host="127.0.0.1", port=8123, token=TOKEN)


# --------------------------------------------------------------------------- token check


class TestTokenMatches:
    @pytest.mark.parametrize(
        "header",
        [f"Bearer {TOKEN}", f"bearer {TOKEN}", f"BEARER   {TOKEN}  ", f"  Bearer {TOKEN}"],
    )
    def test_accepts_bearer_scheme_case_insensitively(self, header):
        assert token_matches(header, TOKEN)

    @pytest.mark.parametrize(
        "header",
        [
            None,
            "",
            "Bearer",
            "Bearer ",
            TOKEN,  # no scheme
            f"Basic {TOKEN}",
            f"Bearer {TOKEN}x",
            f"Bearer {TOKEN[:-1]}",
            f"Token {TOKEN}",
        ],
    )
    def test_rejects_everything_else(self, header):
        assert not token_matches(header, TOKEN)


# --------------------------------------------------------------------------- the ASGI app


def test_build_http_app_rejects_short_token():
    with pytest.raises(ValueError, match="at least"):
        build_http_app(FastMCP("short-token-test"), "short")


@pytest.fixture(scope="module")
def client():
    """The real server, served over Streamable HTTP in-process.

    Module-scoped because FastMCP's HTTP session manager can only be started once per server
    instance; ``json_response=True`` makes responses plain JSON instead of SSE so tests can
    assert on them directly.
    """
    app = build_http_app(entry.mcp, TOKEN, json_response=True)
    with TestClient(app) as test_client:
        yield test_client


def test_health_check_needs_no_token(client):
    response = client.get(HEALTH_PATH)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_missing_token_is_rejected_with_challenge(client):
    response = client.post(MCP_PATH, json=INITIALIZE, headers=MCP_HEADERS)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Bearer ")
    assert response.json()["error"] == "unauthorized"
    assert TOKEN not in response.text


def test_wrong_token_is_rejected(client):
    response = client.post(MCP_PATH, json=INITIALIZE, headers=_auth(TOKEN[:-1] + "X"))
    assert response.status_code == 401


def test_token_in_query_string_is_not_accepted(client):
    """Tokens in URLs leak into logs; only the Authorization header counts."""
    response = client.post(f"{MCP_PATH}?token={TOKEN}", json=INITIALIZE, headers=MCP_HEADERS)
    assert response.status_code == 401


def test_get_without_token_is_rejected(client):
    assert client.get(MCP_PATH, headers=MCP_HEADERS).status_code == 401


def test_delete_without_token_is_rejected(client):
    assert client.delete(MCP_PATH, headers=MCP_HEADERS).status_code == 401


def test_initialize_with_token(client):
    response = client.post(MCP_PATH, json=INITIALIZE, headers=_auth())
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["serverInfo"]["name"] == "ESPN Fantasy Basketball"
    assert "tools" in result["capabilities"]


def test_tools_list_exposes_the_fantasy_tools(client):
    response = client.post(MCP_PATH, json=TOOLS_LIST, headers=_auth())
    assert response.status_code == 200, response.text
    names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert {
        "get_league_teams",
        "get_my_current_matchup",
        "analyze_matchup",
        "get_free_agents",
        "should_i_bid",
    } <= names


def test_tool_call_with_token_reaches_the_tool(client, monkeypatch):
    """A tools/call travels through auth and FastMCP into the real tool function."""
    calls = []

    async def fake_get_nba_schedule(self, date=None):
        calls.append(date)
        return []  # the tool model_dumps each game; an empty slate is a valid answer

    monkeypatch.setattr(
        entry.ESPNFantasyBasketballClient, "get_nba_schedule", fake_get_nba_schedule
    )
    request = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "get_nba_schedule", "arguments": {"date": "2026-10-26"}},
    }
    response = client.post(MCP_PATH, json=request, headers=_auth())
    assert response.status_code == 200, response.text
    assert response.json()["result"]["isError"] is False, response.text
    assert calls == ["2026-10-26"]


# --------------------------------------------------------------------------- entry point


class TestMain:
    def test_defaults_to_stdio(self, monkeypatch):
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        seen = []
        monkeypatch.setattr(entry.mcp, "run", lambda **kw: seen.append(kw))
        entry.main()
        assert seen == [{"transport": "stdio"}]

    @pytest.mark.parametrize("value", ["streamable-http", "HTTP", " http "])
    def test_http_transport_uses_env_config(self, monkeypatch, value):
        monkeypatch.setenv("MCP_TRANSPORT", value)
        monkeypatch.setenv("MCP_AUTH_TOKEN", TOKEN)
        monkeypatch.setenv("PORT", "8081")
        monkeypatch.delenv("MCP_HOST", raising=False)
        seen = []
        monkeypatch.setattr(http_transport, "run_http", lambda mcp, cfg: seen.append((mcp, cfg)))
        entry.main()
        assert seen == [(entry.mcp, HttpConfig(host="127.0.0.1", port=8081, token=TOKEN))]

    def test_http_without_token_exits_with_clear_error(self, monkeypatch):
        monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
        monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
        with pytest.raises(SystemExit, match="MCP_AUTH_TOKEN"):
            entry.main()

    def test_unknown_transport_exits(self, monkeypatch):
        monkeypatch.setenv("MCP_TRANSPORT", "carrier-pigeon")
        with pytest.raises(SystemExit, match="Unknown MCP_TRANSPORT"):
            entry.main()

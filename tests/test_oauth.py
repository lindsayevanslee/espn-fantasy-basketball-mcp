"""Tests for the single-user OAuth 2.1 sign-in used when hosting for claude.ai.

The end-to-end tests drive the exact sequence Claude performs when a custom connector is
added: an unauthenticated call to /mcp, metadata discovery, Dynamic Client Registration,
the authorization redirect, the owner's passphrase login, the PKCE code exchange, and finally
an authenticated MCP request. Everything runs in-process; no network.
"""

import base64
import hashlib
import secrets
import time
from urllib.parse import parse_qs, urlparse

import pytest
from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient

from espn_fantasy_basketball_mcp import oauth
from espn_fantasy_basketball_mcp.http_transport import HttpConfig, build_http_app
from espn_fantasy_basketball_mcp.oauth import (
    LOGIN_PATH,
    Signer,
    SingleUserOAuthProvider,
    redirect_uri_allowed,
)

TOKEN = "oauth-test-passphrase-0123456789abcdefghijklmnopqrstuvwxyz"
PUBLIC_URL = "https://espn-mcp.example.test"
CLAUDE_CALLBACK = "https://claude.ai/api/mcp/auth_callback"
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": "2025-06-18",
}
TOOLS_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


# --------------------------------------------------------------------------- units


class TestRedirectUriAllowlist:
    @pytest.mark.parametrize(
        "uri",
        [
            CLAUDE_CALLBACK,
            "https://claude.com/api/mcp/auth_callback",
            "http://localhost/callback",
            "http://localhost:3118/callback",
            "http://127.0.0.1:52000/callback",
        ],
    )
    def test_allowed(self, uri):
        assert redirect_uri_allowed(uri)

    @pytest.mark.parametrize(
        "uri",
        [
            "https://evil.example/api/mcp/auth_callback",
            "https://claude.ai.evil.example/api/mcp/auth_callback",
            "https://claude.ai/api/mcp/auth_callback?x=1",
            "http://localhost/other",
            "https://localhost/callback",
            "http://localhost/callback?next=x",
            "http://localhost/callback#frag",
            "http://[::1]/callback",
        ],
    )
    def test_rejected(self, uri):
        assert not redirect_uri_allowed(uri)


class TestSigner:
    def test_round_trip(self):
        signer = Signer(TOKEN)
        token = signer.sign("access", {"client_id": "c", "scopes": []}, ttl=60)
        body = signer.unsign("access", token)
        assert body is not None
        assert body["client_id"] == "c"
        assert body["kind"] == "access"
        assert body["exp"] > time.time()

    def test_tokens_are_unique_per_issue(self):
        signer = Signer(TOKEN)
        assert signer.sign("a", {}, 60) != signer.sign("a", {}, 60)

    def test_wrong_kind_rejected(self):
        signer = Signer(TOKEN)
        token = signer.sign("refresh", {"client_id": "c"}, ttl=60)
        assert signer.unsign("access", token) is None

    def test_expired_rejected(self):
        signer = Signer(TOKEN)
        token = signer.sign("code", {}, ttl=60)
        assert signer.unsign("code", token, now=time.time() + 61) is None
        assert signer.unsign("code", token, now=time.time() + 30) is not None

    def test_no_ttl_never_expires(self):
        signer = Signer(TOKEN)
        token = signer.sign("client", {}, ttl=None)
        assert signer.unsign("client", token, now=time.time() + 10**9) is not None

    def test_other_secret_rejected(self):
        token = Signer(TOKEN).sign("access", {}, 60)
        assert Signer(TOKEN + "x").unsign("access", token) is None

    @pytest.mark.parametrize("bad", ["", "nodot", "a.b", "a.b.c", ".sig", "data."])
    def test_garbage_rejected(self, bad):
        assert Signer(TOKEN).unsign("access", bad) is None

    def test_tampered_payload_rejected(self):
        signer = Signer(TOKEN)
        token = signer.sign("access", {"client_id": "c"}, 60)
        data, sig = token.split(".")
        tampered = data[:-2] + ("AA" if data[-2:] != "AA" else "BB")
        assert signer.unsign("access", f"{tampered}.{sig}") is None

    def test_derive_is_deterministic_and_secret_bound(self):
        assert Signer(TOKEN).derive("s", "id") == Signer(TOKEN).derive("s", "id")
        assert Signer(TOKEN).derive("s", "id") != Signer(TOKEN).derive("s", "other")
        assert Signer(TOKEN).derive("s", "id") != Signer(TOKEN + "x").derive("s", "id")


class TestConfig:
    def test_oauth_mode_requires_public_url(self):
        with pytest.raises(ValueError, match="MCP_PUBLIC_URL is required"):
            HttpConfig.from_env({"MCP_AUTH_TOKEN": TOKEN, "MCP_AUTH_MODE": "oauth"})

    def test_oauth_mode_parses(self):
        cfg = HttpConfig.from_env(
            {"MCP_AUTH_TOKEN": TOKEN, "MCP_AUTH_MODE": "OAuth", "MCP_PUBLIC_URL": PUBLIC_URL + "/"}
        )
        assert (cfg.auth_mode, cfg.public_url) == ("oauth", PUBLIC_URL)

    def test_bearer_is_default_and_ignores_public_url(self):
        cfg = HttpConfig.from_env({"MCP_AUTH_TOKEN": TOKEN, "MCP_PUBLIC_URL": PUBLIC_URL})
        assert (cfg.auth_mode, cfg.public_url) == ("bearer", None)

    def test_unknown_mode_rejected(self):
        with pytest.raises(ValueError, match="MCP_AUTH_MODE"):
            HttpConfig.from_env({"MCP_AUTH_TOKEN": TOKEN, "MCP_AUTH_MODE": "magic"})

    @pytest.mark.parametrize(
        "url",
        ["http://espn-mcp.example.test", PUBLIC_URL + "/mcp", PUBLIC_URL + "?x=1", "https://"],
    )
    def test_bad_public_url_rejected(self, url):
        with pytest.raises(ValueError, match="MCP_PUBLIC_URL"):
            HttpConfig.from_env(
                {"MCP_AUTH_TOKEN": TOKEN, "MCP_AUTH_MODE": "oauth", "MCP_PUBLIC_URL": url}
            )

    def test_loopback_http_allowed_for_local_testing(self):
        cfg = HttpConfig.from_env(
            {
                "MCP_AUTH_TOKEN": TOKEN,
                "MCP_AUTH_MODE": "oauth",
                "MCP_PUBLIC_URL": "http://localhost:8000",
            }
        )
        assert cfg.public_url == "http://localhost:8000"


def test_build_requires_public_url_in_oauth_mode():
    with pytest.raises(ValueError, match="public_url"):
        build_http_app(FastMCP("no-url"), TOKEN, auth_mode="oauth")


def test_sdk_still_exposes_the_attributes_we_set():
    """configure_oauth sets two private FastMCP attributes; fail loudly if an SDK upgrade moves them."""
    server = FastMCP("attr-check")
    assert hasattr(server, "_auth_server_provider") and hasattr(server, "_token_verifier")
    provider = oauth.configure_oauth(server, secret=TOKEN, public_url=PUBLIC_URL)
    assert server._auth_server_provider is provider
    assert server.settings.auth is not None
    assert str(server.settings.auth.resource_server_url) == PUBLIC_URL + "/mcp"


# --------------------------------------------------------------------------- end to end


@pytest.fixture(scope="module")
def client():
    server = FastMCP("oauth-e2e")

    @server.tool()
    def ping() -> str:
        """Reply with pong."""
        return "pong"

    app = build_http_app(
        server, TOKEN, json_response=True, auth_mode="oauth", public_url=PUBLIC_URL
    )
    with TestClient(app, base_url=PUBLIC_URL) as test_client:
        yield test_client


def _register(client, redirect_uri=CLAUDE_CALLBACK, auth_method="none"):
    return client.post(
        "/register",
        json={
            "client_name": "Claude",
            "redirect_uris": [redirect_uri],
            "token_endpoint_auth_method": auth_method,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )


def _authorize_and_login(
    client, client_id, challenge, passphrase=TOKEN, redirect_uri=CLAUDE_CALLBACK
):
    """Run /authorize -> /login (GET) -> /login (POST). Returns the final response."""
    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "abc123",
            "resource": PUBLIC_URL + "/mcp",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert location.startswith(PUBLIC_URL + LOGIN_PATH + "?req=")
    req = parse_qs(urlparse(location).query)["req"][0]

    page = client.get(LOGIN_PATH, params={"req": req})
    assert page.status_code == 200
    assert 'type="password"' in page.text
    assert "Claude" in page.text

    return client.post(
        LOGIN_PATH, data={"req": req, "passphrase": passphrase}, follow_redirects=False
    )


def _exchange(client, client_id, code, verifier, redirect_uri=CLAUDE_CALLBACK, **extra):
    return client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            **extra,
        },
    )


def test_unauthenticated_mcp_request_points_at_discovery(client):
    response = client.post("/mcp", json=TOOLS_LIST, headers=MCP_HEADERS)
    assert response.status_code == 401
    www = response.headers["WWW-Authenticate"]
    assert www.startswith("Bearer ")
    # The pointer in the header must resolve: Claude follows it literally.
    pointer = www.split('resource_metadata="', 1)[1].split('"', 1)[0]
    assert pointer.startswith(PUBLIC_URL)
    doc = client.get(pointer.removeprefix(PUBLIC_URL))
    assert doc.status_code == 200, pointer
    assert doc.json()["resource"] == PUBLIC_URL + "/mcp"


@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource/mcp",
        "/mcp/.well-known/oauth-protected-resource",
    ],
)
def test_protected_resource_metadata_is_served_at_every_path_claude_tries(client, path):
    doc = client.get(path)
    assert doc.status_code == 200, path
    assert doc.json()["resource"] == PUBLIC_URL + "/mcp"


def test_protected_resource_metadata(client):
    doc = client.get("/.well-known/oauth-protected-resource").json()
    assert doc["resource"] == PUBLIC_URL + "/mcp"
    assert doc["authorization_servers"][0].rstrip("/") == PUBLIC_URL


def test_authorization_server_metadata(client):
    doc = client.get("/.well-known/oauth-authorization-server").json()
    assert doc["issuer"].rstrip("/") == PUBLIC_URL
    assert doc["authorization_endpoint"] == PUBLIC_URL + "/authorize"
    assert doc["token_endpoint"] == PUBLIC_URL + "/token"
    assert doc["registration_endpoint"] == PUBLIC_URL + "/register"
    assert doc["code_challenge_methods_supported"] == ["S256"]
    assert "authorization_code" in doc["grant_types_supported"]


def test_health_stays_open(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_registration_rejects_foreign_redirect_uri(client):
    response = _register(client, redirect_uri="https://evil.example/callback")
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


def test_registration_is_stateless_and_secret_free_for_public_clients(client):
    response = _register(client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body.get("client_secret") is None
    assert body["redirect_uris"] == [CLAUDE_CALLBACK]
    # The id is a signed description of the client, so it survives restarts.
    assert Signer(TOKEN).unsign("client", body["client_id"]) is not None


def test_full_flow_then_mcp_call_then_refresh(client):
    client_id = _register(client).json()["client_id"]
    verifier, challenge = _pkce()

    done = _authorize_and_login(client, client_id, challenge)
    assert done.status_code == 302, done.text
    redirect = urlparse(done.headers["location"])
    assert f"{redirect.scheme}://{redirect.netloc}{redirect.path}" == CLAUDE_CALLBACK
    query = parse_qs(redirect.query)
    assert query["state"] == ["abc123"]
    code = query["code"][0]

    tokens = _exchange(client, client_id, code, verifier)
    assert tokens.status_code == 200, tokens.text
    body = tokens.json()
    assert body["token_type"].lower() == "bearer"
    assert body["expires_in"] == oauth.ACCESS_TOKEN_TTL
    access, refresh = body["access_token"], body["refresh_token"]

    authed = {**MCP_HEADERS, "Authorization": f"Bearer {access}"}
    response = client.post("/mcp", json=TOOLS_LIST, headers=authed)
    assert response.status_code == 200, response.text
    assert [t["name"] for t in response.json()["result"]["tools"]] == ["ping"]

    # An authorization code is single use.
    assert _exchange(client, client_id, code, verifier).status_code == 400

    refreshed = client.post(
        "/token",
        data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": refresh},
    )
    assert refreshed.status_code == 200, refreshed.text
    new_access = refreshed.json()["access_token"]
    assert new_access != access
    authed = {**MCP_HEADERS, "Authorization": f"Bearer {new_access}"}
    assert client.post("/mcp", json=TOOLS_LIST, headers=authed).status_code == 200


def test_wrong_passphrase_is_rejected_without_a_code(client):
    client_id = _register(client).json()["client_id"]
    _, challenge = _pkce()
    response = _authorize_and_login(client, client_id, challenge, passphrase=TOKEN[:-1])
    assert response.status_code == 401
    assert "location" not in response.headers
    assert "not accepted" in response.text
    assert TOKEN not in response.text


def test_wrong_pkce_verifier_is_rejected(client):
    client_id = _register(client).json()["client_id"]
    _, challenge = _pkce()
    other_verifier, _ = _pkce()
    done = _authorize_and_login(client, client_id, challenge)
    code = parse_qs(urlparse(done.headers["location"]).query)["code"][0]
    response = _exchange(client, client_id, code, other_verifier)
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_code_cannot_be_exchanged_by_another_client(client):
    client_a = _register(client).json()["client_id"]
    client_b = _register(client).json()["client_id"]
    verifier, challenge = _pkce()
    done = _authorize_and_login(client, client_a, challenge)
    code = parse_qs(urlparse(done.headers["location"]).query)["code"][0]
    response = _exchange(client, client_b, code, verifier)
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_expired_login_link_is_refused(client):
    assert client.get(LOGIN_PATH, params={"req": "garbage"}).status_code == 400
    response = client.post(LOGIN_PATH, data={"req": "garbage", "passphrase": TOKEN})
    assert response.status_code == 400


def test_authorize_with_unregistered_redirect_is_refused(client):
    client_id = _register(client).json()["client_id"]
    _, challenge = _pkce()
    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://evil.example/cb",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_confidential_client_needs_its_derived_secret(client):
    registered = _register(client, auth_method="client_secret_post").json()
    client_id, secret = registered["client_id"], registered["client_secret"]
    assert secret
    verifier, challenge = _pkce()
    done = _authorize_and_login(client, client_id, challenge)
    code = parse_qs(urlparse(done.headers["location"]).query)["code"][0]

    wrong = _exchange(client, client_id, code, verifier, client_secret="nope")
    assert wrong.status_code in (400, 401), wrong.text
    assert wrong.json()["error"] in ("invalid_client", "unauthorized_client")

    right = _exchange(client, client_id, code, verifier, client_secret=secret)
    assert right.status_code == 200, right.text


@pytest.mark.parametrize(
    "token",
    [
        "garbage",
        Signer(TOKEN).sign("refresh", {"client_id": "c", "scopes": [], "resource": None}, 60),
        Signer(TOKEN + "x").sign("access", {"client_id": "c", "scopes": [], "resource": None}, 60),
        Signer(TOKEN).sign("access", {"client_id": "c", "scopes": [], "resource": None}, -1),
    ],
    ids=["garbage", "refresh-token-as-access", "other-secret", "expired"],
)
def test_bad_access_tokens_are_rejected(client, token):
    response = client.post(
        "/mcp", json=TOOLS_LIST, headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_access_token_in_query_string_is_ignored(client):
    token = Signer(TOKEN).sign("access", {"client_id": "c", "scopes": [], "resource": None}, 60)
    response = client.post(f"/mcp?access_token={token}", json=TOOLS_LIST, headers=MCP_HEADERS)
    assert response.status_code == 401


async def test_provider_round_trips_tokens_without_storage():
    """A fresh provider (as after a restart) still accepts tokens an earlier one issued."""
    first = SingleUserOAuthProvider(TOKEN, PUBLIC_URL)
    second = SingleUserOAuthProvider(TOKEN, PUBLIC_URL)
    tokens = first._issue_tokens("client-x", ["a"], PUBLIC_URL + "/mcp")
    access = await second.load_access_token(tokens.access_token)
    assert access is not None
    assert (access.client_id, access.scopes, access.resource) == (
        "client-x",
        ["a"],
        PUBLIC_URL + "/mcp",
    )
    assert await second.load_access_token(tokens.refresh_token or "") is None

"""Single-user OAuth 2.1 sign-in for the hosted server.

claude.ai adds a remote MCP server as a *custom connector* and, unless the account has the
request-header beta, the only way to hand it a credential is the standard MCP OAuth flow:
Claude gets a ``401`` from ``/mcp``, discovers this authorization server, registers itself as a
client, sends the owner to ``/authorize``, and exchanges the resulting code for tokens.

This module is the smallest authorization server that satisfies that flow for a server with
one owner. The MCP SDK provides the HTTP endpoints (``/authorize``, ``/token``, ``/register``,
the ``/.well-known`` metadata) and all protocol validation (PKCE S256, redirect URI matching,
code expiry, client authentication). What lives here:

* :class:`SingleUserOAuthProvider`, the SDK's provider protocol. The "login" is a page that
  asks for the owner's passphrase, which is ``MCP_AUTH_TOKEN``: the same secret the bearer
  mode uses, compared in constant time.
* **Stateless storage.** Hosting platforms that scale to zero lose memory between requests,
  so nothing here needs a database. Clients, authorization codes, access tokens and refresh
  tokens are all HMAC-signed payloads (key derived from ``MCP_AUTH_TOKEN``) that the server
  verifies rather than looks up. The one exception is a best-effort in-memory set of already
  used authorization codes.
* **A redirect-URI allowlist.** Clients may only register Claude's callback URL and the
  loopback callback Claude Code uses. Combined with PKCE and the passphrase, a leaked
  authorization code or a rogue client registration cannot obtain a token.

Trade-offs of being stateless, acceptable for a single owner but worth knowing: a refresh
token stays valid until it expires (30 days) even after a newer one is issued, and changing
``MCP_AUTH_TOKEN`` invalidates everything at once (which is also how you revoke access).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import logging
import secrets
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qs, urlparse

from mcp.server.auth.handlers.metadata import ProtectedResourceMetadataHandler
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    ProviderTokenVerifier,
    RefreshToken,
    RegistrationError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken, ProtectedResourceMetadata
from pydantic import AnyHttpUrl, AnyUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

logger = logging.getLogger("espn-fantasy-basketball-mcp.oauth")

MCP_PATH = "/mcp"
LOGIN_PATH = "/login"

ACCESS_TOKEN_TTL = 60 * 60
REFRESH_TOKEN_TTL = 30 * 24 * 60 * 60
AUTH_CODE_TTL = 5 * 60
LOGIN_REQUEST_TTL = 10 * 60

# Where Claude may be sent back to with an authorization code. The hosted Claude apps (web,
# desktop, mobile) use one fixed callback; Claude Code uses a loopback redirect on a random
# port, which redirect_uri_allowed() matches port-agnostically.
CLAUDE_CALLBACK_URIS = frozenset(
    {
        "https://claude.ai/api/mcp/auth_callback",
        "https://claude.com/api/mcp/auth_callback",
    }
)
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1"})


def redirect_uri_allowed(uri: str) -> bool:
    """Return True if ``uri`` is Claude's callback or a loopback ``/callback`` on any port."""
    if uri in CLAUDE_CALLBACK_URIS:
        return True
    parsed = urlparse(uri)
    return (
        parsed.scheme == "http"
        and parsed.hostname in LOOPBACK_HOSTS
        and parsed.path == "/callback"
        and not parsed.query
        and not parsed.fragment
    )


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Signer:
    """HMAC-SHA256 signed, optionally expiring, JSON payloads.

    A signed value looks like ``<base64url(json)>.<base64url(hmac)>``. Every payload carries a
    ``kind`` so a token of one kind can never be presented as another, and a random nonce so
    two tokens for the same payload are distinct.
    """

    def __init__(self, secret: str, purpose: str = "espn-fantasy-basketball-mcp/oauth/v1"):
        self._key = hashlib.sha256(f"{purpose}:{secret}".encode()).digest()

    def _mac(self, data: str) -> str:
        return _b64e(hmac.new(self._key, data.encode("ascii"), hashlib.sha256).digest())

    def sign(self, kind: str, payload: Mapping[str, Any], ttl: int | None) -> str:
        body: dict[str, Any] = dict(payload)
        now = int(time.time())
        body.update(kind=kind, iat=now, nonce=secrets.token_urlsafe(12))
        if ttl is not None:
            body["exp"] = now + ttl
        data = _b64e(json.dumps(body, separators=(",", ":"), sort_keys=True).encode())
        return f"{data}.{self._mac(data)}"

    def unsign(self, kind: str, token: str, now: float | None = None) -> dict[str, Any] | None:
        """Return the payload if the signature is valid, the kind matches and it has not expired."""
        data, sep, sig = token.partition(".")
        if not sep or not data or not sig:
            return None
        if not hmac.compare_digest(sig, self._mac(data)):
            return None
        try:
            body = json.loads(_b64d(data))
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(body, dict) or body.get("kind") != kind:
            return None
        exp = body.get("exp")
        if exp is not None and exp <= (time.time() if now is None else now):
            return None
        return body

    def derive(self, label: str, value: str) -> str:
        """A deterministic secret bound to ``value`` (used for client secrets)."""
        return hmac.new(self._key, f"{label}:{value}".encode(), hashlib.sha256).hexdigest()


class SingleUserOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """The SDK provider protocol, backed by signed tokens and a passphrase login page."""

    def __init__(self, secret: str, public_url: str):
        self._secret = secret
        self._signer = Signer(secret)
        self.public_url = public_url.rstrip("/")
        self.resource_url = self.public_url + MCP_PATH
        self._used_codes: dict[str, float] = {}

    # ------------------------------------------------------------------ clients

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        body = self._signer.unsign("client", client_id)
        if body is None:
            return None
        auth_method = body["auth"]
        return OAuthClientInformationFull(
            client_id=client_id,
            client_secret=(
                self._signer.derive("client_secret", client_id) if auth_method != "none" else None
            ),
            redirect_uris=[AnyUrl(uri) for uri in body["redirect_uris"]],
            token_endpoint_auth_method=auth_method,
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            client_name=body.get("name"),
            scope=body.get("scope"),
        )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Accept a Dynamic Client Registration, if every redirect URI is allowed.

        The SDK generates a random client_id, calls this, and then returns ``client_info`` to
        the caller. We replace the id with a signed description of the client so that
        :meth:`get_client` can reconstruct it later without storage, and derive the secret
        from that id for the same reason.
        """
        for uri in client_info.redirect_uris:
            if not redirect_uri_allowed(str(uri)):
                logger.warning("Rejected client registration with redirect_uri %s", uri)
                raise RegistrationError(
                    error="invalid_redirect_uri",
                    error_description="Only Claude's callback URL and loopback callbacks are allowed.",
                )
        client_id = self._signer.sign(
            "client",
            {
                "redirect_uris": [str(uri) for uri in client_info.redirect_uris],
                "auth": client_info.token_endpoint_auth_method,
                "name": client_info.client_name,
                "scope": client_info.scope,
            },
            ttl=None,
        )
        client_info.client_id = client_id
        if client_info.token_endpoint_auth_method != "none":
            client_info.client_secret = self._signer.derive("client_secret", client_id)
            client_info.client_secret_expires_at = None
        logger.info("Registered OAuth client %r", client_info.client_name)

    # ------------------------------------------------------------------ authorize + login

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Send the owner to the login page, carrying the (signed) authorization request."""
        request_token = self._signer.sign(
            "login",
            {
                "client_id": client.client_id,
                "client_name": client.client_name,
                "redirect_uri": str(params.redirect_uri),
                "explicit": params.redirect_uri_provided_explicitly,
                "code_challenge": params.code_challenge,
                "scopes": params.scopes or [],
                "state": params.state,
                "resource": params.resource,
            },
            ttl=LOGIN_REQUEST_TTL,
        )
        return construct_redirect_uri(self.public_url + LOGIN_PATH, req=request_token)

    async def login_page(self, request: Request) -> Response:
        request_token = request.query_params.get("req", "")
        pending = self._signer.unsign("login", request_token)
        if pending is None:
            return _expired_response()
        return HTMLResponse(_render_login(request_token, pending.get("client_name")))

    async def login_submit(self, request: Request) -> Response:
        form = parse_qs((await request.body()).decode("utf-8", errors="replace"))
        request_token = form.get("req", [""])[0]
        passphrase = form.get("passphrase", [""])[0]
        pending = self._signer.unsign("login", request_token)
        if pending is None:
            return _expired_response()
        if not hmac.compare_digest(passphrase.encode("utf-8"), self._secret.encode("utf-8")):
            client = request.client[0] if request.client else "?"
            logger.warning("Rejected login attempt from %s", client)
            return HTMLResponse(
                _render_login(request_token, pending.get("client_name"), error=True),
                status_code=401,
            )
        code = self._signer.sign(
            "code",
            {
                "client_id": pending["client_id"],
                "redirect_uri": pending["redirect_uri"],
                "explicit": pending["explicit"],
                "code_challenge": pending["code_challenge"],
                "scopes": pending["scopes"],
                "resource": pending.get("resource"),
            },
            ttl=AUTH_CODE_TTL,
        )
        logger.info("Owner signed in; issuing authorization code to %r", pending.get("client_name"))
        return RedirectResponse(
            construct_redirect_uri(pending["redirect_uri"], code=code, state=pending.get("state")),
            status_code=302,
        )

    # ------------------------------------------------------------------ codes and tokens

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        body = self._signer.unsign("code", authorization_code)
        if body is None or body["client_id"] != client.client_id:
            return None
        if authorization_code in self._used_codes:
            logger.warning("Rejected reuse of an authorization code")
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=body["scopes"],
            expires_at=body["exp"],
            client_id=body["client_id"],
            code_challenge=body["code_challenge"],
            redirect_uri=AnyUrl(body["redirect_uri"]),
            redirect_uri_provided_explicitly=body["explicit"],
            resource=body.get("resource"),
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        now = time.time()
        self._used_codes = {c: exp for c, exp in self._used_codes.items() if exp > now}
        self._used_codes[authorization_code.code] = authorization_code.expires_at
        return self._issue_tokens(
            client.client_id, authorization_code.scopes, authorization_code.resource
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        body = self._signer.unsign("refresh", refresh_token)
        if body is None or body["client_id"] != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=body["client_id"],
            scopes=body["scopes"],
            expires_at=int(body["exp"]),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        granted = scopes or refresh_token.scopes
        body = self._signer.unsign("refresh", refresh_token.token) or {}
        return self._issue_tokens(client.client_id, granted, body.get("resource"))

    async def load_access_token(self, token: str) -> AccessToken | None:
        body = self._signer.unsign("access", token)
        if body is None:
            return None
        return AccessToken(
            token=token,
            client_id=body["client_id"],
            scopes=body["scopes"],
            expires_at=int(body["exp"]),
            resource=body.get("resource"),
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        # Tokens are self-contained, so there is nothing to delete. Rotating MCP_AUTH_TOKEN
        # revokes every token at once.
        logger.info("Revocation requested; tokens expire on their own (stateless)")

    def _issue_tokens(self, client_id: str, scopes: list[str], resource: str | None) -> OAuthToken:
        payload = {"client_id": client_id, "scopes": scopes, "resource": resource}
        return OAuthToken(
            access_token=self._signer.sign("access", payload, ACCESS_TOKEN_TTL),
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL,
            scope=" ".join(scopes) or None,
            refresh_token=self._signer.sign("refresh", payload, REFRESH_TOKEN_TTL),
        )


# ---------------------------------------------------------------------- pages


def _expired_response() -> Response:
    return HTMLResponse(
        _page(
            "Sign-in link expired",
            "<p>This sign-in link is invalid or has expired. Go back to Claude and connect "
            "again.</p>",
        ),
        status_code=400,
    )


def _render_login(request_token: str, client_name: str | None, error: bool = False) -> str:
    who = html.escape(client_name or "An MCP client")
    message = (
        '<p class="error">That passphrase was not accepted.</p>'
        if error
        else f"<p><strong>{who}</strong> is asking to use your ESPN Fantasy Basketball tools.</p>"
    )
    body = f"""
{message}
<form method="post" action="{LOGIN_PATH}">
  <input type="hidden" name="req" value="{html.escape(request_token)}">
  <label for="passphrase">Server passphrase (<code>MCP_AUTH_TOKEN</code>)</label>
  <input id="passphrase" name="passphrase" type="password" autocomplete="current-password"
         autofocus required>
  <button type="submit">Allow</button>
</form>
"""
    return _page("Sign in to ESPN Fantasy Basketball MCP", body)


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{html.escape(title)}</title>
<style>
  body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 26rem; margin: 3rem auto; padding: 0 1rem; color: #222; }}
  label {{ display: block; margin: 1rem 0 .25rem; }}
  input[type=password] {{ width: 100%; padding: .6rem; font-size: 1rem; box-sizing: border-box; }}
  button {{ margin-top: 1rem; padding: .6rem 1.2rem; font-size: 1rem; }}
  .error {{ color: #b00020; }}
</style></head>
<body><h1>{html.escape(title)}</h1>{body}</body></html>
"""


# ---------------------------------------------------------------------- wiring


def configure_oauth(mcp: FastMCP, *, secret: str, public_url: str) -> SingleUserOAuthProvider:
    """Turn on OAuth for ``mcp`` so that ``mcp.streamable_http_app()`` mounts the auth routes.

    Must be called before ``streamable_http_app()``. ``public_url`` is the HTTPS origin the
    server is reached at (no path); the MCP endpoint is ``public_url + "/mcp"`` and that exact
    string is what the owner enters in Claude.
    """
    provider = SingleUserOAuthProvider(secret, public_url)
    mcp.settings.auth = AuthSettings(
        issuer_url=AnyHttpUrl(provider.public_url),
        resource_server_url=AnyHttpUrl(provider.resource_url),
        client_registration_options=ClientRegistrationOptions(enabled=True),
        required_scopes=None,
    )
    # FastMCP takes the provider and verifier only in its constructor, but the server object
    # is created at import time (tools are registered on it) before the transport is chosen.
    # These are the two attributes streamable_http_app() reads; tests pin this behaviour.
    mcp._auth_server_provider = provider
    mcp._token_verifier = ProviderTokenVerifier(provider)
    mcp.custom_route(LOGIN_PATH, methods=["GET"], include_in_schema=False)(provider.login_page)
    mcp.custom_route(LOGIN_PATH, methods=["POST"], include_in_schema=False)(provider.login_submit)

    # The SDK serves RFC 9728 metadata only at the site root, but its 401 challenge points at
    # <resource>/.well-known/oauth-protected-resource, and Claude also probes the RFC's
    # path-aware form. Serve the same document at both of those so every pointer resolves.
    metadata = ProtectedResourceMetadataHandler(
        ProtectedResourceMetadata(
            resource=AnyHttpUrl(provider.resource_url),
            authorization_servers=[AnyHttpUrl(provider.public_url)],
        )
    )
    for path in (
        MCP_PATH + "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource" + MCP_PATH,
    ):
        mcp.custom_route(path, methods=["GET"], include_in_schema=False)(metadata.handle)
    return provider

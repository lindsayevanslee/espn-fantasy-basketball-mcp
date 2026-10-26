"""Serve the MCP server over Streamable HTTP, protected by a bearer token.

The default stdio transport only works for a client on the same machine (Claude Desktop,
Claude Code). To use the server from claude.ai or the Claude mobile app it has to be
reachable over HTTPS as a *remote* MCP server. This module wires FastMCP's Streamable HTTP
transport behind a small authentication layer:

* Every request to the MCP endpoint must carry ``Authorization: Bearer <MCP_AUTH_TOKEN>``.
  The comparison is constant-time. Anything else gets ``401`` and never reaches the server,
  so the ESPN cookies configured in the environment are only reachable by whoever holds the
  token.
* ``GET /healthz`` is open so a hosting platform can probe liveness without the token.
* The transport runs stateless, so the server works behind load balancers and on platforms
  that scale to zero and back (each request is self-contained).

Configuration is read from the environment by :meth:`HttpConfig.from_env`:

``MCP_AUTH_TOKEN``  required; at least 32 characters. Generate one with
                    ``python -c "import secrets; print(secrets.token_urlsafe(32))"``.
``MCP_HOST``        bind address; defaults to ``127.0.0.1``. Containers set ``0.0.0.0``.
``PORT``            bind port; defaults to ``8000``. ``MCP_PORT`` is accepted as a fallback.
                    ``PORT`` is the convention Cloud Run, Railway, Render and Fly.io use.

TLS is not handled here. Run behind a platform or reverse proxy that terminates HTTPS; the
bearer token travels in a header and must never be sent over plain HTTP across a network.
"""

from __future__ import annotations

import hmac
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("espn-fantasy-basketball-mcp.http")

HEALTH_PATH = "/healthz"
MIN_TOKEN_LENGTH = 32
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
_REALM = "espn-fantasy-basketball-mcp"


@dataclass(frozen=True)
class HttpConfig:
    """Where to listen and which bearer token to require."""

    host: str
    port: int
    token: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> HttpConfig:
        """Build the config from environment variables (see module docstring).

        Raises:
            ValueError: if the token is missing or too short, or the port is invalid.
        """
        env = os.environ if env is None else env

        token = env.get("MCP_AUTH_TOKEN", "").strip()
        if not token:
            raise ValueError(
                "MCP_AUTH_TOKEN is required when MCP_TRANSPORT=streamable-http. "
                "Refusing to expose the server over HTTP without authentication. Generate a "
                'token with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        if len(token) < MIN_TOKEN_LENGTH:
            raise ValueError(
                f"MCP_AUTH_TOKEN must be at least {MIN_TOKEN_LENGTH} characters "
                f"(got {len(token)}). Use a randomly generated token, not a password."
            )

        host = env.get("MCP_HOST", "").strip() or DEFAULT_HOST

        port_raw = env.get("PORT", "").strip() or env.get("MCP_PORT", "").strip()
        if port_raw:
            try:
                port = int(port_raw)
            except ValueError:
                raise ValueError(f"PORT must be an integer, got {port_raw!r}") from None
            if not 1 <= port <= 65535:
                raise ValueError(f"PORT must be between 1 and 65535, got {port}")
        else:
            port = DEFAULT_PORT

        return cls(host=host, port=port, token=token)


def _extract_bearer_token(authorization: str | None) -> str | None:
    """Return the token from an ``Authorization: Bearer <token>`` header, or None."""
    if not authorization:
        return None
    scheme, _, credentials = authorization.strip().partition(" ")
    if scheme.lower() != "bearer":
        return None
    credentials = credentials.strip()
    return credentials or None


def token_matches(authorization: str | None, expected: str) -> bool:
    """Constant-time check of an Authorization header value against the expected token."""
    provided = _extract_bearer_token(authorization)
    if provided is None:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


class BearerTokenMiddleware:
    """Pure ASGI middleware that rejects HTTP requests without the expected bearer token.

    Written against the raw ASGI interface rather than Starlette's ``BaseHTTPMiddleware`` so
    that the MCP transport's streaming (SSE) responses pass through untouched.
    """

    def __init__(self, app: ASGIApp, token: str, open_paths: frozenset[str] = frozenset()):
        self.app = app
        self._token = token
        self._open_paths = open_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self._open_paths:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if not token_matches(headers.get("authorization"), self._token):
            logger.warning(
                "Rejected unauthenticated %s %s from %s",
                scope.get("method"),
                scope["path"],
                (scope.get("client") or ("?",))[0],
            )
            response = JSONResponse(
                {"error": "unauthorized", "detail": "A valid bearer token is required."},
                status_code=401,
                headers={"WWW-Authenticate": f'Bearer realm="{_REALM}"'},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


async def _health(_: Request) -> Response:
    return JSONResponse({"status": "ok"})


def build_http_app(mcp: FastMCP, token: str, *, json_response: bool = False) -> Starlette:
    """Return the ASGI app: FastMCP's Streamable HTTP endpoint behind bearer-token auth.

    Args:
        mcp: The FastMCP server whose tools to expose.
        token: The bearer token every MCP request must present.
        json_response: Return plain JSON instead of SSE streams for responses. Claude
            accepts either; tests use JSON because it is easier to assert on.
    """
    if len(token) < MIN_TOKEN_LENGTH:
        raise ValueError(f"token must be at least {MIN_TOKEN_LENGTH} characters")

    mcp.settings.stateless_http = True
    mcp.settings.json_response = json_response
    mcp.custom_route(HEALTH_PATH, methods=["GET"], include_in_schema=False)(_health)

    app = mcp.streamable_http_app()
    app.add_middleware(BearerTokenMiddleware, token=token, open_paths=frozenset({HEALTH_PATH}))
    return app


def run_http(mcp: FastMCP, config: HttpConfig) -> None:
    """Serve ``mcp`` over Streamable HTTP until interrupted."""
    import uvicorn

    app = build_http_app(mcp, config.token)
    logger.info(
        "Serving MCP over Streamable HTTP on http://%s:%d%s (bearer token required; "
        "health check at %s)",
        config.host,
        config.port,
        mcp.settings.streamable_http_path,
        HEALTH_PATH,
    )
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")

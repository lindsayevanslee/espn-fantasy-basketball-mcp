# Remote MCP server image: serves the ESPN Fantasy Basketball tools over Streamable HTTP so
# claude.ai and the Claude mobile app can use them as a custom connector.
#
# Build:  docker build -t espn-fantasy-mcp .
# Run:    docker run --rm -p 8080:8080 --env-file .env espn-fantasy-mcp
# Then:   curl -s localhost:8080/healthz        -> {"status":"ok"}
#
# Required env: MCP_AUTH_TOKEN plus the ESPN_* variables from .env.example. Never bake them
# into the image; pass them at run time (or as your host's secrets).

FROM python:3.12-slim AS base

# uv, pinned to the same version CI uses.
RUN pip install --no-cache-dir uv==0.11.32

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first so this layer is cached across code changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY espn_fantasy_basketball.py ./
COPY espn_fantasy_basketball_mcp/ ./espn_fantasy_basketball_mcp/

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

# Serve over HTTP on all interfaces; PORT follows the Cloud Run / Railway / Render convention
# (those platforms inject PORT themselves and this default matches Cloud Run's).
ENV MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD ["/app/.venv/bin/python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['PORT']}/healthz\", timeout=2)"]

CMD ["/app/.venv/bin/python", "espn_fantasy_basketball.py"]

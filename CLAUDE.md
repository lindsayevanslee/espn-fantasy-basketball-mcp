# ESPN Fantasy Basketball MCP server

An MCP server (FastMCP, Python 3.10+) exposing ESPN Fantasy Basketball data as tools. Read
`README.md` for the tool list and configuration.

## Commands

- `uv sync --locked --all-extras --dev` installs everything (cloud sessions do this on start).
- `./scripts/check.sh` runs exactly what CI runs: `ruff check`, `ruff format --check`, `mypy`,
  and `pytest` with the coverage gate. Run it before every push.
- `uv run pytest tests/test_server.py -k name` for a single test.

## Layout

- `espn_fantasy_basketball.py`: the tool definitions and the `main()` transport switch.
- `espn_fantasy_basketball_mcp/client.py`: ESPN API client (requests, cache, fetchers, draft, stats).
- `espn_fantasy_basketball_mcp/analysis.py`, `dates.py`, `search.py`, `constants.py`: matchup
  analysis, period/calendar math, player name matching, and ESPN ID tables.
- `espn_fantasy_basketball_mcp/models.py`: Pydantic models for everything the tools return.
- `espn_fantasy_basketball_mcp/http_transport.py`: Streamable HTTP transport and its auth gate,
  used when the server is hosted for claude.ai / the Claude mobile app (`MCP_AUTH_MODE`).
- `espn_fantasy_basketball_mcp/oauth.py`: the single-user OAuth 2.1 sign-in (stateless, signed
  tokens) that `oauth` mode plugs into the MCP SDK's auth routes.

## Conventions

- Tests mock every ESPN call; nothing in `tests/` may hit the network. ESPN-shaped responses
  live in `tests/fixtures/` (synthetic, no real account data). Live checks go in
  `scripts/verify_live.py`, which is read-only.
- Coverage is a ratchet (`fail_under` in `pyproject.toml`): add tests with new code, never
  lower the number.
- `mypy` runs strict-ish (`disallow_untyped_defs`); annotate everything outside `tests/`.
- Line length is 100 (ruff). Let `uv run ruff format .` fix formatting.
- Add new tools in `espn_fantasy_basketball.py` with a docstring listing every argument; the
  docstring is what Claude sees. Credentials come from `_get_espn_credentials` / `_get_team_id`
  with environment fallbacks.
- Keep the README tool list and the CHANGELOG in step with code changes.
- The Cloud Run blocks in the README are tested as code (`tests/test_readme_deploy.py` runs
  them against stand-in commands). Blocks meant to be re-run must stay self-contained, wrapped
  in `( set -euo pipefail ... )`, and must not restate service settings on redeploy.

## Security

- `ESPN_S2`, `ESPN_SWID`, and `MCP_AUTH_TOKEN` are secrets. Never commit them, print them, log
  them, or put them in test fixtures or example output. `.env` is gitignored for a reason.
- The HTTP transport must never accept a token from the URL, and must refuse to start without
  one. Keep `tests/test_http_transport.py` covering both.
- OAuth: never widen the redirect-URI allowlist in `oauth.py` beyond Claude's callback and
  loopback, never skip PKCE, and keep `tests/test_oauth.py` driving the full flow end to end.
- Hosting cost is a safety property too: the server is deployed on Cloud Run, which bills
  open-request time. Keep the transport stateless, keep `GET /mcp` answering `405`, and do not
  add anything that holds a connection open (server-pushed notifications, long polling).
- Do not add tools that write to ESPN (trades, adds/drops) without an explicit request.

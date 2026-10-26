# ESPN Fantasy Basketball MCP Server

[![Tests](https://github.com/lindsayevanslee/espn-fantasy-basketball-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/lindsayevanslee/espn-fantasy-basketball-mcp/actions/workflows/test.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Type checked: mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](https://mypy-lang.org/)

An MCP (Model Context Protocol) server that provides access to ESPN Fantasy Basketball APIs. This server enables Claude and other MCP clients to fetch fantasy basketball data including league settings, teams, rosters, free agents, matchups, player statistics, NBA schedules, and to analyze your current matchup.

> **Note**: This is an unofficial third-party tool and is not affiliated with or endorsed by ESPN.
>
> This repository is a fork of [dylancharris/espn-fantasy-basketball-mcp](https://github.com/dylancharris/espn-fantasy-basketball-mcp) with additional tools, bug fixes, and hardening.

## Features

### Available Tools

#### League & Roster Tools
1. **get_league_teams** - Get all teams in an ESPN Fantasy Basketball league
2. **get_league_settings** - Scoring categories, roster slots, schedule/matchup periods, waiver and trade rules, current period
3. **get_team_roster** - Get roster for a specific team, with per-player season stats, injury status, and today's game
4. **get_team_season_stats** - Season category totals, record, win percentage, and games back for a team
5. **get_free_agents** - Get free agents/waiver wire players (pass `verbose=true` for stats)
6. **get_nba_schedule** - Get NBA game schedule for a date

#### Matchup Tools
7. **get_matchups** - Matchups for a matchup period, with category scores by human-readable name
8. **get_my_current_matchup** - Your current matchup, both rosters, and category scores in one call
9. **analyze_matchup** - Category-by-category projections, close categories, and start/sit priorities for a matchup
10. **get_roster_schedule** - Games this week and next for every player on your roster

#### Player Analysis Tools
11. **get_player_stats** - Stats for one or many players by ESPN player ID (`season`, `projections`, `last_7`, `last_15`, `last_30`)
12. **compare_players** - Compare players across categories
13. **analyze_trade_proposal** - Value and category impact of a proposed trade
14. **get_trending_players** - Players trending up or down in ownership

#### Live Draft Assistant Tools
15. **get_draft_status** - Get current draft status including all picks and progress
16. **should_i_bid** - Get recommendation on whether to bid for the current player being nominated
17. **who_should_i_target_next** - Get recommendation on which player to target/nominate next
18. **analyze_my_draft_strategy** - Analyze your current draft strategy and spending patterns
19. **get_available_players** - Get top available players for the draft with auction values

Most tools read `ESPN_LEAGUE_ID`, `ESPN_TEAM_ID`, `ESPN_YEAR`, `ESPN_S2`, and `ESPN_SWID` from the environment, so you rarely need to pass them. Tools that act on *your* team require a team ID, either as a parameter or via `ESPN_TEAM_ID`, and return a clear error if neither is set.

## Installation

### Prerequisites
- Python 3.10 or higher
- [uv](https://docs.astral.sh/uv/) package manager

### Setup

1. Clone this repository:
   ```bash
   git clone <repository-url>
   cd espn-fantasy-basketball-mcp
   ```

2. Install dependencies using uv:
   ```bash
   uv sync
   ```

## Usage

### Running the Server

```bash
uv run espn_fantasy_basketball.py
```

### Configuration for Claude Desktop

> **⚠️ SECURITY WARNING**: The ESPN_S2 and ESPN_SWID cookies provide full access to your ESPN Fantasy account. Treat them like passwords:
> - Never share these credentials with anyone
> - Never commit them to version control
> - Ensure your Claude Desktop config file has restricted permissions (`chmod 600`)
> - These cookies can expire - you'll need to refresh them periodically from your browser

Add to your Claude Desktop configuration (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "espn-fantasy-basketball": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/espn-fantasy-basketball-mcp",
        "run",
        "espn_fantasy_basketball.py"
      ],
      "env": {
        "ESPN_LEAGUE_ID": "your_league_id",
        "ESPN_TEAM_ID": "your_team_id",
        "ESPN_S2": "your_espn_s2_cookie",
        "ESPN_SWID": "your_swid_cookie",
        "MY_TIMEZONE": "America/Chicago"
      }
    }
  }
}
```

**After adding credentials, secure your config file:**
```bash
chmod 600 ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

### Environment Variables

The following environment variables can be configured:

- **ESPN_LEAGUE_ID**: Your ESPN Fantasy Basketball league ID (required)
- **ESPN_TEAM_ID**: Your team ID within the league (optional, but required by roster, matchup, schedule, and draft tools unless you pass `team_id` each time)
- **ESPN_YEAR**: Season as ESPN labels it, which is the calendar year the season *ends* in (the 2026-27 season is `2027`). Optional. When unset, the server picks the season in progress from today's date (October through December map to the following year). Set it explicitly during September draft prep for a new season, or to look at a past season.
- **ESPN_S2**: ESPN authentication cookie for private leagues (required for private leagues)
- **ESPN_SWID**: ESPN SWID cookie for private leagues (required for private leagues)
- **MY_TIMEZONE**: Timezone for date/time conversions (optional, defaults to `America/New_York`)

The `MY_TIMEZONE` variable controls how dates and times are converted from UTC in API responses. All ISO datetime strings (such as game times, acquisition dates, and trade deadlines) will be converted to this timezone. Use standard IANA timezone names (e.g., `America/Los_Angeles`, `America/Chicago`, `Europe/London`). If not set, the default is `America/New_York`.

These apply only when serving the tools over HTTP for claude.ai and the Claude mobile app (see
[Using the server from the Claude mobile app](#using-the-server-from-the-claude-mobile-app-remote-mcp)):

- **MCP_TRANSPORT**: `stdio` (default, for Claude Desktop and Claude Code) or `streamable-http`.
- **MCP_AUTH_TOKEN**: Required in HTTP mode. A random secret of at least 32 characters that every request must present as `Authorization: Bearer <token>`. The server refuses to start over HTTP without it.
- **MCP_HOST**: Bind address in HTTP mode. Defaults to `127.0.0.1`; the Docker image sets `0.0.0.0`.
- **PORT**: Bind port in HTTP mode. Defaults to `8000`; the Docker image sets `8080`, and hosting platforms that inject `PORT` are honoured.

## Using the server from the Claude mobile app (remote MCP)

Claude Desktop launches this server on your computer and talks to it over stdio. The Claude
iOS and Android apps (and claude.ai in a browser) cannot launch a local process; they only talk
to **remote MCP servers** over HTTPS, added to your account as a *custom connector*. This repo
supports that with a second transport:

- `MCP_TRANSPORT=streamable-http` serves the same tools at `/mcp` over MCP's Streamable HTTP
  transport (`espn_fantasy_basketball_mcp/http_transport.py`).
- Every request must carry `Authorization: Bearer <MCP_AUTH_TOKEN>`. Anything else gets a `401`
  before it reaches the server. The server refuses to start over HTTP with no token, and tokens
  are never accepted in the URL. `GET /healthz` is open for platform health checks.
- Your ESPN cookies live only in the hosted server's environment. Anyone holding the bearer
  token can read your league, so treat the token like a password.

The Claude app itself is only a client: once you have added the connector on claude.ai in a
browser, it is available in the mobile app automatically. You cannot add connectors from the
phone.

> **Before you start**: request-header authentication for custom connectors is a beta that
> Anthropic has not enabled for every account. Open **Customize > Connectors > Add custom
> connector** on claude.ai and check whether the dialog has a **Request headers** section. If it
> does, everything below works. If it does not, see [If there is no Request headers
> section](#if-there-is-no-request-headers-section) before deploying anything.

### 1. Try it locally

```bash
export MCP_AUTH_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
echo "$MCP_AUTH_TOKEN"   # keep this; you will paste it into claude.ai

MCP_TRANSPORT=streamable-http uv run espn_fantasy_basketball.py
# in another terminal:
curl -s localhost:8000/healthz                                   # {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/mcp  # 401 without the token
```

The same thing in Docker, which is what you will deploy:

```bash
docker build -t espn-fantasy-mcp .
docker run --rm -p 8080:8080 --env-file .env -e MCP_AUTH_TOKEN="$MCP_AUTH_TOKEN" espn-fantasy-mcp
curl -s localhost:8080/healthz
```

(`.env` is the file described in `.env.example`; it never leaves your machine.)

### 2. Host it with HTTPS

The `Dockerfile` runs as an unprivileged user, listens on `$PORT`, and works unchanged on
Google Cloud Run, Fly.io, Railway, and Render. All of them terminate TLS for you, which is
required: the bearer token travels in a header and must only cross the internet over HTTPS.
Cloud Run scales to zero and its free tier covers a personal server comfortably, so it is the
suggested default:

```bash
gcloud services enable run.googleapis.com secretmanager.googleapis.com cloudbuild.googleapis.com

# Secrets never go on the command line of the deploy itself.
printf '%s' "$MCP_AUTH_TOKEN" | gcloud secrets create espn-mcp-token --data-file=-
printf '%s' "$ESPN_S2"        | gcloud secrets create espn-s2        --data-file=-
printf '%s' "$ESPN_SWID"      | gcloud secrets create espn-swid      --data-file=-

gcloud run deploy espn-fantasy-mcp --source . --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "ESPN_LEAGUE_ID=123456,ESPN_TEAM_ID=1,MY_TIMEZONE=America/Chicago" \
  --set-secrets "MCP_AUTH_TOKEN=espn-mcp-token:latest,ESPN_S2=espn-s2:latest,ESPN_SWID=espn-swid:latest"
```

`--allow-unauthenticated` only disables Google's own IAM gate on the URL; the server still
rejects every request without your bearer token. If the deploy reports that the service account
cannot read a secret, grant it the *Secret Manager Secret Accessor* role on those secrets. The
command prints a `https://....run.app` URL; your MCP URL is that plus `/mcp`. Check it:

```bash
curl -s https://YOUR-SERVICE.run.app/healthz
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://YOUR-SERVICE.run.app/mcp   # 401
```

On Fly.io the equivalent is `fly launch --no-deploy`, `fly secrets set MCP_AUTH_TOKEN=... ESPN_S2=... ESPN_SWID=...`,
set the non-secret variables in `fly.toml` under `[env]`, then `fly deploy`.

### 3. Add it to Claude as a custom connector

Do this once, on claude.ai in a browser (Pro or Max plan; on Team or Enterprise an Owner adds it
under **Organization settings > Connectors**):

1. Go to **Customize > Connectors** and click **Add custom connector**.
2. Name it (for example `ESPN Fantasy Basketball`) and enter the **MCP server URL**:
   `https://YOUR-SERVICE.run.app/mcp`.
3. Under **Authentication** choose **No sign-in**. (The server has no OAuth login page; the
   header below is the credential.)
4. Open **Request headers**, pick the `authorization` header, and enter the value
   `Bearer <your MCP_AUTH_TOKEN>`, with the word `Bearer` and a space in front of the token.
   Claude sends the value exactly as typed. Mark it **Required**.
5. Click **Add**.

Authentication settings cannot be edited later: to rotate the token, redeploy with a new
`MCP_AUTH_TOKEN`, remove the connector, and add it again.

Then, on your phone, open the Claude app, start a chat, tap **+**, choose **Connectors**, and
turn the connector on. Ask something like *"Using my ESPN connector, how is my matchup looking
this week?"*; the first call will ask you to allow the tool.

### If there is no Request headers section

Your account is not in the beta yet. Do **not** work around it by deploying with no
authentication or by putting the token in the URL: either one exposes your ESPN account to
anyone who finds the URL. The supported alternatives are:

- Ask [Claude support](https://support.claude.com/en/articles/9015913-how-to-get-support) to
  enable request-header authentication for your account, and keep using Claude Desktop in the
  meantime.
- Add an OAuth 2.1 login to this server. Claude's connector flow supports Dynamic Client
  Registration and PKCE, and the MCP SDK ships the server-side routes, so the remaining work
  is a small authorization server with a single-user login page. That is a planned follow-up
  and is tracked in the changelog; it is not implemented yet.

### Security notes for the hosted server

- The bearer token is the only thing between the internet and your league. Generate it
  randomly (the command above), never commit it, and keep it out of chat logs.
- Claude's requests to your server come from Anthropic's published range
  `160.79.104.0/21`. If your host lets you restrict inbound traffic, allowing only that range
  adds a second layer.
- If you front the server with Cloudflare, turn off **Security > Settings > Block AI bots** for
  the hostname; it has been reported to drop Claude's connector requests.
- `ESPN_S2` expires eventually. When tools start returning authentication errors, refresh the
  cookie in your browser, update the secret, and redeploy.
- The server logs rejected requests with their source IP and never logs token values.
- In HTTP mode outside the container the server binds to `127.0.0.1` on purpose; set
  `MCP_HOST=0.0.0.0` only behind a TLS-terminating proxy or platform.

## Draft Tools Usage

The live draft assistant tools are designed for auction drafts and help answer key questions during your draft:

> **💡 Pro Tip**: These tools work seamlessly with Claude Desktop! Ask Claude questions like "Should I bid on this player?" or "Who should I target next?" and it will use these tools automatically to give you expert draft advice.

### 🔍 **get_draft_status**
Get the current state of your draft including all picks made so far.

```python
# Get draft status
draft_status = await get_draft_status(
    league_id=123456,
    year=2025,
    espn_s2="your_espn_s2_cookie",  # for private leagues
    swid="your_swid_cookie"         # for private leagues
)
```

**Returns:**
- `inProgress`: Whether draft is currently active
- `drafted`: Whether draft is completed
- `picks`: Array of all picks made so far with player details
- `currentPickNumber`: Next pick number
- `currentNominatingTeam`: Which team is nominating next

### 💰 **should_i_bid**
Get AI-powered recommendation on whether to bid for the current player being nominated.

```python
# Should I bid for this player?
recommendation = await should_i_bid(
    current_player_id=12345,        # Player being nominated
    team_id=1,                      # Your team ID (optional, uses ESPN_TEAM_ID env var)
    league_id=123456,               # Optional, uses ESPN_LEAGUE_ID env var
    year=2025,                      # Optional, uses ESPN_YEAR env var
    espn_s2="your_espn_s2_cookie",  # Optional, uses ESPN_S2 env var
    swid="your_swid_cookie"         # Optional, uses ESPN_SWID env var
)
```

**Returns:**
- `action`: "bid" or "pass"
- `playerName`: Name of the player
- `suggestedBid`: Recommended bid amount
- `maxBid`: Maximum you should bid
- `reasoning`: Explanation of the recommendation
- `priority`: Priority score (1-10)

### 🎯 **who_should_i_target_next**
Get recommendation on which player to nominate when it's your turn.

```python
# Who should I target next?
recommendation = await who_should_i_target_next(
    team_id=1,                      # Your team ID (optional, uses ESPN_TEAM_ID env var)
    league_id=123456,               # Optional, uses ESPN_LEAGUE_ID env var
    year=2025,                      # Optional, uses ESPN_YEAR env var
    espn_s2="your_espn_s2_cookie",  # Optional, uses ESPN_S2 env var
    swid="your_swid_cookie"         # Optional, uses ESPN_SWID env var
)
```

**Returns:**
- `action`: "nominate" or "pass"
- `playerId`: Recommended player ID
- `playerName`: Player name
- `suggestedBid`: Recommended opening bid
- `reasoning`: Why this player is recommended
- `priority`: Priority score (1-10)

### 📊 **analyze_my_draft_strategy**
Analyze your current draft progress, spending patterns, and punt strategy.

```python
# Analyze my draft strategy
analysis = await analyze_my_draft_strategy(
    team_id=1,                      # Your team ID (optional, uses ESPN_TEAM_ID env var)
    league_id=123456,               # Optional, uses ESPN_LEAGUE_ID env var
    year=2025,                      # Optional, uses ESPN_YEAR env var
    espn_s2="your_espn_s2_cookie",  # Optional, uses ESPN_S2 env var
    swid="your_swid_cookie"         # Optional, uses ESPN_SWID env var
)
```

**Returns:**
- `team_summary`: Your current roster and spending
  - `totalSpent`: Money spent so far
  - `playersCount`: Number of players drafted
  - `remainingBudget`: Money left to spend
- `punt_analysis`: Strategy analysis and recommendations
- `budget_per_remaining_player`: Average $ per remaining roster spot

### 📋 **get_available_players**
Get list of top available players with auction values and rankings.

```python
# Get best available players
players = await get_available_players(
    league_id=123456,
    year=2025,
    limit=25,                       # Number of players to return
    espn_s2="your_espn_s2_cookie",
    swid="your_swid_cookie"
)
```

**Returns:** Array of available players with:
- `playerId`: Player ID
- `player`: Player details (name, position, team)
- `auctionValue`: Projected auction value
- `rank`: Overall ranking
- `isDrafted`: False (only undrafted players returned)

### 💡 **Draft Assistant Example Workflow**

```python
# 1. Check draft status
status = await get_draft_status(league_id, year, espn_s2, swid)
if not status["inProgress"]:
    print("Draft not in progress")

# 2. If someone nominated a player, should you bid?
if current_player_being_nominated:
    advice = await should_i_bid(league_id, year, team_id, player_id, espn_s2, swid)
    print(f"{advice['action'].upper()}: {advice['reasoning']}")
    if advice["action"] == "bid":
        print(f"Suggested bid: ${advice['suggestedBid']}")

# 3. If it's your turn to nominate
if its_your_turn:
    target = await who_should_i_target_next(league_id, year, team_id, espn_s2, swid)
    print(f"Target: {target['playerName']} (${target['suggestedBid']})")
    print(f"Reasoning: {target['reasoning']}")

# 4. Analyze your strategy periodically
strategy = await analyze_my_draft_strategy(league_id, year, team_id, espn_s2, swid)
print(f"Spent: ${strategy['team_summary']['totalSpent']}")
print(f"Budget per remaining player: ${strategy['budget_per_remaining_player']}")
```

### 🆔 **Finding Your Team ID**

Most draft and roster tools require your `team_id`. To find it:

1. Use the `get_league_teams` tool to see all teams:
```python
teams = await get_league_teams(league_id, year, espn_s2, swid)
# Look through the results to find your team
```

2. Or check the ESPN Fantasy Basketball URL when viewing your team:
   - URL format: `https://fantasy.espn.com/basketball/team?leagueId=123456&teamId=1`
   - Your team ID is the number after `teamId=`

3. **Configure it as an environment variable** to avoid being asked every time:
   - Add `ESPN_TEAM_ID` to your Claude Desktop config (see Configuration section above)
   - Once configured, you can omit `team_id` from tool calls and it will use your configured team automatically

### Private League Access

For private leagues, you'll need ESPN authentication cookies:
- `ESPN_S2`: ESPN authentication cookie (long string starting with "AE")
- `ESPN_SWID`: ESPN SWID cookie (format: `{12345678-1234-1234-1234-123456789012}`)

> **⚠️ SECURITY REMINDER**: These cookies grant full access to your ESPN account. Keep them secure and never share them.

To get these cookies:
1. Log into ESPN Fantasy in your browser
2. Open browser developer tools (F12)
3. Go to Application/Storage tab → Cookies → espn.com
4. Find and copy the `espn_s2` and `SWID` cookie values
5. **Important**: Clear your browser's developer tools history after copying to avoid leaving credentials visible

## Development

### Running Tests

```bash
# Run all tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=espn_fantasy_basketball_mcp

# Run specific test file
uv run pytest tests/test_models.py

# Run tests in verbose mode
uv run pytest -v
```

### Code Quality

```bash
# Lint (and auto-fix what ruff can)
uv run ruff check --fix .

# Format
uv run ruff format .

# Type checking (the package and the server entry point)
uv run mypy espn_fantasy_basketball_mcp/ espn_fantasy_basketball.py

# Run every CI check locally (lint, format check, mypy, tests with coverage)
./scripts/check.sh
```

### Verifying Against Your League

The unit tests mock every ESPN call. To check the server against your real league, run the
read-only verification script:

```bash
uv run python scripts/verify_live.py
```

It reads `ESPN_LEAGUE_ID`, `ESPN_TEAM_ID`, `ESPN_S2`, `ESPN_SWID`, `ESPN_YEAR`, and `MY_TIMEZONE`
from the environment, and anything not set there from the `env` block of this server's entry in
your Claude Desktop config. If Claude Desktop already works, no extra setup is needed. Use
`--config PATH` if your config lives somewhere unusual, or `--server NAME` if you have several
ESPN entries. Alternatively copy `.env.example` to `.env` (gitignored) and load it with
`set -a; source .env; set +a`.

It prints a PASS/FAIL report covering: the season your settings resolve to, today's NBA
scoreboard versus the team codes on your roster (`todaysGame`), and a current-week
`analyze_matchup` with games-remaining and projection sanity checks. If none of the teams
whose abbreviations differ between ESPN endpoints (GSW, UTA, WAS, NOP, NYK, SAS) play today,
it tells you the next date each one does so you can re-run. It never prints cookie values and
exits non-zero if any check fails.

### Continuous Integration

GitHub Actions (`.github/workflows/test.yml`) runs on every push and on pull requests into `main`, across Python 3.10–3.12. It installs from `uv.lock` (`uv sync --locked`) so CI uses exactly the versions committed here, and it runs the same four checks as `scripts/check.sh`. The workflow has read-only repository permissions and uses no secrets.

Coverage is enforced with `fail_under` in `pyproject.toml`. It is currently set low (40%) because the matchup, schedule, and settings code added in 2025 does not have tests yet. Raise it as tests are added.

### Working on this repo from your phone

Claude Code *cloud sessions* run on Anthropic's infrastructure and are driven from the **Code**
tab of the Claude iOS/Android app, so you can ask for a change, close the app, and come back
to a pushed branch. One-time setup, done in a browser at [claude.ai/code](https://claude.ai/code):
connect GitHub and install the Claude GitHub App on this repository. (If you have already run
a cloud session on this repo, that is done.) After that, on the phone:

1. Open the Claude app, tap **Code**, then start a new session.
2. Pick this repository and a base branch, describe the change, and send it.
3. Claude works on its own branch and pushes. From the session you can review the diff, ask
   for changes, and create a pull request. Tell it to *"watch this PR and fix CI failures or
   review comments"* to have it respond to GitHub activity on its own.

Cloud sessions start from a fresh clone with nothing installed. `.claude/hooks/session-start.sh`,
registered in `.claude/settings.json`, runs `uv sync --locked --all-extras --dev` at the start of
every cloud session so `uv run pytest`, ruff, mypy, and `./scripts/check.sh` work from the first
message. The hook exits immediately outside the cloud (`CLAUDE_CODE_REMOTE` unset), so it never
touches your local machine. Sessions read the hook from the branch they start on, so it applies
to new sessions once it is on `main`. `CLAUDE.md` gives each session the project conventions.

### Project Structure

```
espn-fantasy-basketball-mcp/
├── espn_fantasy_basketball.py      # Main MCP server using FastMCP (stdio or HTTP via MCP_TRANSPORT)
├── espn_fantasy_basketball_mcp/    # Core library package
│   ├── __init__.py
│   ├── client.py                   # ESPN API client and analysis logic
│   ├── models.py                   # Pydantic data models
│   ├── http_transport.py           # Streamable HTTP transport + bearer-token auth (remote use)
│   └── server.py                   # Legacy low-level MCP server (unused; kept for reference)
├── tests/                          # Test suite (all ESPN calls are mocked; no network needed)
│   ├── test_client.py             # Client tests
│   ├── test_draft.py              # Draft client tests
│   ├── test_draft_server.py       # Draft tool tests
│   ├── test_http_transport.py     # HTTP transport, auth gate, and MCP-over-HTTP tests
│   ├── test_matchup_analysis.py   # Matchup analysis tests
│   ├── test_models.py             # Model tests
│   ├── test_pro_teams.py          # NBA team abbreviation tests
│   ├── test_server.py             # Server tool tests
│   ├── test_statistics.py         # Player stats / comparison / trade client tests
│   ├── test_statistics_server.py  # Player stats tool tests
│   └── test_verify_live.py        # Tests for the live verification script's config loading
├── conftest.py                    # Pytest fixtures
├── scripts/check.sh               # Runs the CI checks locally
├── scripts/verify_live.py         # Read-only check against your real league
├── Dockerfile                     # Image for hosting the server as a remote MCP server
├── .claude/                       # Claude Code cloud-session hook (installs deps on start)
├── CLAUDE.md                      # Conventions for Claude Code sessions
├── .github/workflows/test.yml     # CI
├── pyproject.toml                 # Project configuration, tool settings, coverage gate
├── uv.lock                        # Locked dependency versions (used by CI)
├── requirements.txt               # Dependencies (for pip users)
├── Pipfile                        # Dependencies (for pipenv users)
├── .python-version               # Python version for pyenv/uv
└── README.md                     # This file
```

## API Endpoints Used

This MCP server uses the following ESPN API endpoints:

### Fantasy Basketball API
- **Base URL**: `https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba`
- **League Data**: `/seasons/{year}/segments/0/leagues/{league_id}`
  - Teams: `?view=mTeam`
  - League settings and status: `?view=mSettings`
  - Rosters: `?view=mRoster`
  - Matchups and schedule: `?view=mMatchup`
  - Draft: `?view=mDraftDetail`
  - Players, free agents, and stats: `?view=kona_player_info` with an `x-fantasy-filter` request header

### NBA Schedule API
- **Base URL**: `https://site.api.espn.com/apis/site/v2/sports/basketball/nba`
- **Today's games**: `/scoreboard`
- **Team season schedule**: `/teams/{team_id}/schedule`

## API Limitations & Alternatives Needed

### Current Limitations

1. **Free Agents Query Limit**: ESPN API only returns up to 50 players per request for free agents
2. **Private League Access**: Requires ESPN authentication cookies (`espn_s2` and `SWID`)
3. **Rate Limiting**: ESPN may rate limit requests (not officially documented)
4. **Undocumented API**: ESPN's fantasy API is not officially documented and may change
5. **Data Completeness**: Some fields like team `location` are not provided by ESPN's API
6. **Season Dependency**: API behavior may vary between active and inactive seasons

### Alternative APIs You May Need

1. **NBA Player Stats & Advanced Metrics**
   - **NBA Stats API**: `https://stats.nba.com/stats/` (official but rate limited)
   - **Basketball Reference**: Web scraping required
   - **RapidAPI Sports**: Paid API with comprehensive NBA data

2. **Real-time NBA Data**
   - **ESPN NBA API**: `https://site.api.espn.com/apis/site/v2/sports/basketball/nba` (used for schedule)
   - **NBA Data API**: `https://data.nba.net/prod/` (official but limited)

3. **Advanced Fantasy Analytics**
   - **FantasyLabs API**: Paid service with projections and ownership data
   - **DraftKings API**: For DFS ownership and salaries
   - **Hashtag Basketball**: Free projections (web scraping required)

4. **Player News & Injuries**
   - **ESPN News API**: Limited access
   - **The Athletic API**: Requires subscription
   - **Reddit API**: r/fantasybball for community insights

### Position IDs Reference

ESPN uses the following position IDs:
- 0: Point Guard (PG)
- 1: Shooting Guard (SG) 
- 2: Small Forward (SF)
- 3: Power Forward (PF)
- 4: Center (C)
- 5: Guard (G)
- 6: Forward (F)
- 12: Bench
- 13: IR (Injured Reserve)

## Example Usage

### Via MCP Tools (in Claude Desktop)

Once configured, you can ask Claude to:
- "Get all teams in my fantasy basketball league"
- "Show me the roster for the Lakers team"
- "What free agents are available?"
- "Show me this week's matchups"
- "What NBA games are today?"

### Direct Python Usage

```python
from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient

# Initialize client
client = ESPNFantasyBasketballClient(
    league_id=12345,
    year=2025,
    espn_s2="your_espn_s2_cookie",  # For private leagues
    swid="your_swid_cookie"         # For private leagues
)

# Get all teams in league
teams = await client.get_league_teams()

# Get roster for team ID 1
roster = await client.get_team_roster(team_id=1)

# Get top 25 free agent guards
free_agents = await client.get_free_agents(size=25, position_id=5)

# Get current week matchups
matchups = await client.get_matchups()

# Get today's NBA games
nba_games = await client.get_nba_schedule()
```

## Troubleshooting

### Common Issues

1. **"Team not found" errors**: Verify your league ID and ensure you have access to the league
2. **"team_id is required" errors**: Set `ESPN_TEAM_ID` in your MCP config or pass `team_id` to the tool
3. **Wrong season or empty data**: Check `ESPN_YEAR` if you set it. ESPN names seasons by the year they end in, so the 2026-27 season is `2027`. Unset, the server infers the current season from the date
4. **Authentication errors**: Check that your `espn_s2` and `SWID` cookies are correct and not expired
5. **Empty results**: Some data may not be available during off-season or for certain league settings
6. **Rate limiting**: ESPN may temporarily block requests if you make too many in quick succession. `analyze_matchup` in particular makes many requests

### Debug Mode

The client includes error handling and logging. For debugging, check the server logs when running:

```bash
uv run espn_fantasy_basketball.py
```

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes and add tests
4. Run tests: `uv run pytest`
5. Run code quality checks: `uv run black . && uv run ruff .`
6. Commit your changes: `git commit -am 'Add feature'`
7. Push to the branch: `git push origin feature-name`
8. Create a Pull Request

## License

MIT License - see LICENSE file for details.
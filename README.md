# ESPN Fantasy Basketball MCP Server

[![Tests](https://github.com/lindsayevanslee/espn-fantasy-basketball-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/lindsayevanslee/espn-fantasy-basketball-mcp/actions/workflows/test.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Type checked: mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](https://mypy-lang.org/)

An MCP (Model Context Protocol) server that provides access to ESPN Fantasy Basketball APIs. This server enables Claude and other MCP clients to fetch fantasy basketball data including league settings, teams, rosters, free agents, matchups, player statistics, NBA schedules, and to analyze your current matchup.

> **Note**: This is an unofficial third-party tool and is not affiliated with or endorsed by ESPN.
>
> This repository is a fork of [dylancharris/espn-fantasy-basketball-mcp](https://github.com/dylancharris/espn-fantasy-basketball-mcp) with additional tools, bug fixes, and hardening.

> **New here?** [TUTORIAL.md](TUTORIAL.md) explains how the server works end to end: the request lifecycle, each module, how ESPN's API is shaped, and how to add and test a tool.

## Features

### Available Tools

#### League & Roster Tools
1. **get_league_teams** - All teams in standings order (`standingsRank`, ESPN's `playoffSeed`), with `isMyTeam`, ESPN's record labelled as category or matchup wins, the matchup-level W-L-T derived from the schedule (`matchupRecord`), waiver rank, and acquisitions used vs. the limit this matchup
2. **get_league_settings** - Scoring categories, roster slots, matchup period calendar dates, waiver rules (order reset, process time) and acquisition limits in plain English, including the per-matchup allowance when the limit is per day
3. **get_team_roster** - Roster for a team with per-game stats (incl. FGM/FGA/FTM/FTA), injury status with ESPN's reason and expected return (and an `injuryStatusNote` when the two disagree, e.g. OUT vs. "probable"), today's game, which scoring period (day) the roster is for and which starting slots are locked for it; players ESPN still lists but who were dropped are removed and named in `staleEntriesRemoved`
4. **get_team_season_stats** - Season category totals for a team, its matchup W-L-T over completed periods (never category tallies) next to ESPN's own labelled record, win percentage, and games back on the matchup record
5. **get_free_agents** - Free agents/waiver wire players with ownership percentages, injury detail, and whether each is addable now or on waivers until a given time (pass `verbose=true` for stats)
6. **get_nba_schedule** - Get NBA game schedule for a date
7. **get_transactions** - Recent adds, drops, waiver claims and trades with player and team names, newest first (answers "why is this player on waivers")

#### Matchup Tools
8. **get_matchups** - Matchups for a matchup period, with category scores by human-readable name
9. **get_my_current_matchup** - Your current matchup, both rosters with per-game averages, and category scores in one call (`verbose=true` adds season totals)
10. **analyze_matchup** - Category-by-category projections on a chosen basis (ESPN projections, season actuals, last 7/15/30 days, or a blend) applied to both teams, close and near categories, start/sit priorities with season and projected lines side by side, and lineup warnings. In a weekly-lock league only starting slots count (bench players are listed separately); a player listed OUT with a reported return date inside the week keeps the games from that date
11. **simulate_roster_move** - What if I drop X and add Y? Re-runs the projection before and after on one basis and returns per-category deltas, categories that flip, the added players' lines, which slot each added player was given (a dropped starter's when it can still be filled, else the bench), and whether the move is legal
12. **can_add_player** - Roster-legality check for an add (and optional drops): roster size, position limits by primary position and by eligibility (the verdict's basis is configurable; the current roster is used as evidence of which count ESPN enforces), acquisitions left, and whether each player is a free agent, on waivers, or owned
13. **get_roster_schedule** - Games this matchup period and next for every player on your roster, using the league's own period-to-date mapping; pass `player_ids` to compare streaming candidates alongside
14. **get_player_schedule** - Games this matchup period and next for any ESPN player IDs (free agents, trade targets), with the date windows counted

#### Player Analysis Tools
15. **search_players** - Find ESPN player IDs by name (last name, partial, accented, or misspelled) and see whether each match is a free agent in your league or who owns them
16. **get_player_stats** - Stats for one or many players by ESPN player ID (`season`, `projections`, `last_7`, `last_15`, `last_30`)
17. **compare_players** - Compare players across categories
18. **analyze_trade_proposal** - Value and category impact of a proposed trade
19. **get_trending_players** - Players trending up or down in ownership

#### Live Draft Assistant Tools
20. **get_draft_status** - Get current draft status including all picks and progress
21. **should_i_bid** - Get recommendation on whether to bid for the current player being nominated
22. **who_should_i_target_next** - Get recommendation on which player to target/nominate next
23. **analyze_my_draft_strategy** - Analyze your current draft strategy and spending patterns
24. **get_available_players** - Get top available players for the draft with auction values

Every tool returns a single JSON object. Tools that list several items wrap them as `{"count": N, "<items>": [...]}` with the list under `teams`, `players`, `matchups`, `games`, `transactions`, or `matches`, because FastMCP would otherwise deliver a bare list as one message per element. Tools that take a `player_id` expect ESPN's numeric ID; use `search_players` to find it from a name. Most tools read `ESPN_LEAGUE_ID`, `ESPN_TEAM_ID` and `ESPN_YEAR` from the environment, so you rarely need to pass them. The ESPN cookies (`ESPN_S2`, `ESPN_SWID`) are read from the environment **only**: no tool accepts them as a parameter, because a parameter value would be written into the conversation transcript. Tools that act on *your* team require a team ID, either as a parameter or via `ESPN_TEAM_ID`, and return a clear error if neither is set.

Tool responses leave out fields ESPN did not populate (no `null` padding) and the raw stat-ID blocks; everything is available under a named field. The one exception is a player's `stats` dict, where `fg_pct` / `ft_pct` are null exactly when the player has zero attempts (the attempt counts sit alongside).

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
- **ESPN_POSITION_LIMIT_BASIS**: How `can_add_player` and `simulate_roster_move` count players against the league's position limits: `primary` (default; each player counts once, at his default position) or `eligibility` (every position he is eligible at). ESPN does not document which it uses for basketball; the response reports both counts either way. If ESPN rejects an add this tool allowed, set `eligibility`.
- **ESPN_MCP_DISABLE_CACHE**: Set to `1` to bypass the response cache (see [Caching](#caching))

The `MY_TIMEZONE` variable controls how dates and times are converted from UTC in API responses. All ISO datetime strings (such as game times, acquisition dates, and trade deadlines) will be converted to this timezone. Use standard IANA timezone names (e.g., `America/Los_Angeles`, `America/Chicago`, `Europe/London`). If not set, the default is `America/New_York`.

These apply only when serving the tools over HTTP for claude.ai and the Claude mobile app (see
[Using the server from the Claude mobile app](#using-the-server-from-the-claude-mobile-app-remote-mcp)):

- **MCP_TRANSPORT**: `stdio` (default, for Claude Desktop and Claude Code) or `streamable-http`.
- **MCP_AUTH_TOKEN**: Required in HTTP mode. A random secret of at least 32 characters. In `bearer` mode every request must present it as `Authorization: Bearer <token>`; in `oauth` mode it is the passphrase you type on the sign-in page and the key that signs the tokens. The server refuses to start over HTTP without it.
- **MCP_AUTH_MODE**: `bearer` (default) or `oauth`. Use `oauth` for claude.ai and the Claude mobile app; see the section above for when each applies.
- **MCP_PUBLIC_URL**: Required in `oauth` mode. The HTTPS origin the server is reached at, with no path, e.g. `https://espn-fantasy-mcp-abc123-uc.a.run.app`. The MCP endpoint is that plus `/mcp`.
- **MCP_HOST**: Bind address in HTTP mode. Defaults to `127.0.0.1`; the Docker image sets `0.0.0.0`.
- **PORT**: Bind port in HTTP mode. Defaults to `8000`; the Docker image sets `8080`, and hosting platforms that inject `PORT` are honoured.

### Caching

ESPN responses are cached in memory for the life of the server process and shared across tool
calls. Each endpoint has its own lifetime, chosen by how fast the data changes:

| Data | Lifetime |
|---|---|
| NBA team season schedule | 6 hours |
| All active NBA players (for name search) | 6 hours |
| League settings | 10 minutes |
| League team list | 5 minutes |
| Today's NBA scoreboard | 60 seconds |
| Everything else (rosters, matchups, players, draft) | 15 seconds |

The 15-second lifetime for live data exists only to collapse the many identical requests a single
tool call makes (for example `analyze_matchup` fetching league settings once per player). It is
short enough that a roster move shows up on your next question. Concurrent identical requests
share one in-flight fetch, and failed requests are never cached. Set `ESPN_MCP_DISABLE_CACHE=1`
to turn the cache off.

## Using the server from the Claude mobile app (remote MCP)

Claude Desktop launches this server on your computer and talks to it over stdio. The Claude
iOS and Android apps (and claude.ai in a browser) cannot launch a local process; they only talk
to **remote MCP servers** over HTTPS, added to your account as a *custom connector*. This repo
supports that with a second transport:

- `MCP_TRANSPORT=streamable-http` serves the same tools at `/mcp` over MCP's Streamable HTTP
  transport (`espn_fantasy_basketball_mcp/http_transport.py`).
- Every request must carry a valid `Authorization: Bearer` token or it gets a `401` before it
  reaches any tool. The server refuses to start over HTTP without `MCP_AUTH_TOKEN`, tokens are
  never accepted in the URL, and `GET /healthz` is open for platform health checks.
- Two ways to prove you hold `MCP_AUTH_TOKEN`, chosen with `MCP_AUTH_MODE`:
  - **`oauth`** (use this for claude.ai and the Claude app): the server runs a tiny single-user
    OAuth 2.1 sign-in (`espn_fantasy_basketball_mcp/oauth.py`). When you add the connector,
    Claude opens a page on your server, you paste the token once, and Claude receives short-lived
    access tokens plus a refresh token. This is the standard flow every custom connector
    supports, so it works regardless of account or plan.
  - **`bearer`** (default): the token itself is sent on every request. Only for clients that can
    attach a fixed header: Claude Code (`claude mcp add --transport http ... --header
    "Authorization: Bearer ..."`) and claude.ai accounts that have the **Request headers** beta
    in the connector dialog. Most accounts do not; if yours only shows **Name** and **URL**, use
    `oauth`.
- Your ESPN cookies live only in the hosted server's environment. Anyone who knows
  `MCP_AUTH_TOKEN` can sign in and read your league, so treat it like a password.

The Claude app itself is only a client: once you have added the connector on claude.ai in a
browser, it is available in the mobile app automatically. You cannot add connectors from the
phone.

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

To try the sign-in flow locally, add `MCP_AUTH_MODE=oauth MCP_PUBLIC_URL=http://localhost:8000`
(plain `http` is accepted only for localhost) and open
`http://localhost:8000/.well-known/oauth-authorization-server` to see the discovery document
Claude reads.

### 2. Host it with HTTPS

The `Dockerfile` runs as an unprivileged user, listens on `$PORT`, and works unchanged on
Google Cloud Run, Fly.io, Railway, and Render. All of them terminate TLS for you, which is
required: tokens travel in a header and must only cross the internet over HTTPS. Cloud Run
scales to zero and bills only while a request is being handled, so a personal server stays
inside its free tier (see [What it costs](#what-it-costs)). It is the suggested default.

You need a Google Cloud project with billing enabled. The easiest place to run the commands
is [Cloud Shell](https://shell.cloud.google.com), a browser terminal with `gcloud` already
installed and signed in, so nothing has to be installed on your computer. Clone this repository
there, `cd` into it, and run the blocks below in order in the same terminal.

**Choose a project first.** A new Cloud Shell session has no project selected, and every
command below needs one. A project of its own for this server is the tidy option: its secrets,
service account, and budget alert stay separate from anything else you run, and deleting the
project later removes everything. The free allowances are per billing account, so an extra
project costs nothing.

```bash
gcloud projects list                                   # what you already have
gcloud projects create espn-mcp-YOURNAME --name "ESPN MCP"   # or skip this and reuse one; IDs are globally unique
gcloud config set project espn-mcp-YOURNAME

gcloud billing accounts list                           # copy the ACCOUNT_ID that is open
gcloud billing projects link espn-mcp-YOURNAME --billing-account ACCOUNT_ID
gcloud billing projects describe espn-mcp-YOURNAME --format='value(billingEnabled)'   # True
```

**a. Names.** Cloud Run gives every service a predictable URL built from the service name,
project number, and region, so the sign-in can be told its own address before the first deploy.
The `echo` must print a URL with a 12-digit number in it, like
`https://espn-fantasy-mcp-123456789012.us-central1.run.app`. If the number is missing, no
project is selected; go back one step.

```bash
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
REGION=us-central1
SERVICE=espn-fantasy-mcp
URL="https://${SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"
echo "$URL"

gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com
```

**b. Secrets.** These go into Secret Manager, never into the deploy command, your shell
history, or the image. `read -s` keeps what you paste off the screen.

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32), end="")' \
  | gcloud secrets create espn-mcp-token --data-file=-

read -rsp 'Paste ESPN_S2: ' V && printf '%s' "$V" | gcloud secrets create espn-s2 --data-file=-; unset V; echo
read -rsp 'Paste ESPN_SWID (with the braces): ' V && printf '%s' "$V" | gcloud secrets create espn-swid --data-file=-; unset V; echo
```

**c. A service account that can read those three secrets and nothing else.** Without this the
service would run as the project's default account, which usually has far broader rights.

```bash
gcloud iam service-accounts create espn-mcp-runner --display-name "ESPN MCP runtime"
SA="espn-mcp-runner@${PROJECT_ID}.iam.gserviceaccount.com"
for s in espn-mcp-token espn-s2 espn-swid; do
  gcloud secrets add-iam-policy-binding "$s" \
    --member "serviceAccount:${SA}" --role roles/secretmanager.secretAccessor
done
```

**d. Deploy.** Replace the league ID, team ID, and timezone with yours. The first run asks to
create a container repository; answer yes. `.env` is never uploaded (it is in `.gitignore`,
which `gcloud` honours, and in `.dockerignore`).

```bash
gcloud run deploy "$SERVICE" --source . --region "$REGION" \
  --service-account "$SA" \
  --allow-unauthenticated \
  --min-instances 0 --max-instances 1 --timeout 60 --cpu 1 --memory 512Mi \
  --set-env-vars "MCP_AUTH_MODE=oauth,MCP_PUBLIC_URL=${URL},ESPN_LEAGUE_ID=123456,ESPN_TEAM_ID=1,MY_TIMEZONE=America/Chicago" \
  --set-secrets "MCP_AUTH_TOKEN=espn-mcp-token:latest,ESPN_S2=espn-s2:latest,ESPN_SWID=espn-swid:latest"
```

- `--allow-unauthenticated` only removes Google's own sign-in gate, which Claude cannot pass.
  The server still rejects every MCP request without a valid token.
- `--max-instances 1` is the hard ceiling on what the service can ever cost, and
  `--timeout 60` stops any single request from running longer than a minute.

**e. Check it.**

```bash
curl -s "$URL/healthz"                                        # {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$URL/mcp"   # 401
curl -s "$URL/.well-known/oauth-protected-resource"          # "resource" is exactly $URL/mcp
echo "MCP server URL for Claude: $URL/mcp"
```

If the first `curl` cannot reach the service, print the address Cloud Run assigned with
`gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)'`, set
`URL` to it, and run `gcloud run services update "$SERVICE" --region "$REGION"
--update-env-vars "MCP_PUBLIC_URL=${URL}"`. The address you give Claude and `MCP_PUBLIC_URL`
must be the same one.

When you reach the sign-in page in step 3, this prints the passphrase to paste:

```bash
gcloud secrets versions access latest --secret espn-mcp-token; echo
```

**Later.** To ship new code, pull it and repeat block d (re-run block a first in a fresh
terminal to set the variables). When `ESPN_S2` expires, add a new version and redeploy:
`read -rsp 'ESPN_S2: ' V && printf '%s' "$V" | gcloud secrets versions add espn-s2 --data-file=-; unset V`,
then disable the old version in the console so it stops counting toward the free allowance.
To revoke every Claude sign-in at once, add a new version of `espn-mcp-token` the same way.

#### What it costs

Expected cost for one person's use is zero. Google's always-free allowances, per billing
account per month, as of November 2026 (check
[the Cloud Run pricing page](https://cloud.google.com/run/pricing) and
[the free tier list](https://cloud.google.com/free) before relying on them):

| Service | Free each month | What this server uses |
|---|---|---|
| Cloud Run | 2 million requests, 180,000 vCPU-seconds, 360,000 GiB-seconds | Billed only while a request is in flight; a tool call takes a few seconds |
| Secret Manager | 6 active secret versions, 10,000 reads | 3 versions; read once per cold start |
| Artifact Registry | 0.5 GB of storage | One image of about 225 MB uncompressed per deploy; delete old ones |
| Cloud Build | 2,500 build-minutes | A minute or two per deploy |

Three things keep it there. The server answers `GET /mcp` with `405` instead of holding a
stream open, because an open connection is billable time. `--max-instances 1` caps the worst
case: one instance busy every second of a month is roughly $65, and reaching that would take
continuous traffic. And you should add a budget alert (**Billing > Budgets & alerts**, a $1
budget with email alerts): alerts do not stop spending, but they tell you the same day.

On Fly.io the equivalent is `fly launch --no-deploy`, `fly secrets set MCP_AUTH_TOKEN=... ESPN_S2=... ESPN_SWID=...`,
the non-secret variables (including `MCP_AUTH_MODE=oauth` and `MCP_PUBLIC_URL=https://<app>.fly.dev`)
in `fly.toml` under `[env]`, then `fly deploy`.

### 3. Add it to Claude as a custom connector

Do this once, on claude.ai in a browser (Pro or Max plan; on Team or Enterprise an Owner adds it
under **Organization settings > Connectors**):

1. Go to **Customize > Connectors** and click **Add custom connector**.
2. Name it (for example `ESPN Fantasy Basketball`) and enter the **MCP server URL**:
   `https://YOUR-SERVICE.run.app/mcp`. Leave any OAuth client ID/secret fields under
   **Advanced settings** empty: Claude registers itself with the server automatically. If your
   dialog asks, choose **Sign in now** and **Register automatically**.
3. Click **Add**, then **Connect**. Claude opens your server's sign-in page.
4. Paste your `MCP_AUTH_TOKEN` into the passphrase box and press **Allow**. You are sent back
   to claude.ai and the connector shows as connected.

That is the only time you type the token. Claude keeps a refresh token and renews access on
its own for 30 days, after which it asks you to sign in again. To cut off access at any time,
deploy a new `MCP_AUTH_TOKEN`: every existing token stops working immediately.

If your dialog *does* have a **Request headers** section you may instead deploy with
`MCP_AUTH_MODE=bearer` (the default), choose **No sign-in**, pick the `authorization` header,
and enter `Bearer <your MCP_AUTH_TOKEN>` as its value. Either mode is equally secure; `oauth` is
recommended because it works for every account.

Then, on your phone, open the Claude app, start a chat, tap **+**, choose **Connectors**, and
turn the connector on. Ask something like *"Using my ESPN connector, how is my matchup looking
this week?"*; the first call will ask you to allow the tool.

### How the sign-in works, and its limits

Claude follows the MCP authorization spec: your server answers an unauthenticated request with
`401` and a pointer to its discovery documents, Claude registers itself as an OAuth client
(Dynamic Client Registration), sends you to `/authorize`, which shows the passphrase page, and
exchanges the resulting code for tokens using PKCE. The MCP SDK provides those endpoints and all
of the protocol checks; this repo adds the login page and a provider that needs **no database**:
clients, codes and tokens are HMAC-signed payloads keyed from `MCP_AUTH_TOKEN`, so the server
works on hosts that restart or scale to zero. Client registration is restricted to Claude's
callback URL and the loopback callback Claude Code uses, so no third party can register a
client that receives your codes.

Being stateless has two consequences: a refresh token stays valid until it expires (30 days)
even after a newer one is issued, and the only way to revoke access is to change
`MCP_AUTH_TOKEN`, which revokes everything at once. Both are acceptable for a server with one
owner; if you ever share the server, move to a real user store.

### Security notes for the hosted server

- `MCP_AUTH_TOKEN` is the only thing between the internet and your league. Generate it
  randomly (the command above), never commit it, and keep it out of chat logs. The sign-in page
  logs failed attempts with their source IP; a 32-character random token is not guessable
  online, but keep an eye on the logs anyway.
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

The live draft assistant tools are designed for auction drafts and help answer key questions during your draft. Budget, roster size, and nomination order are read from your league's settings, so they work for any league configuration.

> **💡 Pro Tip**: These tools work seamlessly with Claude Desktop! Ask Claude questions like "Should I bid on this player?" or "Who should I target next?" and it will use these tools automatically to give you expert draft advice.

### 🔍 **get_draft_status**
Get the current state of your draft including all picks made so far.

```python
# Get draft status
draft_status = await get_draft_status(
    league_id=123456,
    year=2027,  # ESPN season ID = year the season ends in
    espn_s2="your_espn_s2_cookie",  # for private leagues
    swid="your_swid_cookie"         # for private leagues
)
```

**Returns:**
- `inProgress`: Whether draft is currently active
- `drafted`: Whether draft is completed
- `picks`: Array of all picks made so far with player details
- `currentPickNumber`: Next pick number
- `currentNominatingTeam`: Team on the clock, from the league's draft order (auction nominations cycle; snake drafts reverse in even rounds)
- `draftType`: `AUCTION` or `SNAKE`

### 💰 **should_i_bid**
Get AI-powered recommendation on whether to bid for the current player being nominated.

```python
# Should I bid for this player?
recommendation = await should_i_bid(
    current_player_id=12345,        # Player being nominated
    team_id=1,                      # Your team ID (optional, uses ESPN_TEAM_ID env var)
    league_id=123456,               # Optional, uses ESPN_LEAGUE_ID env var
    year=2027,                      # Optional; ESPN season ID = year the season ends in
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
    year=2027,                      # Optional; ESPN season ID = year the season ends in
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
    year=2027,                      # Optional; ESPN season ID = year the season ends in
    espn_s2="your_espn_s2_cookie",  # Optional, uses ESPN_S2 env var
    swid="your_swid_cookie"         # Optional, uses ESPN_SWID env var
)
```

**Returns:**
- `team_summary`: Your current roster and spending
  - `totalSpent`, `remainingBudget`, `budget`: Spending against the league's auction budget
  - `playersCount`, `rosterSize`, `remainingSlots`: Roster progress against the league's roster size (IR excluded)
  - `positionCounts`: Drafted players by position
  - `draftType`: `AUCTION` or `SNAKE`
- `punt_analysis`: Strategy analysis and recommendations
- `budget_per_remaining_player`: Average $ per remaining roster spot

### 📋 **get_available_players**
Get list of top available players with auction values and rankings.

```python
# Get best available players
players = await get_available_players(
    league_id=123456,
    year=2027,  # ESPN season ID = year the season ends in
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
`--config PATH` if your config lives somewhere unusual, `--server NAME` if you have several
ESPN entries, or `--year 2027` to check a specific season regardless of `ESPN_YEAR`. Alternatively copy `.env.example` to `.env` (gitignored) and load it with
`set -a; source .env; set +a`.

It prints a PASS/FAIL report covering: the season your settings resolve to, today's NBA
scoreboard versus the team codes on your roster (`todaysGame`), and a current-week
`analyze_matchup` with games-remaining and projection sanity checks. If none of the teams
whose abbreviations differ between ESPN endpoints (GSW, UTA, WAS, NOP, NYK, SAS) play today,
it tells you the next date each one does so you can re-run. It never prints cookie values and
exits non-zero if any check fails.

### Fixture-Backed Tests and Recording Your League

`tests/test_fixtures_e2e.py` runs the real request path (settings, matchups, rosters, free
agents, schedules, `analyze_matchup`) against ESPN-shaped JSON files in `tests/fixtures/`, with
the clock frozen on the last day of a matchup period. `tests/fixture_espn.py` maps each ESPN
request to a fixture file name; the committed fixtures are synthetic (regenerate them with
`uv run python tests/fixtures/build_synthetic.py`).

To capture what ESPN actually sends for your league, record it once:

```bash
uv run python scripts/record_fixtures.py            # writes tests/fixtures/recorded/
uv run python scripts/record_fixtures.py --redact-names
```

It makes the same calls the tools make and writes every response under the name the tests
would look it up by, after removing `members`, owner IDs, every GUID (ESPN SWIDs are GUIDs) and
every cookie-shaped token. Cookie values are never printed or written. The recorded folder is
gitignored: it still carries your league's names and rosters, so it stays on your machine.
Delete it with `rm -rf tests/fixtures/recorded` when you are done.
`tests/test_fixture_hygiene.py` scans everything under `tests/fixtures/` for `espn_s2`, `SWID`,
GUIDs and cookie tokens on every test run, so a leaked credential fails CI.

### Continuous Integration

GitHub Actions (`.github/workflows/test.yml`) runs on every push and on pull requests into `main`, across Python 3.10–3.12. It installs from `uv.lock` (`uv sync --locked`) so CI uses exactly the versions committed here, and it runs the same four checks as `scripts/check.sh`. The workflow has read-only repository permissions and uses no secrets.

Coverage is enforced with `fail_under` in `pyproject.toml` (currently 78%, with coverage around 81%). It is a ratchet: raise it as tests are added, never lower it.

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
│   ├── client.py                   # ESPN API client: requests, cache, fetchers, draft, stats
│   ├── analysis.py                 # Matchup analysis: projections, start/sit, lineup warnings
│   ├── constants.py                # Stat IDs, slot/position names, pro team codes, thresholds
│   ├── dates.py                    # Scoring/matchup period calendar math, games remaining
│   ├── search.py                   # Player name matching
│   ├── models.py                   # Pydantic data models
│   ├── http_transport.py           # Streamable HTTP transport + auth gate (remote use)
│   └── oauth.py                    # Single-user OAuth 2.1 sign-in for claude.ai connectors
├── tests/                          # Test suite (all ESPN calls are mocked; no network needed)
│   ├── fixtures/                  # ESPN-shaped JSON responses (synthetic; build_synthetic.py)
│   ├── fixture_espn.py            # Routes client requests to fixtures; freezes the clock
│   ├── test_fixtures_e2e.py       # End-to-end tests over the fixtures
│   ├── test_fixture_hygiene.py    # No credentials or account IDs in any fixture
│   ├── test_cache.py              # Response cache and request de-duplication
│   ├── test_client.py             # Client tests
│   ├── test_draft.py              # Draft client tests
│   ├── test_draft_server.py       # Draft tool tests
│   ├── test_http_transport.py     # HTTP transport, bearer auth gate, and MCP-over-HTTP tests
│   ├── test_matchup_analysis.py   # analyze_matchup projections and recommendations
│   ├── test_matchup_periods.py    # Matchup period -> calendar date mapping
│   ├── test_models.py             # Model tests
│   ├── test_oauth.py              # OAuth discovery, registration, login, PKCE, token tests
│   ├── test_pro_teams.py          # Team abbreviations and today's-game lookups
│   ├── test_search.py             # Player search
│   ├── test_server.py             # Server tool tests
│   ├── test_statistics.py         # Player stats / comparison / trade client tests
│   ├── test_statistics_server.py  # Player stats tool tests
│   └── test_verify_live.py        # Credential loading for the live verification script
├── conftest.py                    # Pytest fixtures
├── scripts/check.sh               # Runs the CI checks locally
├── scripts/verify_live.py         # Read-only checks against your real league
├── scripts/record_fixtures.py     # Records sanitised ESPN responses into tests/fixtures/recorded/
├── Dockerfile                     # Image for hosting the server as a remote MCP server
├── .claude/                       # Claude Code cloud-session hook (installs deps on start)
├── CLAUDE.md                      # Conventions for Claude Code sessions
├── .github/workflows/test.yml     # CI
├── .github/dependabot.yml         # Weekly GitHub Actions updates
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
- **All active players (league-independent)**: `/seasons/{year}/players?view=players_wl`, used by `search_players`

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

### Not Available From ESPN's Fantasy API

The server covers everything ESPN exposes for a league: settings, rosters, free agents, matchups
and box scores, player stats and projections, draft state, and NBA schedules. It does not have
player news beyond ESPN's status codes and public injury report, advanced metrics, play-by-play,
or daily-fantasy data. Ask Claude for those from its own knowledge or another source, and it
should say which is which.

Two things ESPN's API does not say and the server therefore cannot: what the lineup lock code
`INDIVIDUAL_FIRSTGAME_WEEKLY` means (only `INDIVIDUAL_GAME` and `FIRSTGAME_WEEKLY` have been
seen live; `lineupLocktimeDescription` says when a code is not recognised, and the per-slot
`lineupLocked` flags are authoritative), and why `matchupAcquisitionTotals` can carry an entry
for a matchup period that has not started (reported as sent, with a note).

### ESPN ID Reference

Every tool response carries human-readable names next to ESPN's numeric IDs, so you rarely need
these. ESPN uses three different numberings:

**Lineup slot IDs** (`lineupSlotId`, `eligibleSlots`, `lineupSlotCounts`): 0 PG, 1 SG, 2 SF,
3 PF, 4 C, 5 G, 6 F, 7 SG/SF, 8 G/F, 9 PF/C, 10 F/C, 11 UTIL, 12 Bench, 13 IR. Slots 0–6 and
11–13 were confirmed against a live league; 7–10 are inferred from the order of ESPN's roster
settings page and no league seen so far uses them.

**Player position IDs** (`defaultPositionId`): 1 PG, 2 SG, 3 SF, 4 PF, 5 C.

**Position-limit keys** (`rosterSettings.positionLimits`): 1 PG, 2 SG, 3 SF, 4 PF, 5 C (the same
numbering as `defaultPositionId`, plus an unexplained key `0`), where `-1` means no limit.
Confirmed against a league whose settings page shows a maximum of 4 centers. ESPN does not
document for basketball whether the limit counts a player's primary position or every position he
is eligible at; `can_add_player` assumes primary (the key choice above and ESPN's baseball help
article both point that way), reports both counts, and can be switched with
`ESPN_POSITION_LIMIT_BASIS=eligibility` once ESPN has shown which it enforces.

**Pro team IDs** (`proTeamId`): 1–30, with 0 meaning the player is not on an NBA roster (`FA`).
See `espn_fantasy_basketball_mcp/constants.py` for the full table.

## Example Usage

### Via MCP Tools (in Claude Desktop)

Once configured, you can ask Claude things like:
- "How is my matchup going this week, and who should I start?" (`analyze_matchup`)
- "Which of my players have games left this week?" (`get_roster_schedule`)
- "Find Jokic's player ID and tell me who owns him" (`search_players`)
- "Compare Jalen Williams and Cason Wallace over the last 30 days" (`search_players` + `compare_players`)
- "What free agents are trending up?" (`get_trending_players`)
- "What are my league's roster and waiver rules?" (`get_league_settings`)

### Direct Python Usage

```python
from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient

# Initialize client
client = ESPNFantasyBasketballClient(
    league_id=12345,
    year=2027,  # ESPN season ID = year the season ends in; omit to auto-detect
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

# Find a player by name, then analyze your current matchup
jokic = (await client.search_players("Jokic", limit=1))[0]
analysis = await client.analyze_matchup(team_id=1, matchup_period=1)
```

## Troubleshooting

### Common Issues

1. **"Team not found" errors**: Verify your league ID and ensure you have access to the league
2. **"team_id is required" errors**: Set `ESPN_TEAM_ID` in your MCP config or pass `team_id` to the tool
3. **Wrong season or empty data**: Check `ESPN_YEAR` if you set it. ESPN names seasons by the year they end in, so the 2026-27 season is `2027`. Unset, the server infers the current season from the date
4. **Authentication errors**: Check that your `espn_s2` and `SWID` cookies are correct and not expired
5. **Empty results**: Some data may not be available during off-season or for certain league settings
6. **Rate limiting**: ESPN may temporarily block requests if you make too many in quick succession. The response cache keeps repeated calls cheap; `scripts/verify_live.py` reports how many requests a run made

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
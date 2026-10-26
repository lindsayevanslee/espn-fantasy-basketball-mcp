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
9. **analyze_matchup** - Category-by-category projections, close categories, start/sit priorities, and lineup warnings for starters who cannot play (OUT, suspended, unsigned, on IR)
10. **get_roster_schedule** - Games this matchup period and next for every player on your roster, using the league's own period-to-date mapping

#### Player Analysis Tools
11. **search_players** - Find ESPN player IDs by name (last name, partial, accented, or misspelled) and see whether each match is a free agent in your league or who owns them
12. **get_player_stats** - Stats for one or many players by ESPN player ID (`season`, `projections`, `last_7`, `last_15`, `last_30`)
13. **compare_players** - Compare players across categories
14. **analyze_trade_proposal** - Value and category impact of a proposed trade
15. **get_trending_players** - Players trending up or down in ownership

#### Live Draft Assistant Tools
16. **get_draft_status** - Get current draft status including all picks and progress
17. **should_i_bid** - Get recommendation on whether to bid for the current player being nominated
18. **who_should_i_target_next** - Get recommendation on which player to target/nominate next
19. **analyze_my_draft_strategy** - Analyze your current draft strategy and spending patterns
20. **get_available_players** - Get top available players for the draft with auction values

Tools that take a `player_id` expect ESPN's numeric ID; use `search_players` to find it from a name. Most tools read `ESPN_LEAGUE_ID`, `ESPN_TEAM_ID`, `ESPN_YEAR`, `ESPN_S2`, and `ESPN_SWID` from the environment, so you rarely need to pass them. Tools that act on *your* team require a team ID, either as a parameter or via `ESPN_TEAM_ID`, and return a clear error if neither is set.

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
- **ESPN_MCP_DISABLE_CACHE**: Set to `1` to bypass the response cache (see [Caching](#caching))

The `MY_TIMEZONE` variable controls how dates and times are converted from UTC in API responses. All ISO datetime strings (such as game times, acquisition dates, and trade deadlines) will be converted to this timezone. Use standard IANA timezone names (e.g., `America/Los_Angeles`, `America/Chicago`, `Europe/London`). If not set, the default is `America/New_York`.

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
`--config PATH` if your config lives somewhere unusual, `--server NAME` if you have several
ESPN entries, or `--year 2027` to check a specific season regardless of `ESPN_YEAR`. Alternatively copy `.env.example` to `.env` (gitignored) and load it with
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

### Project Structure

```
espn-fantasy-basketball-mcp/
├── espn_fantasy_basketball.py      # Main MCP server using FastMCP
├── espn_fantasy_basketball_mcp/    # Core library package
│   ├── __init__.py
│   ├── client.py                   # ESPN API client and analysis logic
│   ├── models.py                   # Pydantic data models
│   └── server.py                   # Legacy low-level MCP server (unused; kept for reference)
├── tests/                          # Test suite (all ESPN calls are mocked; no network needed)
│   ├── test_client.py             # Client tests
│   ├── test_draft.py              # Draft client tests
│   ├── test_draft_server.py       # Draft tool tests
│   ├── test_models.py             # Model tests
│   ├── test_server.py             # Server tool tests
│   ├── test_statistics.py         # Player stats / comparison / trade client tests
│   └── test_statistics_server.py  # Player stats tool tests
├── conftest.py                    # Pytest fixtures
├── scripts/check.sh               # Runs the CI checks locally
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
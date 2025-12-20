# ESPN Fantasy Basketball MCP Server

[![Tests](https://github.com/dylancharris/espn-fantasy-basketball-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/dylancharris/espn-fantasy-basketball-mcp/actions/workflows/test.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Type checked: mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](https://mypy-lang.org/)

An MCP (Model Context Protocol) server that provides access to ESPN Fantasy Basketball APIs. This server enables Claude and other MCP clients to fetch fantasy basketball data including league teams, player rosters, waiver wire players, matchup schedules, and NBA schedules.

> **Note**: This is an unofficial third-party tool and is not affiliated with or endorsed by ESPN.

## Features

### Available Tools

#### Core Fantasy Tools
1. **get_league_teams** - Get all teams in an ESPN Fantasy Basketball league
2. **get_team_roster** - Get roster for a specific team 
3. **get_free_agents** - Get free agents/waiver wire players
4. **get_matchups** - Get league matchup schedule
5. **get_nba_schedule** - Get NBA game schedule

#### Live Draft Assistant Tools
6. **get_draft_status** - Get current draft status including all picks and progress
7. **should_i_bid** - Get recommendation on whether to bid for the current player being nominated
8. **who_should_i_target_next** - Get recommendation on which player to target/nominate next
9. **analyze_my_draft_strategy** - Analyze your current draft strategy and spending patterns
10. **get_available_players** - Get top available players for the draft with auction values

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
- **ESPN_TEAM_ID**: Your team ID within the league (optional, but recommended for draft tools)
- **ESPN_YEAR**: Season year (optional, defaults to 2025)
- **ESPN_S2**: ESPN authentication cookie for private leagues (required for private leagues)
- **ESPN_SWID**: ESPN SWID cookie for private leagues (required for private leagues)
- **MY_TIMEZONE**: Timezone for date/time conversions (optional, defaults to `America/New_York`)

The `MY_TIMEZONE` variable controls how dates and times are converted from UTC in API responses. All ISO datetime strings (such as game times, acquisition dates, and trade deadlines) will be converted to this timezone. Use standard IANA timezone names (e.g., `America/Los_Angeles`, `America/Chicago`, `Europe/London`). If not set, the default is `America/New_York`.

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
# Lint and format code
uv run ruff check --fix .

# Type checking
uv run mypy espn_fantasy_basketball_mcp/

# Run all CI checks locally
./scripts/check.sh
```

### Project Structure

```
espn-fantasy-basketball-mcp/
├── espn_fantasy_basketball.py      # Main MCP server using FastMCP
├── espn_fantasy_basketball_mcp/    # Core library package
│   ├── __init__.py
│   ├── client.py                   # ESPN API client
│   ├── models.py                   # Pydantic data models
│   └── server.py                   # Legacy MCP server (unused)
├── tests/                          # Test suite
│   ├── test_client.py             # Client tests
│   ├── test_models.py             # Model tests
│   └── test_server.py             # Server tests
├── conftest.py                    # Pytest configuration
├── pyproject.toml                 # Project configuration
├── requirements.txt               # Dependencies (for pip users)
├── Pipfile                        # Dependencies (for pipenv users)
├── .python-version               # Python version for pyenv
└── README.md                     # This file
```

## API Endpoints Used

This MCP server uses the following ESPN API endpoints:

### Fantasy Basketball API
- **Base URL**: `https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba`
- **League Data**: `/seasons/{year}/segments/0/leagues/{league_id}`
  - Teams: `?view=mTeam`
  - Rosters: `?view=mRoster` 
  - Matchups: `?view=mMatchup`
  - Free Agents: `?view=kona_player_info`

### NBA Schedule API
- **Base URL**: `https://site.api.espn.com/apis/site/v2/sports/basketball/nba`
- **Schedule**: `/scoreboard`

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
2. **Authentication errors**: Check that your `espn_s2` and `SWID` cookies are correct and not expired
3. **Empty results**: Some data may not be available during off-season or for certain league settings
4. **Rate limiting**: ESPN may temporarily block requests if you make too many in quick succession

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
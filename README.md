# ESPN Fantasy Basketball MCP Server

[![Tests](https://github.com/dylancharris/espn-fantasy-basketball-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/dylancharris/espn-fantasy-basketball-mcp/actions/workflows/test.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Type checked: mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](https://mypy-lang.org/)

An MCP (Model Context Protocol) server that provides access to ESPN Fantasy Basketball APIs. This server enables Claude and other MCP clients to fetch fantasy basketball data including league teams, player rosters, waiver wire players, matchup schedules, and NBA schedules.

> **Note**: This is an unofficial third-party tool and is not affiliated with or endorsed by ESPN.

## Features

### Available Tools

1. **get_league_teams** - Get all teams in an ESPN Fantasy Basketball league
2. **get_team_roster** - Get roster for a specific team 
3. **get_free_agents** - Get free agents/waiver wire players
4. **get_matchups** - Get league matchup schedule
5. **get_nba_schedule** - Get NBA game schedule

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
        "ESPN_S2": "your_espn_s2_cookie",
        "ESPN_SWID": "your_swid_cookie"
      }
    }
  }
}
```

### Private League Access

For private leagues, you'll need ESPN authentication cookies:
- `ESPN_S2`: ESPN authentication cookie (long string starting with "AE")
- `ESPN_SWID`: ESPN SWID cookie (format: `{12345678-1234-1234-1234-123456789012}`)

To get these cookies:
1. Log into ESPN Fantasy in your browser
2. Open browser developer tools (F12)
3. Go to Application/Storage tab → Cookies → espn.com
4. Find and copy the `espn_s2` and `SWID` cookie values

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
# Format code
uv run black espn_fantasy_basketball_mcp/ tests/

# Type checking
uv run mypy espn_fantasy_basketball_mcp/

# Lint code
uv run ruff espn_fantasy_basketball_mcp/ tests/
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
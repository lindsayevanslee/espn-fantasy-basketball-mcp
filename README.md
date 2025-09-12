# ESPN Fantasy Basketball MCP Server

An MCP (Model Context Protocol) server that provides access to ESPN Fantasy Basketball APIs. This server enables Claude and other MCP clients to fetch fantasy basketball data including league teams, player rosters, waiver wire players, matchup schedules, and NBA schedules.

## Features

### Available Tools

1. **get_league_teams** - Get all teams in an ESPN Fantasy Basketball league
2. **get_team_roster** - Get roster for a specific team
3. **get_free_agents** - Get free agents/waiver wire players
4. **get_matchups** - Get league matchup schedule
5. **get_nba_schedule** - Get NBA game schedule

## Installation

1. Clone or download this repository
2. Install dependencies:
   ```bash
   pip install -e .
   ```

## Usage

### Running the Server

```bash
espn-fantasy-basketball-mcp
```

### Configuration for Claude Desktop

Add to your Claude Desktop configuration:

```json
{
  "mcpServers": {
    "espn-fantasy-basketball": {
      "command": "python",
      "args": ["-m", "espn_fantasy_basketball_mcp.server"],
      "env": {}
    }
  }
}
```

### Private League Access

For private leagues, you'll need ESPN authentication cookies:
- `espn_s2`: ESPN authentication cookie
- `swid`: ESPN SWID cookie

To get these cookies:
1. Log into ESPN Fantasy in your browser
2. Open browser developer tools
3. Find the `espn_s2` and `SWID` cookies in the Application/Storage tab

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

```python
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

## Development

```bash
# Install development dependencies
pip install -e ".[dev]"

# Format code
black espn_fantasy_basketball_mcp/

# Type checking
mypy espn_fantasy_basketball_mcp/

# Lint
ruff espn_fantasy_basketball_mcp/
```
#!/usr/bin/env python3
"""ESPN Fantasy Basketball MCP Server using FastMCP."""

import asyncio
import logging
from typing import List, Optional

from mcp.server.fastmcp import FastMCP
from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient
from espn_fantasy_basketball_mcp.models import Team, Player, Roster, Matchup, NBAGame

# Configure logging to stderr
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("espn-fantasy-basketball-mcp")

# Create the FastMCP server
mcp = FastMCP("ESPN Fantasy Basketball")


@mcp.tool()
async def get_league_teams(
    league_id: int,
    year: int,
    espn_s2: Optional[str] = None,
    swid: Optional[str] = None
) -> List[dict]:
    """Get all teams in an ESPN Fantasy Basketball league.
    
    Args:
        league_id: ESPN Fantasy Basketball league ID
        year: Season year (e.g., 2025)
        espn_s2: ESPN authentication cookie for private leagues (optional)
        swid: ESPN SWID cookie for private leagues (optional)
        
    Returns:
        List of team dictionaries with id, name, location, record, etc.
    """
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    teams = await client.get_league_teams()
    return [team.model_dump() for team in teams]


@mcp.tool()
async def get_team_roster(
    league_id: int,
    year: int,
    team_id: int,
    scoring_period: Optional[int] = None,
    espn_s2: Optional[str] = None,
    swid: Optional[str] = None
) -> dict:
    """Get roster for a specific team in an ESPN Fantasy Basketball league.
    
    Args:
        league_id: ESPN Fantasy Basketball league ID
        year: Season year (e.g., 2025)
        team_id: Team ID to get roster for
        scoring_period: Specific scoring period (optional)
        espn_s2: ESPN authentication cookie for private leagues (optional)
        swid: ESPN SWID cookie for private leagues (optional)
        
    Returns:
        Dictionary with team roster including all players and their positions
    """
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    roster = await client.get_team_roster(team_id, scoring_period)
    return roster.model_dump()


@mcp.tool()
async def get_free_agents(
    league_id: int,
    year: int,
    size: int = 50,
    position_id: Optional[int] = None,
    espn_s2: Optional[str] = None,
    swid: Optional[str] = None
) -> List[dict]:
    """Get free agents/waiver wire players from an ESPN Fantasy Basketball league.
    
    Args:
        league_id: ESPN Fantasy Basketball league ID
        year: Season year (e.g., 2025)
        size: Number of players to return (max 50, default 50)
        position_id: Filter by position ID (optional)
        espn_s2: ESPN authentication cookie for private leagues (optional)
        swid: ESPN SWID cookie for private leagues (optional)
        
    Returns:
        List of available free agent player dictionaries
    """
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    players = await client.get_free_agents(size, position_id)
    return [player.model_dump() for player in players]


@mcp.tool()
async def get_matchups(
    league_id: int,
    year: int,
    scoring_period: Optional[int] = None,
    espn_s2: Optional[str] = None,
    swid: Optional[str] = None
) -> List[dict]:
    """Get matchups/schedule for an ESPN Fantasy Basketball league.
    
    Args:
        league_id: ESPN Fantasy Basketball league ID
        year: Season year (e.g., 2025)
        scoring_period: Specific scoring period to get matchups for (optional)
        espn_s2: ESPN authentication cookie for private leagues (optional)
        swid: ESPN SWID cookie for private leagues (optional)
        
    Returns:
        List of matchup dictionaries with home/away teams and scores
    """
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    matchups = await client.get_matchups(scoring_period)
    return [matchup.model_dump() for matchup in matchups]


@mcp.tool()
async def get_nba_schedule(date: Optional[str] = None) -> List[dict]:
    """Get NBA schedule for a specific date.
    
    Args:
        date: Date in YYYY-MM-DD format (optional, defaults to today)
        
    Returns:
        List of NBA game dictionaries with teams, times, and details
    """
    # Create a temporary client just for NBA API access
    client = ESPNFantasyBasketballClient(1, 2025)  # Dummy values for NBA API
    games = await client.get_nba_schedule(date)
    return [game.model_dump() for game in games]


if __name__ == "__main__":
    # Run the server
    mcp.run(transport="stdio")
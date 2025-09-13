#!/usr/bin/env python3
"""ESPN Fantasy Basketball MCP Server using FastMCP."""

import logging

from mcp.server.fastmcp import FastMCP

from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient

# Configure logging to stderr
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("espn-fantasy-basketball-mcp")

# Create the FastMCP server
mcp = FastMCP("ESPN Fantasy Basketball")


@mcp.tool()
async def get_league_teams(
    league_id: int,
    year: int,
    espn_s2: str | None = None,
    swid: str | None = None
) -> list[dict]:
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
    scoring_period: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None
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
    position_id: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None
) -> list[dict]:
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
    scoring_period: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None
) -> list[dict]:
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
async def get_nba_schedule(date: str | None = None) -> list[dict]:
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


@mcp.tool()
async def get_draft_status(
    league_id: int,
    year: int,
    espn_s2: str | None = None,
    swid: str | None = None
) -> dict:
    """Get current draft status including all picks and progress.

    Args:
        league_id: ESPN Fantasy Basketball league ID
        year: Season year (e.g., 2025)
        espn_s2: ESPN authentication cookie for private leagues (optional)
        swid: ESPN SWID cookie for private leagues (optional)

    Returns:
        Dictionary with draft status, picks, and current state
    """
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    draft_status = await client.get_draft_status()
    return draft_status.model_dump()


@mcp.tool()
async def should_i_bid(
    league_id: int,
    year: int,
    team_id: int,
    current_player_id: int,
    espn_s2: str | None = None,
    swid: str | None = None
) -> dict:
    """Get recommendation on whether to bid for the current player being nominated.

    Args:
        league_id: ESPN Fantasy Basketball league ID
        year: Season year (e.g., 2025)
        team_id: Your team ID
        current_player_id: ID of player currently being nominated
        espn_s2: ESPN authentication cookie for private leagues (optional)
        swid: ESPN SWID cookie for private leagues (optional)

    Returns:
        Dictionary with bid recommendation, suggested amount, and reasoning
    """
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    recommendation = await client.get_draft_recommendation(team_id, current_player_id)
    return recommendation.model_dump()


@mcp.tool()
async def who_should_i_target_next(
    league_id: int,
    year: int,
    team_id: int,
    espn_s2: str | None = None,
    swid: str | None = None
) -> dict:
    """Get recommendation on which player to target/nominate next.

    Args:
        league_id: ESPN Fantasy Basketball league ID
        year: Season year (e.g., 2025)
        team_id: Your team ID
        espn_s2: ESPN authentication cookie for private leagues (optional)
        swid: ESPN SWID cookie for private leagues (optional)

    Returns:
        Dictionary with player recommendation and reasoning
    """
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    recommendation = await client.get_draft_recommendation(team_id, None)
    return recommendation.model_dump()


@mcp.tool()
async def analyze_my_draft_strategy(
    league_id: int,
    year: int,
    team_id: int,
    espn_s2: str | None = None,
    swid: str | None = None
) -> dict:
    """Analyze your current draft strategy and spending patterns.

    Args:
        league_id: ESPN Fantasy Basketball league ID
        year: Season year (e.g., 2025)
        team_id: Your team ID
        espn_s2: ESPN authentication cookie for private leagues (optional)
        swid: ESPN SWID cookie for private leagues (optional)

    Returns:
        Dictionary with punt strategy analysis, spending summary, and recommendations
    """
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)

    # Get team summary and strategy analysis
    team_summary = await client.get_team_draft_summary(team_id)
    punt_analysis = await client.analyze_punt_strategy(team_id)

    return {
        "team_summary": team_summary.model_dump(),
        "punt_analysis": punt_analysis,
        "budget_per_remaining_player": round(team_summary.remainingBudget / max(1, 13 - team_summary.playersCount), 2)
    }


@mcp.tool()
async def get_available_players(
    league_id: int,
    year: int,
    limit: int = 50,
    espn_s2: str | None = None,
    swid: str | None = None
) -> list[dict]:
    """Get top available players for the draft with auction values.

    Args:
        league_id: ESPN Fantasy Basketball league ID
        year: Season year (e.g., 2025)
        limit: Number of players to return (default 50)
        espn_s2: ESPN authentication cookie for private leagues (optional)
        swid: ESPN SWID cookie for private leagues (optional)

    Returns:
        List of available player dictionaries with auction values and rankings
    """
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    players = await client.get_available_players(limit)
    return [player.model_dump() for player in players]


if __name__ == "__main__":
    # Run the server
    mcp.run(transport="stdio")

#!/usr/bin/env python3
"""ESPN Fantasy Basketball MCP Server using FastMCP."""

import logging
import os

from mcp.server.fastmcp import FastMCP

from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("espn-fantasy-basketball-mcp")

# Create the FastMCP server
mcp = FastMCP("ESPN Fantasy Basketball")


def _get_espn_credentials(
    league_id: int | None = None,
    year: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> tuple[int, int, str | None, str | None]:
    """Get ESPN credentials from parameters or environment variables.

    Args:
        league_id: League ID parameter (optional)
        year: Year parameter (optional)
        espn_s2: ESPN S2 cookie parameter (optional)
        swid: ESPN SWID parameter (optional)

    Returns:
        Tuple of (league_id, year, espn_s2, swid) with environment fallbacks
    """
    # Use provided parameters or fall back to environment variables
    final_league_id = league_id or int(os.getenv("ESPN_LEAGUE_ID", "0"))
    final_year = year or int(os.getenv("ESPN_YEAR", "2025"))
    final_espn_s2 = espn_s2 or os.getenv("ESPN_S2")
    final_swid = swid or os.getenv("ESPN_SWID")

    return final_league_id, final_year, final_espn_s2, final_swid


def _get_team_id(team_id: int | None = None) -> int | None:
    """Get team ID from parameter or environment variable.

    Args:
        team_id: Team ID parameter (optional)

    Returns:
        Team ID with environment fallback, or None if not configured
    """
    if team_id is not None:
        return team_id

    env_team_id = os.getenv("ESPN_TEAM_ID")
    return int(env_team_id) if env_team_id else None


@mcp.tool()
async def get_league_teams(
    league_id: int | None = None,
    year: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> list[dict]:
    """Get all teams in an ESPN Fantasy Basketball league.

    Args:
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        List of team dictionaries with id, name, location, record, etc.
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    teams = await client.get_league_teams()
    return [team.model_dump() for team in teams]


@mcp.tool()
async def get_league_settings(
    league_id: int | None = None,
    year: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> dict:
    """Get league settings including schedule, roster, scoring, and acquisition configuration.

    This provides important information for making recommendations:
    - Week boundaries and matchup periods
    - Lineup lock times and position limits
    - Waiver processing schedule and acquisition limits
    - Trade deadline and veto rules
    - Scoring categories and settings

    Args:
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        Dictionary with league settings including:
        - scheduleSettings: Week boundaries, matchup periods, playoff settings
        - rosterSettings: Lineup slots, position limits, lock times
        - acquisitionSettings: Waiver schedule, acquisition limits
        - tradeSettings: Trade deadline, veto rules
        - scoringSettings: Scoring categories and type
        - status: Current matchup period, scoring periods
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    settings = await client.get_league_settings()
    return settings.model_dump()


@mcp.tool()
async def get_team_roster(
    team_id: int | None = None,
    league_id: int | None = None,
    year: int | None = None,
    scoring_period: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> dict:
    """Get roster for a specific team in an ESPN Fantasy Basketball league.

    Args:
        team_id: Team ID to get roster for (optional, uses ESPN_TEAM_ID env var)
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        scoring_period: Specific scoring period (optional)
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        Dictionary with team roster including all players and their positions
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    team_id = _get_team_id(team_id)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    roster = await client.get_team_roster(team_id, scoring_period)
    return roster.model_dump()


@mcp.tool()
async def get_free_agents(
    league_id: int | None = None,
    year: int | None = None,
    size: int = 50,
    position_id: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> list[dict]:
    """Get free agents/waiver wire players from an ESPN Fantasy Basketball league.

    Args:
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        size: Number of players to return (max 50, default 50)
        position_id: Filter by position ID (optional)
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        List of available free agent player dictionaries
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    players = await client.get_free_agents(size, position_id)
    return [player.model_dump() for player in players]


@mcp.tool()
async def get_matchups(
    league_id: int | None = None,
    year: int | None = None,
    scoring_period: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> list[dict]:
    """Get matchups/schedule for an ESPN Fantasy Basketball league.

    Args:
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        scoring_period: Specific scoring period to get matchups for (optional)
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        List of matchup dictionaries with home/away teams and scores
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
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
    league_id: int | None = None,
    year: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> dict:
    """Get current draft status including all picks and progress.

    Args:
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        Dictionary with draft status, picks, and current state
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    draft_status = await client.get_draft_status()
    return draft_status.model_dump()


@mcp.tool()
async def should_i_bid(
    current_player_id: int,
    team_id: int | None = None,
    league_id: int | None = None,
    year: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> dict:
    """Get recommendation on whether to bid for the current player being nominated.

    Args:
        current_player_id: ID of player currently being nominated
        team_id: Your team ID (optional, uses ESPN_TEAM_ID env var)
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        Dictionary with bid recommendation, suggested amount, and reasoning
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    team_id = _get_team_id(team_id)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    recommendation = await client.get_draft_recommendation(team_id, current_player_id)
    return recommendation.model_dump()


@mcp.tool()
async def who_should_i_target_next(
    team_id: int | None = None,
    league_id: int | None = None,
    year: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> dict:
    """Get recommendation on which player to target/nominate next.

    Args:
        team_id: Your team ID (optional, uses ESPN_TEAM_ID env var)
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        Dictionary with player recommendation and reasoning
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    team_id = _get_team_id(team_id)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    recommendation = await client.get_draft_recommendation(team_id, None)
    return recommendation.model_dump()


@mcp.tool()
async def analyze_my_draft_strategy(
    team_id: int | None = None,
    league_id: int | None = None,
    year: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> dict:
    """Analyze your current draft strategy and spending patterns.

    Args:
        team_id: Your team ID (optional, uses ESPN_TEAM_ID env var)
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        Dictionary with punt strategy analysis, spending summary, and recommendations
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    team_id = _get_team_id(team_id)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)

    # Get team summary and strategy analysis
    team_summary = await client.get_team_draft_summary(team_id)
    punt_analysis = await client.analyze_punt_strategy(team_id)

    return {
        "team_summary": team_summary.model_dump(),
        "punt_analysis": punt_analysis,
        "budget_per_remaining_player": round(
            team_summary.remainingBudget / max(1, 13 - team_summary.playersCount), 2
        ),
    }


@mcp.tool()
async def get_available_players(
    league_id: int | None = None,
    year: int | None = None,
    limit: int = 50,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> list[dict]:
    """Get top available players for the draft with auction values.

    Args:
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        limit: Number of players to return (default 50)
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        List of available player dictionaries with auction values and rankings
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    players = await client.get_available_players(limit)
    return [player.model_dump() for player in players]


@mcp.tool()
async def get_player_stats(
    player_id: int,
    league_id: int | None = None,
    year: int | None = None,
    timeframe: str = "season",
    espn_s2: str | None = None,
    swid: str | None = None,
) -> dict:
    """Get comprehensive player statistics for specified timeframe.

    Args:
        player_id: ESPN player ID
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        timeframe: Time period - "season", "projections", "last_7", "last_30"
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        Dictionary with comprehensive player statistics across all categories
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    stats = await client.get_player_stats(player_id, timeframe)
    return stats.model_dump()


@mcp.tool()
async def compare_players(
    player_ids: list[int],
    league_id: int | None = None,
    year: int | None = None,
    categories: list[str] | None = None,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> dict:
    """Compare multiple players across statistical categories.

    Args:
        player_ids: List of ESPN player IDs to compare
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        categories: List of categories to compare (optional, defaults to 9-cat)
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        Dictionary with detailed player comparison and winner by category
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    comparison = await client.compare_players(player_ids, categories)
    return comparison.model_dump()


@mcp.tool()
async def analyze_trade_proposal(
    your_player_ids: list[int],
    their_player_ids: list[int],
    league_id: int | None = None,
    year: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> dict:
    """Analyze a trade proposal using comprehensive statistical analysis.

    Args:
        your_player_ids: List of player IDs you would trade away
        their_player_ids: List of player IDs you would receive
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        Dictionary with trade analysis, recommendation, and category impact
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    analysis = await client.analyze_trade_proposal(your_player_ids, their_player_ids)
    return analysis.model_dump()


@mcp.tool()
async def get_trending_players(
    league_id: int | None = None,
    year: int | None = None,
    direction: str = "up",
    limit: int = 20,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> list[dict]:
    """Get players trending up or down in adds/drops for waiver wire intelligence.

    Args:
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        direction: Trending direction - "up" or "down"
        limit: Number of players to return (default 20)
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        List of trending player dictionaries with add/drop percentages and reasons
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    trending = await client.get_trending_players(direction, limit)
    return [player.model_dump() for player in trending]


@mcp.tool()
async def get_roster_schedule(
    team_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    league_id: int | None = None,
    year: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> dict:
    """Get game schedule summary for all players on your fantasy roster.

    This helps you see how many games each of your players has in the upcoming week(s),
    which is crucial for setting your lineup and making roster decisions.

    Args:
        team_id: Your fantasy team ID (optional, uses ESPN_TEAM_ID env var)
        start_date: Start date in YYYY-MM-DD format (optional, defaults to today)
        end_date: End date in YYYY-MM-DD format (optional, defaults to 7 days from start)
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        Dictionary with schedule summary including games per player and total games
    """
    from datetime import datetime, timedelta

    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    team_id = _get_team_id(team_id)

    # Default dates if not provided
    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-%d")
    if not end_date:
        end_date = (datetime.fromisoformat(start_date) + timedelta(days=7)).strftime("%Y-%m-%d")

    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    schedule_summary = await client.get_roster_schedule_summary(team_id, start_date, end_date)
    return schedule_summary.model_dump()


if __name__ == "__main__":
    # Run the server
    mcp.run(transport="stdio")

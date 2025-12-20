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
async def get_team_season_stats(
    team_id: int | None = None,
    league_id: int | None = None,
    year: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> dict:
    """Get team statistics aggregated across the entire season.

    This aggregates stats from all matchups in the season for a specific team.

    Args:
        team_id: Team ID to get season stats for (optional, uses ESPN_TEAM_ID env var)
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        Dictionary with team season statistics including:
        - categoryScores: Season totals for each scoring category
        - componentStats: Component stats totals (FGM, FGA, FTM, FTA, etc.)
        - totalGamesPlayed: Total games played across all matchups
        - matchupWins: Number of matchup wins
        - matchupLosses: Number of matchup losses
        - matchupTies: Number of matchup ties
        - winPercentage: Win percentage (wins / (wins + losses + ties))
        - gamesBack: Games behind the league leader
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    team_id = _get_team_id(team_id)
    if team_id is None:
        raise ValueError("team_id is required. Provide it as a parameter or set ESPN_TEAM_ID environment variable.")
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    stats = await client.get_team_season_stats(team_id)
    return stats.model_dump()


@mcp.tool()
async def get_free_agents(
    league_id: int | None = None,
    year: int | None = None,
    size: int = 50,
    position_id: int | None = None,
    verbose: bool = False,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> list[dict]:
    """Get free agents/waiver wire players from an ESPN Fantasy Basketball league.

    Args:
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        size: Number of players to return (max 50, default 50)
        position_id: Filter by position ID (optional)
        verbose: If True, include full season stats and per-game averages.
                 If False, return only essential fields (id, name, position, ownership) (default False).
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        List of available free agent player dictionaries.
        When verbose=False, stats field will be None to reduce response size.
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    players = await client.get_free_agents(size, position_id, verbose)
    return [player.model_dump() for player in players]


@mcp.tool()
async def get_matchups(
    league_id: int | None = None,
    year: int | None = None,
    scoring_period: int | None = None,
    team_id: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> list[dict]:
    """Get matchups/schedule for an ESPN Fantasy Basketball league.

    Defaults to current scoring period and your team (from ESPN_TEAM_ID env var) if not specified.

    Args:
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        scoring_period: Specific scoring period to get matchups for (optional, defaults to current week)
        team_id: Filter to only return matchups for this team (optional, defaults to ESPN_TEAM_ID env var)
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        List of matchup dictionaries with home/away teams and scores.
        Category scores are provided in both numeric stat IDs (cumulativeScore) and
        human-readable names (categoryScores) for easier interpretation.
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    # Default to team_id from environment if not provided
    team_id = _get_team_id(team_id)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    
    # Convert scoring_period to int if it's a string (MCP client may pass strings)
    if scoring_period is not None:
        scoring_period = int(scoring_period) if isinstance(scoring_period, str) else scoring_period
    
    matchups = await client.get_matchups(scoring_period, team_id)
    return [matchup.model_dump() for matchup in matchups]


@mcp.tool()
async def get_my_current_matchup(
    team_id: int | None = None,
    league_id: int | None = None,
    year: int | None = None,
    verbose: bool = False,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> dict | None:
    """Get your current matchup with complete information in a single call.
    
    This combines multiple pieces of information:
    - Your team's roster for the current week
    - Opponent's roster for the current week
    - Current category scores (with human-readable names)
    - The week/scoring period
    
    This replaces the need for 3 separate calls (get_matchups, get_team_roster × 2).

    Args:
        team_id: Your team ID (optional, uses ESPN_TEAM_ID env var)
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        verbose: If True, include full player stats in rosters.
                 If False, omit player stats from rosters (keeps only lineup info like name, position, injury status) (default False).
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        Dictionary with complete matchup information including:
        - matchupId: Matchup ID
        - scoringPeriod: Current scoring period/week
        - yourTeam: Your team's matchup data (scores, games played)
        - opponentTeam: Opponent's matchup data (scores, games played)
        - yourRoster: Your team's roster for this week (stats omitted if verbose=False)
        - opponentRoster: Opponent's roster for this week (stats omitted if verbose=False)
        - winner: Winner determination (if available)
        - playoff: Whether this is a playoff matchup
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    team_id = _get_team_id(team_id)
    if not team_id:
        raise ValueError("team_id is required. Provide it as a parameter or set ESPN_TEAM_ID env var.")
    
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    matchup = await client.get_my_current_matchup(team_id, verbose)
    
    if matchup is None:
        return None
    
    return matchup.model_dump()


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
    player_id: int | list[int],
    league_id: int | None = None,
    year: int | None = None,
    timeframe: str = "season",
    espn_s2: str | None = None,
    swid: str | None = None,
) -> dict | list[dict]:
    """Get comprehensive player statistics for one or more players.
    
    Can be called with a single player ID (returns dict) or a list of player IDs 
    (returns list[dict]). Using a list is more efficient as it makes a single 
    API request for all players.

    Args:
        player_id: ESPN player ID (int) or list of player IDs (list[int])
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        timeframe: Time period - "season", "projections", "last_7", "last_30"
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        Dictionary with player statistics if single ID provided, 
        list of dictionaries if list provided
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    stats = await client.get_player_stats(player_id, timeframe)
    
    # Return single dict or list of dicts based on input type
    if isinstance(player_id, int):
        return stats.model_dump()
    else:
        return [s.model_dump() for s in stats]


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
    scoring_period: int | None = None,
    league_id: int | None = None,
    year: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> dict:
    """Get game schedule summary for all players on your fantasy roster.

    This helps you see how many games each of your players has in the upcoming week(s),
    which is crucial for setting your lineup and making roster decisions.
    
    Uses league settings to properly calculate week boundaries (Monday-to-Sunday)
    and map scoring periods to dates for accurate game counts.

    Args:
        team_id: Your fantasy team ID (optional, uses ESPN_TEAM_ID env var)
        start_date: Start date in YYYY-MM-DD format (optional, defaults to today)
        end_date: End date in YYYY-MM-DD format (optional, defaults to 7 days from start)
        scoring_period: Specific scoring period to get schedule for (optional)
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: Season year (e.g., 2025) (optional, uses ESPN_YEAR env var or defaults to 2025)
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        Dictionary with schedule summary including:
        - gamesThisWeek: Games in current week (Monday-Sunday)
        - gamesNextWeek: Games in next week (Monday-Sunday)
        - games per player with dates and opponents
        - scoringPeriod: The scoring period this schedule represents
    """
    from datetime import datetime, timedelta

    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    team_id = _get_team_id(team_id)
    if not team_id:
        raise ValueError("team_id is required. Provide it as a parameter or set ESPN_TEAM_ID env var.")

    # Default dates if not provided
    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-%d")
    if not end_date:
        end_date = (datetime.fromisoformat(start_date) + timedelta(days=7)).strftime("%Y-%m-%d")

    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    schedule_summary = await client.get_roster_schedule_summary(
        team_id, start_date, end_date, scoring_period
    )
    return schedule_summary.model_dump()


if __name__ == "__main__":
    # Run the server
    mcp.run(transport="stdio")

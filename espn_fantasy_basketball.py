#!/usr/bin/env python3
"""ESPN Fantasy Basketball MCP Server using FastMCP."""

import logging
import os
from datetime import date
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("espn-fantasy-basketball-mcp")

# Create the FastMCP server
mcp = FastMCP("ESPN Fantasy Basketball")

# Fields that duplicate named ones and are left out of every tool's output: the raw stat-ID
# block on a matchup side (categoryScores, componentStats and categoryWins/Losses/Ties carry
# the same data by name).
_MATCHUP_SIDE_EXCLUDE = {"cumulativeScore": True}
_MATCHUP_EXCLUDE = {"home": _MATCHUP_SIDE_EXCLUDE, "away": _MATCHUP_SIDE_EXCLUDE}
_CURRENT_MATCHUP_EXCLUDE = {
    "yourTeam": _MATCHUP_SIDE_EXCLUDE,
    "opponentTeam": _MATCHUP_SIDE_EXCLUDE,
}


def _dump(model: BaseModel, exclude: dict[str, Any] | None = None) -> dict[str, Any]:
    """Serialise a model for the MCP response without null fields.

    Every optional field that ESPN did not populate (jersey, ownership on a roster view, ...)
    would otherwise be sent as null on every player, which roughly doubled response sizes.
    A field that is absent means "not available", exactly as null did.
    """
    return model.model_dump(exclude_none=True, exclude=exclude)


def _default_season(today: date | None = None) -> int:
    """Return the ESPN season ID for the NBA season in progress (or next up).

    ESPN labels a season by the calendar year it *ends* in: the 2026-27 season is 2027.
    The regular season tips off in October, so October through December map to the
    following year and January through September map to the current year.

    During September draft prep for a new season, set ESPN_YEAR explicitly.

    Args:
        today: Date to evaluate (defaults to today; injectable for tests)
    """
    today = today or date.today()
    return today.year + 1 if today.month >= 10 else today.year


def _get_espn_credentials(
    league_id: int | None = None,
    year: int | None = None,
) -> tuple[int, int, str | None, str | None]:
    """Resolve league, season and ESPN cookies for a tool call.

    The league ID and season may be passed as tool parameters, with ESPN_LEAGUE_ID and
    ESPN_YEAR as fallbacks. The cookies are read from ESPN_S2 and ESPN_SWID only: they grant
    full access to the owner's ESPN account, and accepting them as tool parameters would put
    them into the conversation transcript, so no tool exposes them in its schema.

    Args:
        league_id: League ID parameter (optional)
        year: Year parameter (optional)

    Returns:
        Tuple of (league_id, year, espn_s2, swid)
    """
    final_league_id = league_id or int(os.getenv("ESPN_LEAGUE_ID", "0"))
    final_year = year or int(os.getenv("ESPN_YEAR") or _default_season())
    espn_s2 = os.getenv("ESPN_S2") or None
    swid = os.getenv("ESPN_SWID") or None
    return final_league_id, final_year, espn_s2, swid


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
) -> list[dict]:
    """Get all teams in an ESPN Fantasy Basketball league.

    Args:
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)

    Returns:
        List of team dictionaries in standings order (standingsRank 1 = first; ESPN's own
        playoffSeed is alongside). isMyTeam is true for the team ESPN_TEAM_ID points at.
        `record` is ESPN's record: recordType / recordDescription say whether it counts
        categories (H2H Each Category, where ESPN's standings are category totals) or
        matchups. matchupRecord is the matchup-level W-L-T derived from decided schedule
        results, with completedMatchupPeriods saying how many it covers. waiverRank is the
        team's place in the waiver order (1 = first claim), and acquisitionsThisMatchup /
        acquisitionLimitThisMatchup / acquisitionsRemainingThisMatchup show adds used against
        the effective per-matchup limit; matchupAcquisitionTotalsNote explains an entry for a
        period that has not started.
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    teams = await client.get_league_teams(my_team_id=_get_team_id())
    return [_dump(team) for team in teams]


@mcp.tool()
async def get_league_settings(
    league_id: int | None = None,
    year: int | None = None,
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
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)

    Returns:
        Dictionary with league settings including:
        - scheduleSettings: Week boundaries, matchup periods, playoff settings
        - rosterSettings: Lineup slots, position limits, lock times
        - acquisitionSettings: Waiver schedule, acquisition limits, acquisitionLimitDescription
          ("1 per day, so 7 for matchup period 2 (7 days)"), effectiveLimitByMatchupPeriod (a
          per-day limit times the days in each period), waiverOrderReset / waiverOrderDescription
        - tradeSettings: Trade deadline, veto rules
        - scoringSettings: Scoring categories and type
        - status: currentMatchupPeriod (a week) with currentMatchupPeriodDates, and
          latestScoringPeriod (a day counter; 1 = opening night) with latestScoringPeriodDate

        scheduleSettings.matchupPeriodDates is the authoritative period -> [first_day, last_day]
        mapping; the raw matchupPeriods is week-indexed and should not be read as days.
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    settings = await client.get_league_settings()
    return _dump(settings)


@mcp.tool()
async def get_team_roster(
    team_id: int | None = None,
    league_id: int | None = None,
    year: int | None = None,
    scoring_period: int | None = None,
) -> dict:
    """Get roster for a specific team in an ESPN Fantasy Basketball league.

    Args:
        team_id: Team ID to get roster for (optional, uses ESPN_TEAM_ID env var)
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)
        scoring_period: Specific scoring period, i.e. a day index where 1 is opening night
            (optional; omit for today's roster). The response says which period and date it
            is for (scoringPeriodId / scoringPeriodDate) and whether that lineup is locked;
            use scoringPeriodId + 1 for tomorrow's editable lineup. When omitted, players ESPN
            still lists but who were dropped (onTeamId no longer this team) are removed and
            named in staleEntriesRemoved; a historical day is returned exactly as stored.

    Returns:
        Dictionary with team roster including all players, positions, per-game stats
        (gamesPlayed is null when ESPN does not report it; fg_pct/ft_pct are null exactly when
        fga/fta is 0), injury status plus injuryDetails / injuryReturnDate when ESPN
        publishes a reason, today's game, and per-slot lock state for that scoring period
        (each entry's lineupLocked, plus lockedSlots / unlockedSlots lists)
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    team_id = _get_team_id(team_id)
    if team_id is None:
        raise ValueError(
            "team_id is required. Provide it as a parameter or set ESPN_TEAM_ID environment variable."
        )
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    roster = await client.get_team_roster(team_id, scoring_period)
    return _dump(roster)


@mcp.tool()
async def get_team_season_stats(
    team_id: int | None = None,
    league_id: int | None = None,
    year: int | None = None,
) -> dict:
    """Get team statistics aggregated across the entire season.

    This aggregates stats from all matchups in the season for a specific team.

    Args:
        team_id: Team ID to get season stats for (optional, uses ESPN_TEAM_ID env var)
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)

    Returns:
        Dictionary with team season statistics including:
        - categoryScores: Season totals for each scoring category
        - componentStats: Component stats totals (FGM, FGA, FTM, FTA, etc.)
        - matchupWins / matchupLosses / matchupTies: one result per completed matchup period,
          from the schedule's decided results (never category tallies);
          completedMatchupPeriods says how many periods they cover
        - espnRecord with espnRecordType / espnRecordDescription: ESPN's own record, which in
          an H2H Each Category league counts categories and is what the standings use
        - winPercentage: Win percentage (wins / (wins + losses), excludes ties)
        - gamesBack: Games behind the leader on the matchup record (gamesBackDescription)
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    team_id = _get_team_id(team_id)
    if team_id is None:
        raise ValueError(
            "team_id is required. Provide it as a parameter or set ESPN_TEAM_ID environment variable."
        )
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    stats = await client.get_team_season_stats(team_id)
    return _dump(stats)


@mcp.tool()
async def get_free_agents(
    league_id: int | None = None,
    year: int | None = None,
    size: int = 50,
    position_id: int | None = None,
    verbose: bool = False,
) -> list[dict]:
    """Get free agents/waiver wire players from an ESPN Fantasy Basketball league.

    Args:
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)
        size: Number of players to return (max 50, default 50)
        position_id: Filter by position ID (optional)
        verbose: If True, include full season stats and per-game averages.
                 If False, return only essential fields (id, name, position, ownership) (default False).

    Returns:
        List of available free agent player dictionaries. availabilityStatus is FREEAGENT (can
        be added now) or WAIVERS (claims process at waiverProcessDateISO; ESPN's "WA" flag),
        with a plain-English availabilityNote. When verbose=False, stats is None.
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    players = await client.get_free_agents(size, position_id, verbose)
    return [_dump(player) for player in players]


@mcp.tool()
async def get_transactions(
    limit: int = 25,
    scoring_period: int | None = None,
    team_id: int | None = None,
    include_lineup_changes: bool = False,
    league_id: int | None = None,
    year: int | None = None,
) -> list[dict]:
    """Recent league transactions: adds, drops, waiver claims and trades, newest first.

    Use it to answer "why is this player on waivers" (who dropped him and when), "what did my
    opponent change this week", or to see pending waiver claims.

    Args:
        limit: Maximum transactions to return (1-200, default 25)
        scoring_period: Only one scoring period (day; 1 = opening night) (optional)
        team_id: Only transactions by, or moving a player to/from, this team (optional; NOT
            defaulted from ESPN_TEAM_ID, so the whole league is returned unless you pass one)
        include_lineup_changes: Also return plain lineup saves (ESPN logs every one as a
            ROSTER / FUTURE_ROSTER transaction); off by default to keep the log readable
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)

    Returns:
        List of transactions with type, status (EXECUTED / PENDING / ...), team, dates, the
        players moved (ADD / DROP with names) and a one-line summary.
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    transactions = await client.get_transactions(
        int(limit), scoring_period, team_id, include_lineup_changes
    )
    return [_dump(t) for t in transactions]


@mcp.tool()
async def get_matchups(
    league_id: int | None = None,
    year: int | None = None,
    matchup_period: int | None = None,
    team_id: int | None = None,
) -> list[dict]:
    """Get matchups/schedule for an ESPN Fantasy Basketball league.

    Defaults to the current matchup period and your team (from ESPN_TEAM_ID env var) if not specified.

    Args:
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)
        matchup_period: Matchup period (week) to get matchups for (optional, defaults to the current one).
            Use get_league_settings -> status.currentMatchupPeriod for the current week.
        team_id: Filter to only return matchups for this team (optional, defaults to ESPN_TEAM_ID env var)

    Returns:
        List of matchup dictionaries with home/away teams and scores.
        Category scores are provided in both numeric stat IDs (cumulativeScore) and
        human-readable names (categoryScores) for easier interpretation.
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    # Default to team_id from environment if not provided
    team_id = _get_team_id(team_id)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)

    # Convert matchup_period to int if it's a string (MCP client may pass strings)
    if matchup_period is not None:
        matchup_period = int(matchup_period) if isinstance(matchup_period, str) else matchup_period

    matchups = await client.get_matchups(matchup_period, team_id)
    return [_dump(matchup, _MATCHUP_EXCLUDE) for matchup in matchups]


@mcp.tool()
async def get_my_current_matchup(
    team_id: int | None = None,
    league_id: int | None = None,
    year: int | None = None,
    verbose: bool = False,
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
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)
        verbose: If True, include season totals in each player's stats as well.
                 If False (default), rosters still carry per-game averages (points, rebounds,
                 assists, ..., gamesPlayed), injury status/details and today's game; only the
                 season totals block is omitted.

    Returns:
        Dictionary with complete matchup information including:
        - matchupId: Matchup ID
        - scoringPeriod: Current scoring period/week
        - yourTeam: Your team's matchup data (scores, games played)
        - opponentTeam: Opponent's matchup data (scores, games played)
        - yourRoster: Your team's roster today, with per-game averages (season totals only if verbose=True)
        - opponentRoster: Opponent's roster today, same shape
        - yourTeam.categoryWins/Losses/Ties: categories led, trailed and tied so far this week
        - A roster's note says when today's lineup is locked; the next day's lineup is read
          with get_team_roster(scoring_period=...), which this tool does not take
        - staleEntriesRemoved (per roster): players ESPN still listed but who were dropped
        - winner: Winner determination (if available)
        - playoff: Whether this is a playoff matchup
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    team_id = _get_team_id(team_id)
    if not team_id:
        raise ValueError(
            "team_id is required. Provide it as a parameter or set ESPN_TEAM_ID env var."
        )

    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    matchup = await client.get_my_current_matchup(team_id, verbose)

    if matchup is None:
        return None

    return _dump(matchup, _CURRENT_MATCHUP_EXCLUDE)


@mcp.tool()
async def get_nba_schedule(date: str | None = None) -> list[dict]:
    """Get NBA schedule for a specific date.

    Args:
        date: Date in YYYY-MM-DD format (optional, defaults to today)

    Returns:
        List of NBA game dictionaries with teams, times, and details
    """
    # Create a temporary client just for NBA API access
    # Dummy league ID; the NBA schedule endpoint does not use league or season
    client = ESPNFantasyBasketballClient(1, _default_season())
    games = await client.get_nba_schedule(date)
    return [_dump(game) for game in games]


@mcp.tool()
async def get_draft_status(
    league_id: int | None = None,
    year: int | None = None,
) -> dict:
    """Get current draft status including all picks and progress.

    Args:
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)

    Returns:
        Dictionary with draft status, picks, and current state
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    draft_status = await client.get_draft_status()
    return _dump(draft_status)


@mcp.tool()
async def should_i_bid(
    current_player_id: int,
    team_id: int | None = None,
    league_id: int | None = None,
    year: int | None = None,
) -> dict:
    """Get recommendation on whether to bid for the current player being nominated.

    Args:
        current_player_id: ID of player currently being nominated
        team_id: Your team ID (optional, uses ESPN_TEAM_ID env var)
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)

    Returns:
        Dictionary with bid recommendation, suggested amount, and reasoning
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    team_id = _get_team_id(team_id)
    if team_id is None:
        raise ValueError(
            "team_id is required. Provide it as a parameter or set ESPN_TEAM_ID environment variable."
        )
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    recommendation = await client.get_draft_recommendation(team_id, current_player_id)
    return _dump(recommendation)


@mcp.tool()
async def who_should_i_target_next(
    team_id: int | None = None,
    league_id: int | None = None,
    year: int | None = None,
) -> dict:
    """Get recommendation on which player to target/nominate next.

    Args:
        team_id: Your team ID (optional, uses ESPN_TEAM_ID env var)
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)

    Returns:
        Dictionary with player recommendation and reasoning
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    team_id = _get_team_id(team_id)
    if team_id is None:
        raise ValueError(
            "team_id is required. Provide it as a parameter or set ESPN_TEAM_ID environment variable."
        )
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    recommendation = await client.get_draft_recommendation(team_id, None)
    return _dump(recommendation)


@mcp.tool()
async def analyze_my_draft_strategy(
    team_id: int | None = None,
    league_id: int | None = None,
    year: int | None = None,
) -> dict:
    """Analyze your current draft strategy and spending patterns.

    Args:
        team_id: Your team ID (optional, uses ESPN_TEAM_ID env var)
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)

    Returns:
        Dictionary with punt strategy analysis, spending summary, and recommendations
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    team_id = _get_team_id(team_id)
    if team_id is None:
        raise ValueError(
            "team_id is required. Provide it as a parameter or set ESPN_TEAM_ID environment variable."
        )
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)

    # Get team summary and strategy analysis
    team_summary = await client.get_team_draft_summary(team_id)
    punt_analysis = await client.analyze_punt_strategy(team_id)

    remaining_slots = team_summary.remainingSlots
    if remaining_slots is None:
        remaining_slots = max(0, team_summary.rosterSize - team_summary.playersCount)

    return {
        "team_summary": _dump(team_summary),
        "punt_analysis": punt_analysis,
        "budget_per_remaining_player": round(
            team_summary.remainingBudget / max(1, remaining_slots), 2
        ),
    }


@mcp.tool()
async def get_available_players(
    league_id: int | None = None,
    year: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """Get top available players for the draft with auction values.

    Args:
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)
        limit: Number of players to return (default 50)

    Returns:
        List of available player dictionaries with auction values and rankings
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    players = await client.get_available_players(limit)
    return [_dump(player) for player in players]


@mcp.tool()
async def get_player_stats(
    player_id: int | list[int],
    league_id: int | None = None,
    year: int | None = None,
    timeframe: str = "season",
) -> dict | list[dict]:
    """Get comprehensive player statistics for one or more players.

    Can be called with a single player ID (returns dict) or a list of player IDs
    (returns list[dict]). Using a list is more efficient as it makes a single
    API request for all players.

    Args:
        player_id: ESPN player ID (int) or list of player IDs (list[int])
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)
        timeframe: Time period - "season", "projections", "last_7", "last_30"

    Returns:
        Dictionary with player statistics if single ID provided,
        list of dictionaries if list provided
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)

    # Return single dict or list of dicts based on input type
    if isinstance(player_id, int):
        stats = await client.get_player_stats(player_id, timeframe)
        return _dump(stats)
    stats_list = await client.get_player_stats(player_id, timeframe)
    return [_dump(s) for s in stats_list]


@mcp.tool()
async def compare_players(
    player_ids: list[int],
    league_id: int | None = None,
    year: int | None = None,
    categories: list[str] | None = None,
) -> dict:
    """Compare multiple players across statistical categories.

    Args:
        player_ids: List of ESPN player IDs to compare
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)
        categories: List of categories to compare (optional, defaults to 9-cat)

    Returns:
        Dictionary with detailed player comparison and winner by category
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    comparison = await client.compare_players(player_ids, categories)
    return _dump(comparison)


@mcp.tool()
async def analyze_trade_proposal(
    your_player_ids: list[int],
    their_player_ids: list[int],
    league_id: int | None = None,
    year: int | None = None,
) -> dict:
    """Analyze a trade proposal using comprehensive statistical analysis.

    Args:
        your_player_ids: List of player IDs you would trade away
        their_player_ids: List of player IDs you would receive
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)

    Returns:
        Dictionary with trade analysis, recommendation, and category impact
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    analysis = await client.analyze_trade_proposal(your_player_ids, their_player_ids)
    return _dump(analysis)


@mcp.tool()
async def get_trending_players(
    league_id: int | None = None,
    year: int | None = None,
    direction: str = "up",
    limit: int = 20,
) -> list[dict]:
    """Get players trending up or down in adds/drops for waiver wire intelligence.

    Args:
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)
        direction: Trending direction - "up" or "down"
        limit: Number of players to return (default 20)

    Returns:
        List of trending player dictionaries with add/drop percentages and reasons
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    trending = await client.get_trending_players(direction, limit)
    return [_dump(player) for player in trending]


@mcp.tool()
async def get_roster_schedule(
    team_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    matchup_period: int | None = None,
    player_ids: list[int] | None = None,
    league_id: int | None = None,
    year: int | None = None,
) -> dict:
    """Get game schedule summary for all players on your fantasy roster.

    This helps you see how many games each of your players has in the upcoming week(s),
    which is crucial for setting your lineup and making roster decisions.

    When matchup_period is given, "this week" and "next week" are that matchup period and
    the next one, using the league's own period-to-date mapping (so a short opening week or
    a two-week All-Star period is handled). Otherwise they are the Monday-to-Sunday week
    containing start_date and the week after. The windows used are returned as
    thisWeek / nextWeek.

    Pass player_ids to list streaming candidates (free agents or other teams' players) next
    to your roster; they are marked includedInTotals=False and left out of the team totals.
    For candidates only, use get_player_schedule.

    Args:
        team_id: Your fantasy team ID (optional, uses ESPN_TEAM_ID env var)
        start_date: Start date in YYYY-MM-DD format (optional, defaults to today)
        end_date: End date in YYYY-MM-DD format (optional, defaults to 7 days from start)
        matchup_period: Matchup period (week) to summarize (optional; overrides the dates).
            Use get_league_settings -> status.currentMatchupPeriod for the current week.
        player_ids: Extra ESPN player IDs to include for comparison (optional; use
            search_players to find IDs)
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)

    Returns:
        Dictionary with schedule summary including:
        - thisWeek / nextWeek: the [first_day, last_day] windows counted
        - gamesThisWeek / gamesNextWeek per player, with dates, opponents, and tip-off times
        - totalGamesThisWeek / totalGamesNextWeek / averageGamesPerPlayer over rostered players
        - scoringPeriod: The matchup period this schedule represents
    """
    from datetime import datetime, timedelta

    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    team_id = _get_team_id(team_id)
    if not team_id:
        raise ValueError(
            "team_id is required. Provide it as a parameter or set ESPN_TEAM_ID env var."
        )

    # Default dates if not provided
    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-%d")
    if not end_date:
        end_date = (datetime.fromisoformat(start_date) + timedelta(days=7)).strftime("%Y-%m-%d")

    extra_ids = _coerce_player_ids(player_ids) if player_ids else None

    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    schedule_summary = await client.get_roster_schedule_summary(
        team_id, start_date, end_date, matchup_period, extra_player_ids=extra_ids
    )
    return _dump(schedule_summary)


def _coerce_player_ids(player_ids: list) -> list[int]:
    """MCP clients sometimes send numbers as strings; accept both, reject anything else."""
    coerced: list[int] = []
    for pid in player_ids:
        try:
            coerced.append(int(pid))
        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid player ID {pid!r}: must be an integer") from e
    return coerced


@mcp.tool()
async def get_player_schedule(
    player_ids: list[int],
    matchup_period: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    league_id: int | None = None,
    year: int | None = None,
) -> dict:
    """How many games specific players have this matchup period and next, by ESPN player ID.

    Use this for streaming candidates and trade targets who are not on your roster: it
    answers "how many games does this free agent have left this week" directly instead of
    inferring from other teams' players. Find IDs with search_players.

    Windows work like get_roster_schedule: with matchup_period, "this week" is that matchup
    period and "next week" the following one (league's own period dates); otherwise the
    Monday-to-Sunday week containing start_date and the week after.

    Args:
        player_ids: ESPN player IDs (1-50). Unknown IDs are listed with a note and zero games.
        matchup_period: Matchup period (week) to count (optional; overrides the dates).
            Use get_league_settings -> status.currentMatchupPeriod for the current week.
        start_date: Start date in YYYY-MM-DD format (optional, defaults to today)
        end_date: End date in YYYY-MM-DD format (optional, defaults to 7 days from start)
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)

    Returns:
        Dictionary with thisWeek / nextWeek windows, per-player games (dates, opponents,
        tip-off times, gamesThisWeek, gamesNextWeek) and totals over the listed players.
        teamId is null because this is not a roster.
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    if not player_ids:
        raise ValueError("player_ids is required (one or more ESPN player IDs)")
    ids = _coerce_player_ids(player_ids)
    if matchup_period is not None:
        matchup_period = int(matchup_period) if isinstance(matchup_period, str) else matchup_period

    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    summary = await client.get_players_schedule_summary(ids, start_date, end_date, matchup_period)
    return _dump(summary)


@mcp.tool()
async def analyze_matchup(
    team_id: int | None = None,
    matchup_period: int | None = None,
    league_id: int | None = None,
    year: int | None = None,
) -> dict:
    """Analyze a matchup and provide strategic recommendations.

    By default, analyzes your next matchup (current week + 1). Can also analyze
    any other matchup period by specifying matchup_period.

    This provides comprehensive analysis including:
    - Category win/loss projections based on games remaining and player stats
    - Close categories where lineup decisions matter most
    - Player recommendations prioritized by which categories you need
    - Games remaining analysis for both teams
    - Strategic notes and recommendations

    Args:
        team_id: Your team ID (optional, uses ESPN_TEAM_ID env var)
        matchup_period: Matchup period to analyze (optional, defaults to next matchup).
                       Use None for next matchup, or specify a period number (e.g., 1, 2, 3...)
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)

    Returns:
        Dictionary with comprehensive matchup analysis including:
        - categoryProjections: Projections for each category with current/projected scores
        - categoriesWinning: Categories you're projected to win
        - categoriesLosing: Categories you're projected to lose
        - closeCategories: Categories that are close; each projection carries the
          closeThreshold used and a closenessRule explaining it (per-category margins for
          counting stats, made-shot equivalents for percentages)
        - playerRecommendations: Players to start, sorted by priority. Priority is driven by
          close categories (closeCategoriesHelped / closeCategoriesHurt); hurting a category
          already projected lost by a wide margin is not penalised. Each reasoning carries the
          per-game numbers behind it.
        - projectionMethod: how the projections are built (ESPN projected per-game averages x
          expected remaining games; OUT players contribute nothing; no confidence range)
        - yourGamesRemaining / yourExpectedGames and expectedGamesBreakdown: scheduled games
          not yet played, the availability-discounted figure, and one line per discounted
          player explaining the gap (same for the opponent)
        - opponentPlayers: the opponent's roster as the projection sees it (games remaining,
          availability, injury detail, projected per-game numbers)
        - currentCategoryWins/Losses/Ties: Current category record
        - projectedCategoryWins/Losses: Projected category record
        - strategyNotes: Strategic recommendations
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    team_id = _get_team_id(team_id)
    if team_id is None:
        raise ValueError(
            "team_id is required. Provide it as a parameter or set ESPN_TEAM_ID environment variable."
        )

    # Convert matchup_period to int if it's a string (MCP client may pass strings)
    if matchup_period is not None:
        matchup_period = int(matchup_period) if isinstance(matchup_period, str) else matchup_period

    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    analysis = await client.analyze_matchup(team_id, matchup_period)
    return _dump(analysis)


@mcp.tool()
async def search_players(
    query: str,
    limit: int = 5,
    include_league_status: bool = True,
    league_id: int | None = None,
    year: int | None = None,
) -> list[dict]:
    """Find ESPN player IDs by name. Use this before any tool that needs a player_id.

    Matching is forgiving: last name only ("Jokic"), partial first names ("steph curry"),
    accents ("Dončić"), and small typos all work. Results are sorted best match first.

    Args:
        query: Player name or part of one
        limit: Maximum number of matches to return (1-25, default 5)
        include_league_status: Also report whether each match is a free agent in your league
            or which fantasy team owns them (default True; costs one extra request)
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (e.g., 2027 for 2026-27) (optional, uses ESPN_YEAR env var or defaults to the current season)

    Returns:
        List of matches with playerId, fullName, matchScore (1.0 = exact), defaultPosition,
        proTeamAbbrev ("FA" if unsigned), injuryStatus, and when include_league_status is set:
        isFreeAgent, fantasyTeamId, fantasyTeamName, percentOwned.
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    results = await client.search_players(query, limit, include_league_status)
    return [_dump(r) for r in results]


if __name__ == "__main__":
    # Run the server
    mcp.run(transport="stdio")

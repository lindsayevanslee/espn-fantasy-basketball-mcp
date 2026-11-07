"""Matchup analysis: category projections, start/sit priorities and lineup warnings."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .constants import (
    AVAILABILITY_FACTORS,
    CATEGORY_HELP_THRESHOLDS,
    CLOSE_MARGINS,
    CLOSE_PERCENTAGE_FALLBACK,
    CLOSE_PERCENTAGE_MAKES,
    HURTS_RATIO,
    LINEUP_SLOT_NAMES,
    SHOOTING_THRESHOLDS,
    SLOT_BENCH,
    SLOT_IR,
    STAT_ID_TO_CATEGORY,
    TURNOVER_HELPS_BELOW,
    TURNOVER_HURTS_ABOVE,
)
from .dates import games_remaining_by_player
from .models import (
    CategoryProjection,
    MatchupAnalysis,
    OpponentPlayerSummary,
    PlayerRecommendation,
    PlayerStats,
    Roster,
    RosterEntry,
)

if TYPE_CHECKING:
    from .client import ESPNFantasyBasketballClient

logger = logging.getLogger(__name__)


def player_availability(entry: RosterEntry) -> tuple[str, float]:
    """Classify how available a rostered player is for the remaining games.

    Returns a (label, factor) pair. The factor scales the player's remaining games in
    projections: 1.0 for healthy and day-to-day players, 0.5 for doubtful, 0.0 for players
    who cannot score (OUT, suspended, in the IR slot, or unsigned/"FA").
    """
    player = entry.playerPoolEntry.player
    if player.proTeamAbbrev == "FA" or player.proTeamId == 0:
        return "FA", 0.0
    if entry.lineupSlotId == SLOT_IR:
        return "IR", 0.0
    status = (entry.injuryStatus or player.injuryStatus or "ACTIVE").upper()
    label = "SUSPENDED" if status == "SUSPENSION" else status
    return label, AVAILABILITY_FACTORS.get(status, 1.0)


def category_close_threshold(
    category: str, is_percentage: bool, your_current: float, attempts: float | None
) -> tuple[float, str]:
    """How small a projected margin must be for `category` to count as close, and why.

    Counting categories use a per-category margin (CLOSE_MARGINS: roughly what two strong
    player-games swing), so blocks at 0.4 and points at 0.4 are not judged on one scale.
    Percentage categories are judged in made shots: the lead is close when it is worth no more
    than CLOSE_PERCENTAGE_MAKES makes over the week's projected attempts, which is what a
    reader means by "one basket decides it".
    """
    if is_percentage:
        if attempts and attempts > 0:
            threshold = CLOSE_PERCENTAGE_MAKES / attempts
            return threshold, (
                f"lead worth at most {CLOSE_PERCENTAGE_MAKES:g} made shots over about "
                f"{attempts:.0f} projected attempts (margin <= {threshold:.4f})"
            )
        threshold = CLOSE_PERCENTAGE_FALLBACK.get(category, 0.01)
        return threshold, f"margin <= {threshold} (projected attempts unknown)"
    if category in CLOSE_MARGINS:
        threshold = CLOSE_MARGINS[category]
        return threshold, f"margin <= {threshold:g} (about two strong player-games)"
    threshold = max(abs(your_current) * 0.05, 2.0)
    return threshold, f"margin <= {threshold:g} (5% of the current total, minimum 2)"


def category_verdict(category: str, value: float) -> tuple[str, str] | None:
    """Does a per-game value help or hurt a category? Returns ("helps"|"hurts", display) or
    None when it is unremarkable. The display carries the number so the claim is checkable."""
    if category == "turnovers":
        display = f"{category} ({value:.1f}/g)"
        if value <= TURNOVER_HELPS_BELOW:
            return "helps", display
        if value >= TURNOVER_HURTS_ABOVE:
            return "hurts", display
        return None
    if category in SHOOTING_THRESHOLDS:
        # PlayerStats stores percentages on a 0-100 scale (e.g. 47.8); tolerate a fraction.
        pct = value * 100.0 if value <= 1.0 else value
        good, poor = SHOOTING_THRESHOLDS[category]
        display = f"{category} ({pct:.1f}%)"
        if pct >= good:
            return "helps", display
        if pct < poor:
            return "hurts", display
        return None
    threshold = CATEGORY_HELP_THRESHOLDS.get(category, 5.0)
    display = f"{category} ({value:.1f}/g)"
    if value >= threshold:
        return "helps", display
    if value < threshold * HURTS_RATIO:
        return "hurts", display
    return None


def expected_games_breakdown(
    roster: Roster,
    games_left: dict[int, int],
    availability: dict[int, tuple[str, float]],
) -> list[str]:
    """One line per player whose remaining games are discounted, plus the arithmetic."""
    lines: list[str] = []
    scheduled = 0
    expected = 0.0
    for entry in roster.entries:
        games = games_left.get(entry.playerId, 0)
        label, factor = availability.get(entry.playerId, ("ACTIVE", 1.0))
        scheduled += games
        expected += games * factor
        if games > 0 and factor < 1.0:
            player = entry.playerPoolEntry.player
            detail = f"; {player.injuryDetails}" if player.injuryDetails else ""
            lines.append(
                f"{player.fullName}: {games} scheduled, {games * factor:g} expected "
                f"({label}{detail})"
            )
    if lines:
        lines.append(
            f"{scheduled} scheduled - {scheduled - expected:g} discounted = {expected:g} expected"
        )
    return lines


def projection_method(end_date: str) -> str:
    """Spell out how the projections are built, so the reader can weigh them."""
    return (
        "Projected total = current matchup total + sum over rostered players of (ESPN's "
        "projected per-game average x expected remaining games). Expected games are the "
        f"player's scheduled games from now through {end_date} multiplied by an availability "
        "factor: OUT, suspended, in the IR slot or unsigned = 0; DOUBTFUL = 0.5; everything "
        "else = 1. A player listed OUT contributes nothing even if his expected return date "
        "falls inside the window. FG% and FT% are projected as made/attempted. The per-game "
        "averages are ESPN's season projections (get_player_stats timeframe 'projections'), "
        "not recent form, and no confidence range is given: early-season numbers are noisy."
    )


async def analyze_matchup(
    client: ESPNFantasyBasketballClient, team_id: int, matchup_period: int | None = None
) -> MatchupAnalysis:
    """Analyze a matchup and provide strategic recommendations.

    By default, analyzes the next matchup (current + 1). Can also analyze
    any other matchup period by specifying matchup_period.

    This provides comprehensive analysis including:
    - Category win/loss projections
    - Close categories where decisions matter
    - Player recommendations based on category needs
    - Games remaining analysis

    Args:
        team_id: Your team ID
        matchup_period: Matchup period to analyze (defaults to next matchup).
                      Use None for next matchup, or specify a period number (e.g., 1, 2, 3...)

    Returns:
        MatchupAnalysis object with detailed matchup analysis

    Raises:
        ValueError: If team_id is invalid or no matchup found
    """
    # Determine which matchup period to analyze
    league_settings = await client.get_league_settings()
    current_matchup_period = league_settings.status.currentMatchupPeriod

    if matchup_period is None:
        # Default to next matchup
        target_matchup_period = current_matchup_period + 1
    else:
        target_matchup_period = matchup_period

    # Get matchup data for the specified period, passing league_settings to avoid duplicate call
    matchup = await client.get_matchup_for_period(
        team_id, target_matchup_period, verbose=True, league_settings=league_settings
    )
    if not matchup:
        period_desc = "next" if matchup_period is None else f"period {matchup_period}"
        raise ValueError(f"No matchup found for team {team_id} in {period_desc} matchup")

    # Use league settings already fetched
    scoring_stat_ids = client._get_scoring_stat_ids(league_settings)
    stat_mapping = dict(STAT_ID_TO_CATEGORY)

    # Get current category scores
    your_category_scores = matchup.yourTeam.categoryScores or {}
    opponent_category_scores = matchup.opponentTeam.categoryScores or {}

    # Get roster schedules to determine games remaining
    # Use proper scoring period dates instead of simple date estimation

    # Get actual dates for the matchup period using scoring period mapping
    # Matchup periods typically correspond to scoring periods, but we need to map correctly
    # For now, use the matchup period as the scoring period to get dates
    # Calendar window of the matchup period, from ESPN's matchupPeriods mapping
    window = await client.get_matchup_period_dates(target_matchup_period, league_settings)
    matchup_end: date | None = None  # last day of the matchup period, for games-remaining
    if window is not None:
        start_date, matchup_end = window[0].isoformat(), window[1]
        end_date = window[1].isoformat()
    else:
        # Last resort: assume 7-day weeks around today
        logger.warning("Could not determine matchup period dates; estimating from today")
        weeks_offset = target_matchup_period - current_matchup_period
        start_dt = datetime.now() + timedelta(weeks=weeks_offset)
        start_date = start_dt.strftime("%Y-%m-%d")
        end_date = (start_dt + timedelta(days=6)).strftime("%Y-%m-%d")
        matchup_end = date.fromisoformat(end_date)

    opponent_team_id = matchup.opponentTeam.teamId
    if not opponent_team_id:
        raise ValueError("Opponent team ID not found in matchup")

    # Use the matchup period as scoring period for schedule lookup; both teams concurrently
    your_schedule, opponent_schedule = await asyncio.gather(
        client.get_roster_schedule_summary(team_id, start_date, end_date, target_matchup_period),
        client.get_roster_schedule_summary(
            opponent_team_id, start_date, end_date, target_matchup_period
        ),
    )

    # Get player stats for all players (projections and recent performance)
    your_player_ids = [entry.playerId for entry in matchup.yourRoster.entries]
    opponent_player_ids = [entry.playerId for entry in matchup.opponentRoster.entries]
    all_player_ids = your_player_ids + opponent_player_ids

    # Get projections and recent stats
    player_projections = {}
    player_recent_stats = {}
    if all_player_ids:
        try:
            projections_list, recent_list = await asyncio.gather(
                client.get_player_stats(all_player_ids, "projections"),
                client.get_player_stats(all_player_ids, "last_7"),
            )

            # Normalize to lists
            if isinstance(projections_list, list):
                for stats in projections_list:
                    player_projections[stats.playerId] = stats
            else:
                player_projections[projections_list.playerId] = projections_list

            if isinstance(recent_list, list):
                for stats in recent_list:
                    player_recent_stats[stats.playerId] = stats
            else:
                player_recent_stats[recent_list.playerId] = recent_list
        except Exception as e:
            logger.warning(f"Could not get player stats for analysis: {e}")

    # Calculate category projections
    category_projections = []
    categories_winning = []
    categories_losing = []
    categories_tied = []
    close_categories = []

    # Current category wins/losses/ties are tallied in the loop below
    current_category_wins = 0
    current_category_losses = 0
    current_category_ties = 0

    # Games already played are reflected in the current category scores, so projections
    # must only add games on or after today. Count them once per player for both rosters.
    now = datetime.now(ZoneInfo(client._get_timezone()))
    your_games_left = games_remaining_by_player(your_schedule, now, matchup_end)
    opponent_games_left = games_remaining_by_player(opponent_schedule, now, matchup_end)
    your_games_remaining = sum(your_games_left.values())
    opponent_games_remaining = sum(opponent_games_left.values())

    # Discount remaining games by availability: an OUT, suspended, IR, or unsigned player
    # contributes nothing, a DOUBTFUL player half. Projections use these expected games.
    your_availability = {e.playerId: player_availability(e) for e in matchup.yourRoster.entries}
    opponent_availability = {
        e.playerId: player_availability(e) for e in matchup.opponentRoster.entries
    }
    your_expected = {
        pid: games * your_availability.get(pid, ("ACTIVE", 1.0))[1]
        for pid, games in your_games_left.items()
    }
    opponent_expected = {
        pid: games * opponent_availability.get(pid, ("ACTIVE", 1.0))[1]
        for pid, games in opponent_games_left.items()
    }
    your_expected_games = round(sum(your_expected.values()), 1)
    opponent_expected_games = round(sum(opponent_expected.values()), 1)

    for stat_id in sorted(scoring_stat_ids):
        category_name = stat_mapping.get(str(stat_id))
        if not category_name:
            continue

        attempts_basis: float | None = None  # projected attempts, for percentage closeness
        your_current = your_category_scores.get(category_name, 0.0)
        opponent_current = opponent_category_scores.get(category_name, 0.0)
        current_lead = your_current - opponent_current

        # Special handling for percentage categories
        is_percentage_category = category_name in ["fieldGoalPercentage", "freeThrowPercentage"]

        # For percentage categories, we need to calculate from FGM/FGA or FTM/FTA totals
        if is_percentage_category:
            # Get component stats to calculate current percentages accurately
            # These should contain FGM/FGA/FTM/FTA counts (stat IDs 13, 14, 15, 16)
            your_component_stats = matchup.yourTeam.componentStats or {}
            opponent_component_stats = matchup.opponentTeam.componentStats or {}

            # Also try to get raw data from cumulativeScore if available
            # This ensures we get actual counts even if componentStats is missing or incorrect
            your_cumulative_score = matchup.yourTeam.cumulativeScore or {}
            opponent_cumulative_score = matchup.opponentTeam.cumulativeScore or {}
            your_score_by_stat = (
                your_cumulative_score.get("scoreByStat") or {}
                if isinstance(your_cumulative_score, dict)
                else {}
            )
            opponent_score_by_stat = (
                opponent_cumulative_score.get("scoreByStat") or {}
                if isinstance(opponent_cumulative_score, dict)
                else {}
            )

            if category_name == "fieldGoalPercentage":
                # Get FGM/FGA counts - try componentStats first, then raw API data
                your_fgm_raw = your_component_stats.get("fieldGoalsMade", 0.0)
                your_fga_raw = your_component_stats.get("fieldGoalsAttempted", 0.0)
                opponent_fgm_raw = opponent_component_stats.get("fieldGoalsMade", 0.0)
                opponent_fga_raw = opponent_component_stats.get("fieldGoalsAttempted", 0.0)

                # If componentStats doesn't have valid counts, try reading from raw API response
                if your_fgm_raw < 1.0 or your_fga_raw < 1.0:
                    your_fgm_stat = your_score_by_stat.get("13") or {}
                    your_fga_stat = your_score_by_stat.get("14") or {}
                    if isinstance(your_fgm_stat, dict) and "score" in your_fgm_stat:
                        your_fgm_raw = your_fgm_stat["score"]
                    if isinstance(your_fga_stat, dict) and "score" in your_fga_stat:
                        your_fga_raw = your_fga_stat["score"]

                if opponent_fgm_raw < 1.0 or opponent_fga_raw < 1.0:
                    opponent_fgm_stat = opponent_score_by_stat.get("13") or {}
                    opponent_fga_stat = opponent_score_by_stat.get("14") or {}
                    if isinstance(opponent_fgm_stat, dict) and "score" in opponent_fgm_stat:
                        opponent_fgm_raw = opponent_fgm_stat["score"]
                    if isinstance(opponent_fga_stat, dict) and "score" in opponent_fga_stat:
                        opponent_fga_raw = opponent_fga_stat["score"]

                # Validate that we have actual counts, not percentages
                # Counts should be large numbers (>= 1), percentages are < 1
                # If values look like percentages, treat as missing and use categoryScores percentage
                your_fgm = your_fgm_raw if your_fgm_raw >= 1.0 else 0.0
                your_fga = your_fga_raw if your_fga_raw >= 1.0 else 0.0
                opponent_fgm = opponent_fgm_raw if opponent_fgm_raw >= 1.0 else 0.0
                opponent_fga = opponent_fga_raw if opponent_fga_raw >= 1.0 else 0.0

                # Recalculate current percentages from totals if available
                # This ensures we're using the correct current percentage
                if your_fga > 0:
                    your_current = your_fgm / your_fga
                else:
                    # If no FGA counts available, use the percentage from categoryScores
                    your_current = your_category_scores.get(category_name, 0.0)

                if opponent_fga > 0:
                    opponent_current = opponent_fgm / opponent_fga
                else:
                    # If no FGA counts available, use the percentage from categoryScores
                    opponent_current = opponent_category_scores.get(category_name, 0.0)

                # Start projected totals from current counts
                # Projected = (currentFGM + projectedFGM) / (currentFGA + projectedFGA)
                your_projected_fgm = your_fgm
                your_projected_fga = your_fga
                opponent_projected_fgm = opponent_fgm
                opponent_projected_fga = opponent_fga

                # Add projected contributions for games remaining (not yet tipped off)
                for entry in matchup.yourRoster.entries:
                    player_id = entry.playerId
                    games_left = your_expected.get(player_id, 0.0)

                    if games_left > 0 and player_id in player_projections:
                        proj = player_projections[player_id]
                        # Try to get FGM/FGA from projections
                        # Note: PlayerStats may not include these, so we estimate from FG% and attempts
                        fgm_per_game = getattr(proj, "fieldGoalsMade", None)
                        fga_per_game = getattr(proj, "fieldGoalsAttempted", None)

                        # If not available, estimate from FG% and points (rough estimate)
                        if fgm_per_game is None or fga_per_game is None:
                            fg_pct = getattr(proj, "fieldGoalPercentage", None)
                            points_per_game = getattr(proj, "points", None) or 0.0
                            # Normalize percentage to decimal (PlayerStats stores as whole number 47.8, need 0.478)
                            if fg_pct is not None:
                                if fg_pct > 1.0:
                                    fg_pct = fg_pct / 100.0  # Convert from whole number to decimal
                            # Rough estimate: assume ~2 points per FGM (accounting for 3s and FTs)
                            if fg_pct and fg_pct > 0:
                                estimated_fgm = points_per_game / 2.0  # Rough estimate
                                estimated_fga = estimated_fgm / fg_pct if fg_pct > 0 else 0.0
                                fgm_per_game = (
                                    fgm_per_game if fgm_per_game is not None else estimated_fgm
                                )
                                fga_per_game = (
                                    fga_per_game if fga_per_game is not None else estimated_fga
                                )

                        if fgm_per_game is not None and fga_per_game is not None:
                            your_projected_fgm += fgm_per_game * games_left
                            your_projected_fga += fga_per_game * games_left

                # Add projected contributions for opponent
                for entry in matchup.opponentRoster.entries:
                    player_id = entry.playerId
                    games_left = opponent_expected.get(player_id, 0.0)

                    if games_left > 0 and player_id in player_projections:
                        proj = player_projections[player_id]
                        # Try to get FGM/FGA from projections
                        fgm_per_game = getattr(proj, "fieldGoalsMade", None)
                        fga_per_game = getattr(proj, "fieldGoalsAttempted", None)

                        # If not available, estimate from FG% and points
                        if fgm_per_game is None or fga_per_game is None:
                            fg_pct = getattr(proj, "fieldGoalPercentage", None)
                            points_per_game = getattr(proj, "points", None) or 0.0
                            # Normalize percentage to decimal (PlayerStats stores as whole number 47.8, need 0.478)
                            if fg_pct is not None:
                                if fg_pct > 1.0:
                                    fg_pct = fg_pct / 100.0  # Convert from whole number to decimal
                            if fg_pct and fg_pct > 0:
                                estimated_fgm = points_per_game / 2.0  # Rough estimate
                                estimated_fga = estimated_fgm / fg_pct if fg_pct > 0 else 0.0
                                fgm_per_game = (
                                    fgm_per_game if fgm_per_game is not None else estimated_fgm
                                )
                                fga_per_game = (
                                    fga_per_game if fga_per_game is not None else estimated_fga
                                )

                        if fgm_per_game is not None and fga_per_game is not None:
                            opponent_projected_fgm += fgm_per_game * games_left
                            opponent_projected_fga += fga_per_game * games_left

                # Calculate projected percentages using weighted average formula
                # Projected = (currentFGM + projectedFGM) / (currentFGA + projectedFGA)
                attempts_basis = max(your_projected_fga, opponent_projected_fga)
                if your_projected_fga > 0:
                    your_projected = your_projected_fgm / your_projected_fga
                else:
                    # If no FGA projected, use current percentage
                    your_projected = your_current

                if opponent_projected_fga > 0:
                    opponent_projected = opponent_projected_fgm / opponent_projected_fga
                else:
                    # If no FGA projected, use current percentage
                    opponent_projected = opponent_current

            elif category_name == "freeThrowPercentage":
                # Get FTM/FTA counts - try componentStats first, then raw API data
                your_ftm_raw = your_component_stats.get("freeThrowsMade", 0.0)
                your_fta_raw = your_component_stats.get("freeThrowsAttempted", 0.0)
                opponent_ftm_raw = opponent_component_stats.get("freeThrowsMade", 0.0)
                opponent_fta_raw = opponent_component_stats.get("freeThrowsAttempted", 0.0)

                # If componentStats doesn't have valid counts, try reading from raw API response
                if your_ftm_raw < 1.0 or your_fta_raw < 1.0:
                    your_ftm_stat = your_score_by_stat.get("15") or {}
                    your_fta_stat = your_score_by_stat.get("16") or {}
                    if isinstance(your_ftm_stat, dict) and "score" in your_ftm_stat:
                        your_ftm_raw = your_ftm_stat["score"]
                    if isinstance(your_fta_stat, dict) and "score" in your_fta_stat:
                        your_fta_raw = your_fta_stat["score"]

                if opponent_ftm_raw < 1.0 or opponent_fta_raw < 1.0:
                    opponent_ftm_stat = opponent_score_by_stat.get("15") or {}
                    opponent_fta_stat = opponent_score_by_stat.get("16") or {}
                    if isinstance(opponent_ftm_stat, dict) and "score" in opponent_ftm_stat:
                        opponent_ftm_raw = opponent_ftm_stat["score"]
                    if isinstance(opponent_fta_stat, dict) and "score" in opponent_fta_stat:
                        opponent_fta_raw = opponent_fta_stat["score"]

                # Validate that we have actual counts, not percentages
                # Counts should be large numbers (>= 1), percentages are < 1
                # If values look like percentages, treat as missing and use categoryScores percentage
                your_ftm = your_ftm_raw if your_ftm_raw >= 1.0 else 0.0
                your_fta = your_fta_raw if your_fta_raw >= 1.0 else 0.0
                opponent_ftm = opponent_ftm_raw if opponent_ftm_raw >= 1.0 else 0.0
                opponent_fta = opponent_fta_raw if opponent_fta_raw >= 1.0 else 0.0

                # Recalculate current percentages from totals if available
                if your_fta > 0:
                    your_current = your_ftm / your_fta
                else:
                    # If no FTA counts available, use the percentage from categoryScores
                    your_current = your_category_scores.get(category_name, 0.0)

                if opponent_fta > 0:
                    opponent_current = opponent_ftm / opponent_fta
                else:
                    # If no FTA counts available, use the percentage from categoryScores
                    opponent_current = opponent_category_scores.get(category_name, 0.0)

                # Start projected totals from current counts
                # Projected = (currentFTM + projectedFTM) / (currentFTA + projectedFTA)
                your_projected_ftm = your_ftm
                your_projected_fta = your_fta
                opponent_projected_ftm = opponent_ftm
                opponent_projected_fta = opponent_fta

                # Add projected contributions based on games remaining
                # For current week, only count games that haven't been played yet
                for entry in matchup.yourRoster.entries:
                    player_id = entry.playerId
                    games_left = your_expected.get(player_id, 0.0)

                    if games_left > 0 and player_id in player_projections:
                        proj = player_projections[player_id]
                        # Try to get FTM/FTA from projections
                        ftm_per_game = getattr(proj, "freeThrowsMade", None)
                        fta_per_game = getattr(proj, "freeThrowsAttempted", None)

                        # If not available, estimate from FT% and points/assists (players who drive get more FTs)
                        if ftm_per_game is None or fta_per_game is None:
                            ft_pct = getattr(proj, "freeThrowPercentage", None)
                            points_per_game = getattr(proj, "points", None) or 0.0
                            # Normalize percentage to decimal (PlayerStats stores as whole number 75.3, need 0.753)
                            if ft_pct is not None:
                                if ft_pct > 1.0:
                                    ft_pct = ft_pct / 100.0  # Convert from whole number to decimal
                            # Rough estimate: assume ~20% of points come from FTs, so ~0.2 * points = FTM
                            if ft_pct and ft_pct > 0:
                                estimated_ftm = points_per_game * 0.2  # Rough estimate
                                estimated_fta = estimated_ftm / ft_pct if ft_pct > 0 else 0.0
                                ftm_per_game = (
                                    ftm_per_game if ftm_per_game is not None else estimated_ftm
                                )
                                fta_per_game = (
                                    fta_per_game if fta_per_game is not None else estimated_fta
                                )

                        if ftm_per_game is not None and fta_per_game is not None:
                            your_projected_ftm += ftm_per_game * games_left
                            your_projected_fta += fta_per_game * games_left

                # Add projected contributions for opponent
                for entry in matchup.opponentRoster.entries:
                    player_id = entry.playerId
                    games_left = opponent_expected.get(player_id, 0.0)

                    if games_left > 0 and player_id in player_projections:
                        proj = player_projections[player_id]
                        # Try to get FTM/FTA from projections
                        ftm_per_game = getattr(proj, "freeThrowsMade", None)
                        fta_per_game = getattr(proj, "freeThrowsAttempted", None)

                        # If not available, estimate from FT% and points
                        if ftm_per_game is None or fta_per_game is None:
                            ft_pct = getattr(proj, "freeThrowPercentage", None)
                            points_per_game = getattr(proj, "points", None) or 0.0
                            # Normalize percentage to decimal (PlayerStats stores as whole number 75.3, need 0.753)
                            if ft_pct is not None:
                                if ft_pct > 1.0:
                                    ft_pct = ft_pct / 100.0  # Convert from whole number to decimal
                            if ft_pct and ft_pct > 0:
                                estimated_ftm = points_per_game * 0.2  # Rough estimate
                                estimated_fta = estimated_ftm / ft_pct if ft_pct > 0 else 0.0
                                ftm_per_game = (
                                    ftm_per_game if ftm_per_game is not None else estimated_ftm
                                )
                                fta_per_game = (
                                    fta_per_game if fta_per_game is not None else estimated_fta
                                )

                        if ftm_per_game is not None and fta_per_game is not None:
                            opponent_projected_ftm += ftm_per_game * games_left
                            opponent_projected_fta += fta_per_game * games_left

                # Calculate projected percentages using weighted average formula
                # Projected = (currentFTM + projectedFTM) / (currentFTA + projectedFTA)
                attempts_basis = max(your_projected_fta, opponent_projected_fta)
                if your_projected_fta > 0:
                    your_projected = your_projected_ftm / your_projected_fta
                else:
                    # If no FTA projected, use current percentage
                    your_projected = your_current

                if opponent_projected_fta > 0:
                    opponent_projected = opponent_projected_ftm / opponent_projected_fta
                else:
                    # If no FTA projected, use current percentage
                    opponent_projected = opponent_current

            # Recalculate current_lead with accurate percentages
            current_lead = your_current - opponent_current

        else:
            # For non-percentage categories, use additive projection
            # Always calculate projections based on games remaining and player averages
            your_projected_add = 0.0
            opponent_projected_add = 0.0

            # Calculate projections for your team
            for entry in matchup.yourRoster.entries:
                player_id = entry.playerId
                games_left = your_expected.get(player_id, 0.0)

                if games_left > 0 and player_id in player_projections:
                    proj = player_projections[player_id]
                    # Get per-game average for this category
                    category_value = getattr(proj, category_name, None)
                    if category_value is not None:
                        # Add projected contribution: per-game average * games remaining
                        your_projected_add += category_value * games_left

            # Calculate projections for opponent team
            for entry in matchup.opponentRoster.entries:
                player_id = entry.playerId
                games_left = opponent_expected.get(player_id, 0.0)

                if games_left > 0 and player_id in player_projections:
                    proj = player_projections[player_id]
                    category_value = getattr(proj, category_name, None)
                    if category_value is not None:
                        # Add projected contribution: per-game average * games remaining
                        opponent_projected_add += category_value * games_left

            # Projections = current score + (games remaining × player averages)
            your_projected = your_current + your_projected_add
            opponent_projected = opponent_current + opponent_projected_add

        projected_lead = (
            your_projected - opponent_projected
            if your_projected is not None and opponent_projected is not None
            else None
        )

        # Projected result, and whether the category is close on its own scale
        projected_result = None
        margin = None
        is_close = False
        close_threshold: float | None = None
        closeness_rule: str | None = None

        if projected_lead is not None:
            margin = abs(projected_lead)
            close_threshold, closeness_rule = category_close_threshold(
                category_name, is_percentage_category, your_current, attempts_basis
            )
            is_close = margin <= close_threshold

            # A tie is a lead too small to mean anything: a fifth of a percentage point, or a
            # tenth of a counting stat. Win/loss is decided by the sign of anything larger.
            epsilon = 0.002 if is_percentage_category else 0.1
            if projected_lead > epsilon:
                projected_result = "win"
                categories_winning.append(category_name)
            elif projected_lead < -epsilon:
                projected_result = "loss"
                categories_losing.append(category_name)
            else:
                projected_result = "tie"
                categories_tied.append(category_name)

            if is_close:
                close_categories.append(category_name)

        # Track current category wins/losses/ties with appropriate thresholds
        if is_percentage_category:
            # Use smaller threshold for percentage categories
            if current_lead > 0.002:
                current_category_wins += 1
            elif current_lead < -0.002:
                current_category_losses += 1
            else:
                current_category_ties += 1
        else:
            # Use original threshold for non-percentage categories
            if current_lead > 0.1:
                current_category_wins += 1
            elif current_lead < -0.1:
                current_category_losses += 1
            else:
                current_category_ties += 1

        # Always include projections, even if they equal current (for future matchups, current is 0)
        category_projections.append(
            CategoryProjection(
                category=category_name,
                yourCurrent=your_current,
                opponentCurrent=opponent_current,
                yourProjected=your_projected,
                opponentProjected=opponent_projected,
                currentLead=current_lead,
                projectedLead=projected_lead,
                projectedResult=projected_result,
                margin=margin,
                isClose=is_close,
                closeThreshold=close_threshold,
                closenessRule=closeness_rule,
            )
        )

    # Generate player recommendations and lineup warnings
    player_recommendations = []
    lineup_warnings: list[str] = []

    for entry in matchup.yourRoster.entries:
        player_id = entry.playerId
        player = entry.playerPoolEntry.player
        games_remaining = your_games_left.get(player_id, 0)
        availability, factor = your_availability.get(player_id, ("ACTIVE", 1.0))
        slot_name = entry.lineupSlotName or dict(LINEUP_SLOT_NAMES).get(
            entry.lineupSlotId, f"SLOT_{entry.lineupSlotId}"
        )
        is_starter = entry.lineupSlotId not in (SLOT_BENCH, SLOT_IR)

        # ESPN's reason/timeline for the status, when it publishes one
        detail = f" ({player.injuryDetails})" if player.injuryDetails else ""

        # A starter who cannot play is a dead lineup slot; say so explicitly.
        if is_starter and factor == 0.0:
            if availability == "FA":
                lineup_warnings.append(
                    f"{player.fullName} ({slot_name}) is not on an NBA roster and cannot "
                    "score; replace or move to bench"
                )
            elif games_remaining > 0:
                lineup_warnings.append(
                    f"{player.fullName} ({slot_name}) is {availability}{detail} with "
                    f"{games_remaining} game(s) left; move to bench and start a healthy player"
                )
        elif (
            is_starter
            and games_remaining > 0
            and availability not in ("ACTIVE", "NORMAL", "PROBABLE")
        ):
            lineup_warnings.append(
                f"{player.fullName} ({slot_name}) is {availability}{detail}; "
                "check status before tip-off"
            )

        # Skip players who cannot play or have no games left
        if games_remaining == 0 or factor == 0.0:
            continue

        # Get player stats
        proj_stats = player_projections.get(player_id)

        if not proj_stats:
            continue

        # Which categories this player moves, weighted by whether they are still in play.
        # Close categories (winnable or losable by a start/sit) count most. A category
        # projected lost by a wide margin is not penalised: hurting it costs nothing, and
        # helping it earns only a little. Categories safely won are ignored.
        categories_helped: list[str] = []
        categories_hurt: list[str] = []
        close_helped: list[str] = []
        close_hurt: list[str] = []
        shown_close_helped: list[str] = []
        shown_close_hurt: list[str] = []
        shown_trail_helped: list[str] = []
        shown_trail_hurt: list[str] = []
        priority_score = 5  # Base priority

        close_set = set(close_categories)
        for category in [c.category for c in category_projections]:
            if category not in close_set and category not in categories_losing:
                continue
            category_value = getattr(proj_stats, category, None)
            if category_value is None:
                continue
            verdict = category_verdict(category, category_value)
            if verdict is None:
                continue
            kind, display = verdict
            if kind == "helps":
                categories_helped.append(category)
                if category in close_set:
                    close_helped.append(category)
                    shown_close_helped.append(display)
                    priority_score += 3
                else:
                    shown_trail_helped.append(display)
                    priority_score += 1
            else:
                categories_hurt.append(category)
                if category in close_set:
                    close_hurt.append(category)
                    shown_close_hurt.append(display)
                    priority_score -= 2
                else:
                    shown_trail_hurt.append(display)

        # Boost priority for players with more games remaining
        if games_remaining >= 3:
            priority_score += 2
        elif games_remaining == 2:
            priority_score += 1

        # Discount uncertain availability
        if availability == "DOUBTFUL":
            priority_score -= 2
        elif availability in ("DAY_TO_DAY", "QUESTIONABLE"):
            priority_score -= 1

        # Boost priority if player helps in several close categories
        if len(close_helped) >= 3:
            priority_score += 2
        elif len(close_helped) >= 2:
            priority_score += 1

        # Cap priority between 1-10
        priority_score = max(1, min(10, priority_score))

        # Build reasoning, with the per-game numbers behind every claim
        reasoning_parts = []
        if shown_close_helped:
            reasoning_parts.append(f"Helps close categories: {', '.join(shown_close_helped)}")
        if shown_close_hurt:
            reasoning_parts.append(f"Hurts close categories: {', '.join(shown_close_hurt)}")
        if shown_trail_helped:
            reasoning_parts.append(f"Helps categories you trail: {', '.join(shown_trail_helped)}")
        if shown_trail_hurt:
            reasoning_parts.append(
                "Hurts categories already projected lost (not penalised): "
                f"{', '.join(shown_trail_hurt)}"
            )
        if games_remaining >= 3:
            reasoning_parts.append(f"{games_remaining} games remaining")
        if availability not in ("ACTIVE", "NORMAL"):
            reasoning_parts.append(f"Status: {availability}{detail}")
        if not reasoning_parts:
            reasoning_parts.append("Active player; no close or trailing category moved")

        reasoning = ". ".join(reasoning_parts)

        # Get lineup slot name
        lineup_slot_name = None
        if entry.lineupSlotName:
            lineup_slot_name = entry.lineupSlotName
        else:
            lineup_slot_mapping = dict(LINEUP_SLOT_NAMES)
            lineup_slot_name = lineup_slot_mapping.get(
                entry.lineupSlotId, f"SLOT_{entry.lineupSlotId}"
            )

        player_recommendations.append(
            PlayerRecommendation(
                playerId=player_id,
                playerName=player.fullName,
                position=player.defaultPosition,
                lineupSlotId=entry.lineupSlotId,
                lineupSlotName=lineup_slot_name,
                gamesRemaining=games_remaining,
                availability=availability,
                expectedGames=round(games_remaining * factor, 1),
                priority=priority_score,
                reasoning=reasoning,
                categoriesHelped=categories_helped,
                categoriesHurt=categories_hurt,
                closeCategoriesHelped=close_helped,
                closeCategoriesHurt=close_hurt,
                injuryStatus=entry.injuryStatus,
                injuryDetails=player.injuryDetails,
                todaysGame=entry.todaysGame,
            )
        )

    # Sort recommendations by priority (highest first), then by expected games
    player_recommendations.sort(key=lambda x: (x.priority, x.expectedGames or 0), reverse=True)

    # The opponent's side of the projection, player by player
    category_names = [
        name for sid in sorted(scoring_stat_ids) if (name := stat_mapping.get(str(sid)))
    ]
    opponent_players: list[OpponentPlayerSummary] = []
    for entry in matchup.opponentRoster.entries:
        player = entry.playerPoolEntry.player
        games = opponent_games_left.get(entry.playerId, 0)
        label, factor = opponent_availability.get(entry.playerId, ("ACTIVE", 1.0))
        opp_proj: PlayerStats | None = player_projections.get(entry.playerId)
        per_game = (
            {
                name: value
                for name in category_names
                if (value := getattr(opp_proj, name, None)) is not None
            }
            if opp_proj
            else None
        )
        opponent_players.append(
            OpponentPlayerSummary(
                playerId=entry.playerId,
                playerName=player.fullName,
                lineupSlotName=entry.lineupSlotName
                or dict(LINEUP_SLOT_NAMES).get(entry.lineupSlotId, f"SLOT_{entry.lineupSlotId}"),
                gamesRemaining=games,
                availability=label,
                expectedGames=round(games * factor, 1),
                injuryStatus=entry.injuryStatus or player.injuryStatus,
                injuryDetails=player.injuryDetails,
                projectedPerGame=per_game or None,
            )
        )

    # Generate strategy notes
    strategy_notes = []

    # Calculate projected category record
    projected_category_wins = len(categories_winning)
    projected_category_losses = len(categories_losing)

    if projected_category_wins > projected_category_losses:
        strategy_notes.append(
            f"Projected to win {projected_category_wins}-{projected_category_losses}"
        )
    elif projected_category_losses > projected_category_wins:
        strategy_notes.append(
            f"Currently trailing, projected {projected_category_wins}-{projected_category_losses}"
        )
    else:
        strategy_notes.append(
            f"Projected tie at {projected_category_wins}-{projected_category_wins}"
        )

    if close_categories:
        strategy_notes.append(
            f"Focus on {len(close_categories)} close categories: {', '.join(close_categories)}"
        )

    games_edge = round(your_expected_games - opponent_expected_games, 1)
    if games_edge > 0:
        strategy_notes.append(
            f"You have {games_edge:g} more expected games remaining than your opponent - advantage"
        )
    elif games_edge < 0:
        strategy_notes.append(
            f"Opponent has {-games_edge:g} more expected games remaining - consider streaming"
        )
    if lineup_warnings:
        strategy_notes.append(f"{len(lineup_warnings)} lineup warning(s): see lineupWarnings")

    if categories_losing:
        strategy_notes.append(f"Prioritize players who help in: {', '.join(categories_losing[:3])}")

    return MatchupAnalysis(
        matchupId=matchup.matchupId,
        scoringPeriod=matchup.scoringPeriod,
        yourTeamId=team_id,
        opponentTeamId=opponent_team_id,
        yourTeamName=matchup.yourTeam.teamName,
        opponentTeamName=matchup.opponentTeam.teamName,
        yourTeamAbbrev=matchup.yourTeam.teamAbbrev,
        opponentTeamAbbrev=matchup.opponentTeam.teamAbbrev,
        categoryProjections=category_projections,
        categoriesWinning=categories_winning,
        categoriesLosing=categories_losing,
        categoriesTied=categories_tied,
        closeCategories=close_categories,
        playerRecommendations=player_recommendations,
        projectionMethod=projection_method(end_date),
        yourGamesRemaining=your_games_remaining,
        opponentGamesRemaining=opponent_games_remaining,
        yourExpectedGames=your_expected_games,
        opponentExpectedGames=opponent_expected_games,
        expectedGamesBreakdown=expected_games_breakdown(
            matchup.yourRoster, your_games_left, your_availability
        ),
        opponentExpectedGamesBreakdown=expected_games_breakdown(
            matchup.opponentRoster, opponent_games_left, opponent_availability
        ),
        opponentPlayers=opponent_players,
        currentCategoryWins=current_category_wins,
        currentCategoryLosses=current_category_losses,
        currentCategoryTies=current_category_ties,
        projectedCategoryWins=projected_category_wins,
        projectedCategoryLosses=projected_category_losses,
        strategyNotes=strategy_notes,
        lineupWarnings=lineup_warnings,
    )

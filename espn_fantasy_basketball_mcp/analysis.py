"""Matchup analysis: category projections, start/sit priorities, lineup warnings, and
what-if roster moves.

The work is split in two so the same arithmetic serves `analyze_matchup` and
`simulate_roster_move`:

- `gather_inputs` fetches everything from ESPN (settings, matchup, both rosters, schedules,
  per-game stats on every basis) into a `MatchupInputs`.
- `compute_analysis` is pure: it turns a `MatchupInputs` into a `MatchupAnalysis`. The
  simulation swaps players in the inputs and runs it again, so before/after share one basis.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
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
    CategoryDelta,
    CategoryProjection,
    CurrentMatchup,
    LeagueSettings,
    MatchupAnalysis,
    OpponentPlayerSummary,
    PlayerRecommendation,
    PlayerStats,
    RosterEntry,
    RosterLegality,
    RosterMoveSimulation,
    RosterScheduleSummary,
)

if TYPE_CHECKING:
    from .client import ESPNFantasyBasketballClient

logger = logging.getLogger(__name__)

# Per-game bases a projection can be built on. "blend" averages projections and season actuals.
BASES = ("projections", "season", "last_7", "last_15", "last_30", "blend")
NEAR_FACTOR = 1.5  # a margin within 1.5x the close threshold is "near": effectively in play
PERCENTAGE_CATEGORIES = ("fieldGoalPercentage", "freeThrowPercentage")
COUNTING_FIELDS = (
    "points",
    "rebounds",
    "assists",
    "steals",
    "blocks",
    "threePointMade",
    "turnovers",
    "fieldGoalsMade",
    "fieldGoalsAttempted",
    "freeThrowsMade",
    "freeThrowsAttempted",
    "minutes",
)


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
    entries: list[RosterEntry],
    games_left: dict[int, int],
    availability: dict[int, tuple[str, float]],
) -> list[str]:
    """One line per player whose remaining games are discounted, plus the arithmetic."""
    lines: list[str] = []
    scheduled = 0
    expected = 0.0
    for entry in entries:
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


BASIS_DESCRIPTIONS = {
    "projections": "ESPN's rest-of-season per-game projections",
    "season": "this season's actual per-game averages",
    "last_7": "per-game averages over the last 7 days",
    "last_15": "per-game averages over the last 15 days",
    "last_30": "per-game averages over the last 30 days",
    "blend": "the mean of ESPN's projections and this season's actual per-game averages",
}


def projection_method(end_date: str, basis: str = "projections") -> str:
    """Spell out how the projections are built, so the reader can weigh them."""
    return (
        "Projected total = current matchup total + sum over rostered players of (per-game "
        f"average x expected remaining games), for BOTH teams on the same basis: "
        f"{BASIS_DESCRIPTIONS.get(basis, basis)} (basis='{basis}'). Expected games are the "
        f"player's scheduled games from now through {end_date} multiplied by an availability "
        "factor: OUT, suspended, in the IR slot or unsigned = 0; DOUBTFUL = 0.5; everything "
        "else = 1. A player listed OUT contributes nothing even if his expected return date "
        "falls inside the window. FG% and FT% are projected as made/attempted. A player with no "
        "numbers on the chosen basis falls back to ESPN's projections (listed in basisNotes). "
        "There is no confidence range given: early-season numbers are noisy."
    )


# --------------------------------------------------------------------------- inputs
@dataclass
class MatchupInputs:
    """Everything `compute_analysis` needs, fetched once. Swap fields to run what-ifs."""

    team_id: int
    opponent_team_id: int
    target_period: int
    matchup: CurrentMatchup
    settings: LeagueSettings
    start_date: str
    end_date: str
    matchup_end: date | None
    your_entries: list[RosterEntry]
    opponent_entries: list[RosterEntry]
    your_schedule: RosterScheduleSummary
    opponent_schedule: RosterScheduleSummary
    stats: dict[str, dict[int, PlayerStats]]  # basis -> playerId -> per-game stats
    basis: str
    now: datetime
    scoring_stat_ids: set[int]
    timezone: str
    roster_source: str
    basis_notes: list[str] = field(default_factory=list)


def _blend(a: PlayerStats, b: PlayerStats) -> PlayerStats:
    """Mean of two per-game lines; percentages recomputed from blended made/attempted."""
    values: dict[str, Any] = {}
    for name in COUNTING_FIELDS:
        x, y = getattr(a, name, None), getattr(b, name, None)
        if x is not None and y is not None:
            values[name] = round((x + y) / 2, 2)
        else:
            values[name] = x if x is not None else y
    for pct, made, att in (
        ("fieldGoalPercentage", "fieldGoalsMade", "fieldGoalsAttempted"),
        ("freeThrowPercentage", "freeThrowsMade", "freeThrowsAttempted"),
    ):
        m, t = values.get(made), values.get(att)
        if m is not None and t:
            values[pct] = round(m / t * 100, 1)
        else:
            x, y = getattr(a, pct, None), getattr(b, pct, None)
            values[pct] = round((x + y) / 2, 1) if x is not None and y is not None else x or y
    gp = a.gamesPlayed if a.gamesPlayed is not None else b.gamesPlayed
    return PlayerStats(
        playerId=a.playerId, playerName=a.playerName, timeframe="blend", gamesPlayed=gp, **values
    )


def basis_stats(inputs: MatchupInputs, player_id: int) -> PlayerStats | None:
    """Per-game line for a player on the chosen basis, falling back to projections."""
    if inputs.basis == "blend":
        proj = inputs.stats.get("projections", {}).get(player_id)
        season = inputs.stats.get("season", {}).get(player_id)
        if proj and season and (season.gamesPlayed or 0) > 0:
            return _blend(proj, season)
        return proj or season
    chosen = inputs.stats.get(inputs.basis, {}).get(player_id)
    if chosen is not None and (inputs.basis == "projections" or _has_numbers(chosen)):
        return chosen
    return inputs.stats.get("projections", {}).get(player_id)


def _has_numbers(stats: PlayerStats) -> bool:
    """A season/last-N line for a player who has not played is all zeros or None."""
    if stats.gamesPlayed is not None and stats.gamesPlayed > 0:
        return True
    return any((getattr(stats, f, None) or 0) > 0 for f in ("points", "rebounds", "assists"))


def _per_game_map(stats: PlayerStats | None, names: list[str]) -> dict[str, float] | None:
    if stats is None:
        return None
    out = {n: v for n in names if (v := getattr(stats, n, None)) is not None}
    return out or None


async def gather_inputs(
    client: ESPNFantasyBasketballClient,
    team_id: int,
    matchup_period: int | None = None,
    basis: str = "projections",
) -> MatchupInputs:
    """Fetch everything the projection needs. Raises ValueError for a bad basis or no matchup."""
    if basis not in BASES:
        raise ValueError(f"Invalid basis: {basis}. Must be one of {list(BASES)}")

    league_settings = await client.get_league_settings()
    current_matchup_period = league_settings.status.currentMatchupPeriod
    target_matchup_period = current_matchup_period + 1 if matchup_period is None else matchup_period

    matchup = await client.get_matchup_for_period(
        team_id, target_matchup_period, verbose=True, league_settings=league_settings
    )
    if not matchup:
        period_desc = "next" if matchup_period is None else f"period {matchup_period}"
        raise ValueError(f"No matchup found for team {team_id} in {period_desc} matchup")
    opponent_team_id = matchup.opponentTeam.teamId
    if not opponent_team_id:
        raise ValueError("Opponent team ID not found in matchup")

    window = await client.get_matchup_period_dates(target_matchup_period, league_settings)
    matchup_end: date | None = None
    if window is not None:
        start_date, matchup_end = window[0].isoformat(), window[1]
        end_date = window[1].isoformat()
    else:
        logger.warning("Could not determine matchup period dates; estimating from today")
        weeks_offset = target_matchup_period - current_matchup_period
        start_dt = datetime.now() + timedelta(weeks=weeks_offset)
        start_date = start_dt.strftime("%Y-%m-%d")
        end_date = (start_dt + timedelta(days=6)).strftime("%Y-%m-%d")
        matchup_end = date.fromisoformat(end_date)

    your_schedule, opponent_schedule = await asyncio.gather(
        client.get_roster_schedule_summary(team_id, start_date, end_date, target_matchup_period),
        client.get_roster_schedule_summary(
            opponent_team_id, start_date, end_date, target_matchup_period
        ),
    )

    all_player_ids = [e.playerId for e in matchup.yourRoster.entries] + [
        e.playerId for e in matchup.opponentRoster.entries
    ]
    stats = await fetch_stats(client, all_player_ids, basis)

    roster_source = (
        "today's roster for both teams (the same players get_team_roster returns), with "
        "lineup slots taken from the lineup set for the matchup's first day when ESPN has one"
        if matchup.rosterNote is None
        else matchup.rosterNote
    )
    return MatchupInputs(
        team_id=team_id,
        opponent_team_id=opponent_team_id,
        target_period=target_matchup_period,
        matchup=matchup,
        settings=league_settings,
        start_date=start_date,
        end_date=end_date,
        matchup_end=matchup_end,
        your_entries=list(matchup.yourRoster.entries),
        opponent_entries=list(matchup.opponentRoster.entries),
        your_schedule=your_schedule,
        opponent_schedule=opponent_schedule,
        stats=stats,
        basis=basis,
        now=datetime.now(ZoneInfo(client._get_timezone())),
        scoring_stat_ids=client._get_scoring_stat_ids(league_settings),
        timezone=client._get_timezone(),
        roster_source=roster_source,
    )


async def fetch_stats(
    client: ESPNFantasyBasketballClient, player_ids: list[int], basis: str
) -> dict[str, dict[int, PlayerStats]]:
    """Per-game stats for every player on projections, season, and the basis if different."""
    timeframes = ["projections", "season"]
    if basis not in ("projections", "season", "blend"):
        timeframes.append(basis)
    stats: dict[str, dict[int, PlayerStats]] = {t: {} for t in timeframes}
    if not player_ids:
        return stats

    async def one(timeframe: str) -> None:
        try:
            result = await client.get_player_stats(player_ids, timeframe)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not get {timeframe} stats for analysis: {e}")
            return
        for s in result if isinstance(result, list) else [result]:
            stats[timeframe][s.playerId] = s

    await asyncio.gather(*(one(t) for t in timeframes))
    return stats


# --------------------------------------------------------------------------- compute
def _shooting_per_game(
    stats: PlayerStats, made_attr: str, att_attr: str, pct_attr: str, points_share: float
) -> tuple[float, float] | None:
    """Per-game (made, attempted) for FG or FT, estimated from points and % when absent."""
    made = getattr(stats, made_attr, None)
    att = getattr(stats, att_attr, None)
    if made is not None and att is not None:
        return made, att
    pct = getattr(stats, pct_attr, None)
    points = getattr(stats, "points", None) or 0.0
    if pct is None:
        return None
    if pct > 1.0:
        pct = pct / 100.0
    if pct <= 0:
        return None
    est_made = points * points_share
    return est_made, est_made / pct


def _current_counts(
    side_component: dict[str, float], score_by_stat: dict, made_key: str, att_key: str
) -> tuple[float, float]:
    """Current made/attempted for a side, from componentStats or raw scoreByStat (IDs 13-16)."""
    names = {
        "13": "fieldGoalsMade",
        "14": "fieldGoalsAttempted",
        "15": "freeThrowsMade",
        "16": "freeThrowsAttempted",
    }
    made = side_component.get(names[made_key], 0.0)
    att = side_component.get(names[att_key], 0.0)
    if made < 1.0 or att < 1.0:
        m = score_by_stat.get(made_key) or {}
        a = score_by_stat.get(att_key) or {}
        if isinstance(m, dict) and "score" in m:
            made = m["score"]
        if isinstance(a, dict) and "score" in a:
            att = a["score"]
    # Counts are >= 1; anything smaller is a percentage or missing
    return (made if made >= 1.0 else 0.0), (att if att >= 1.0 else 0.0)


def compute_analysis(inputs: MatchupInputs) -> MatchupAnalysis:
    """Turn fetched inputs into the full analysis. Pure: no network."""
    matchup = inputs.matchup
    stat_mapping = dict(STAT_ID_TO_CATEGORY)
    category_names = [
        name for sid in sorted(inputs.scoring_stat_ids) if (name := stat_mapping.get(str(sid)))
    ]
    your_scores = matchup.yourTeam.categoryScores or {}
    opp_scores = matchup.opponentTeam.categoryScores or {}

    # Games left and expected games, per player, for both sides
    your_games_left = games_remaining_by_player(
        inputs.your_schedule, inputs.now, inputs.matchup_end
    )
    opp_games_left = games_remaining_by_player(
        inputs.opponent_schedule, inputs.now, inputs.matchup_end
    )
    your_avail = {e.playerId: player_availability(e) for e in inputs.your_entries}
    opp_avail = {e.playerId: player_availability(e) for e in inputs.opponent_entries}
    your_expected = {
        e.playerId: your_games_left.get(e.playerId, 0) * your_avail[e.playerId][1]
        for e in inputs.your_entries
    }
    opp_expected = {
        e.playerId: opp_games_left.get(e.playerId, 0) * opp_avail[e.playerId][1]
        for e in inputs.opponent_entries
    }
    your_games_remaining = sum(your_games_left.get(e.playerId, 0) for e in inputs.your_entries)
    opp_games_remaining = sum(opp_games_left.get(e.playerId, 0) for e in inputs.opponent_entries)
    your_expected_games = round(sum(your_expected.values()), 1)
    opp_expected_games = round(sum(opp_expected.values()), 1)

    # Per-game lines on the chosen basis, with fallbacks noted
    basis_notes = list(inputs.basis_notes)
    your_lines: dict[int, PlayerStats | None] = {}
    opp_lines: dict[int, PlayerStats | None] = {}
    for entries, lines in ((inputs.your_entries, your_lines), (inputs.opponent_entries, opp_lines)):
        for e in entries:
            line = basis_stats(inputs, e.playerId)
            lines[e.playerId] = line
            if (
                line is not None
                and inputs.basis not in ("projections", "blend")
                and line.timeframe != inputs.basis
                and your_expected.get(e.playerId, opp_expected.get(e.playerId, 0)) > 0
            ):
                basis_notes.append(
                    f"{e.playerPoolEntry.player.fullName}: no {inputs.basis} numbers; "
                    "ESPN projections used"
                )

    your_component = matchup.yourTeam.componentStats or {}
    opp_component = matchup.opponentTeam.componentStats or {}
    your_raw = (matchup.yourTeam.cumulativeScore or {}).get("scoreByStat") or {}
    opp_raw = (matchup.opponentTeam.cumulativeScore or {}).get("scoreByStat") or {}

    category_projections: list[CategoryProjection] = []
    winning: list[str] = []
    losing: list[str] = []
    tied: list[str] = []
    close: list[str] = []
    near: list[str] = []
    far_behind: list[str] = []
    cur_w = cur_l = cur_t = 0

    for category in category_names:
        is_pct = category in PERCENTAGE_CATEGORIES
        your_current = your_scores.get(category, 0.0)
        opp_current = opp_scores.get(category, 0.0)
        attempts_basis: float | None = None

        if is_pct:
            made_key, att_key = ("13", "14") if category == "fieldGoalPercentage" else ("15", "16")
            made_attr, att_attr = (
                ("fieldGoalsMade", "fieldGoalsAttempted")
                if category == "fieldGoalPercentage"
                else ("freeThrowsMade", "freeThrowsAttempted")
            )
            share = 0.5 if category == "fieldGoalPercentage" else 0.2
            y_made, y_att = _current_counts(your_component, your_raw, made_key, att_key)
            o_made, o_att = _current_counts(opp_component, opp_raw, made_key, att_key)
            your_current = y_made / y_att if y_att > 0 else your_scores.get(category, 0.0)
            opp_current = o_made / o_att if o_att > 0 else opp_scores.get(category, 0.0)
            y_pm, y_pa, o_pm, o_pa = y_made, y_att, o_made, o_att
            for e in inputs.your_entries:
                games = your_expected.get(e.playerId, 0.0)
                line = your_lines.get(e.playerId)
                if games > 0 and line is not None:
                    shooting = _shooting_per_game(line, made_attr, att_attr, category, share)
                    if shooting:
                        y_pm += shooting[0] * games
                        y_pa += shooting[1] * games
            for e in inputs.opponent_entries:
                games = opp_expected.get(e.playerId, 0.0)
                line = opp_lines.get(e.playerId)
                if games > 0 and line is not None:
                    shooting = _shooting_per_game(line, made_attr, att_attr, category, share)
                    if shooting:
                        o_pm += shooting[0] * games
                        o_pa += shooting[1] * games
            attempts_basis = max(y_pa, o_pa)
            your_projected = y_pm / y_pa if y_pa > 0 else your_current
            opp_projected = o_pm / o_pa if o_pa > 0 else opp_current
        else:
            y_add = sum(
                (getattr(your_lines.get(e.playerId), category, None) or 0.0)
                * your_expected.get(e.playerId, 0.0)
                for e in inputs.your_entries
                if your_lines.get(e.playerId) is not None
            )
            o_add = sum(
                (getattr(opp_lines.get(e.playerId), category, None) or 0.0)
                * opp_expected.get(e.playerId, 0.0)
                for e in inputs.opponent_entries
                if opp_lines.get(e.playerId) is not None
            )
            your_projected = your_current + y_add
            opp_projected = opp_current + o_add

        current_lead = your_current - opp_current
        projected_lead = your_projected - opp_projected
        margin = abs(projected_lead)
        close_threshold, closeness_rule = category_close_threshold(
            category, is_pct, your_current, attempts_basis
        )
        near_threshold = close_threshold * NEAR_FACTOR
        is_close = margin <= close_threshold
        closeness = "close" if is_close else "near" if margin <= near_threshold else "clear"

        epsilon = 0.002 if is_pct else 0.1
        if projected_lead > epsilon:
            result = "win"
            winning.append(category)
        elif projected_lead < -epsilon:
            result = "loss"
            losing.append(category)
        else:
            result = "tie"
            tied.append(category)
        if closeness == "close":
            close.append(category)
        elif closeness == "near":
            near.append(category)
        elif result == "loss":
            far_behind.append(category)

        if current_lead > epsilon:
            cur_w += 1
        elif current_lead < -epsilon:
            cur_l += 1
        else:
            cur_t += 1

        category_projections.append(
            CategoryProjection(
                category=category,
                yourCurrent=your_current,
                opponentCurrent=opp_current,
                yourProjected=your_projected,
                opponentProjected=opp_projected,
                currentLead=current_lead,
                projectedLead=projected_lead,
                projectedResult=result,
                margin=margin,
                isClose=is_close,
                closeness=closeness,
                closeThreshold=close_threshold,
                nearThreshold=near_threshold,
                closenessRule=closeness_rule,
            )
        )

    # ---- player recommendations and lineup warnings (every non-IR player is listed)
    recommendations: list[PlayerRecommendation] = []
    lineup_warnings: list[str] = []
    close_set = set(close)
    in_play = set(close) | set(near)
    season_map = inputs.stats.get("season", {})
    proj_map = inputs.stats.get("projections", {})

    for entry in inputs.your_entries:
        pid = entry.playerId
        player = entry.playerPoolEntry.player
        games_remaining = your_games_left.get(pid, 0)
        availability, factor = your_avail[pid]
        slot_name = entry.lineupSlotName or dict(LINEUP_SLOT_NAMES).get(
            entry.lineupSlotId, f"SLOT_{entry.lineupSlotId}"
        )
        is_starter = entry.lineupSlotId not in (SLOT_BENCH, SLOT_IR)
        detail = f" ({player.injuryDetails})" if player.injuryDetails else ""

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

        if entry.lineupSlotId == SLOT_IR:
            continue  # IR players are not start/sit candidates

        line = your_lines.get(pid)
        season_line = season_map.get(pid)

        def build(
            priority: int,
            reasoning: str,
            helped: list[str],
            hurt: list[str],
            close_helped: list[str],
            close_hurt: list[str],
            *,
            _entry: RosterEntry = entry,
            _line: PlayerStats | None = line,
            _season: PlayerStats | None = season_line,
            _games: int = games_remaining,
            _availability: str = availability,
            _factor: float = factor,
            _slot: str = slot_name,
        ) -> PlayerRecommendation:
            p = _entry.playerPoolEntry.player
            return PlayerRecommendation(
                playerId=_entry.playerId,
                playerName=p.fullName,
                position=p.defaultPosition,
                lineupSlotId=_entry.lineupSlotId,
                lineupSlotName=_slot,
                gamesRemaining=_games,
                availability=_availability,
                expectedGames=round(_games * _factor, 1),
                priority=priority,
                reasoning=reasoning,
                categoriesHelped=helped,
                categoriesHurt=hurt,
                closeCategoriesHelped=close_helped,
                closeCategoriesHurt=close_hurt,
                injuryStatus=_entry.injuryStatus,
                injuryDetails=p.injuryDetails,
                todaysGame=_entry.todaysGame,
                basisPerGame=_per_game_map(_line, category_names),
                seasonPerGame=_per_game_map(_season, category_names),
                projectedPerGame=_per_game_map(proj_map.get(_entry.playerId), category_names),
                seasonGamesPlayed=_season.gamesPlayed if _season else None,
            )

        if games_remaining == 0 or factor == 0.0 or line is None:
            if games_remaining == 0:
                why = "No games left in this matchup window"
            elif factor == 0.0:
                why = f"{availability}{detail}: contributes no expected games"
            else:
                why = "No per-game numbers available on any basis"
            recommendations.append(build(1, why, [], [], [], []))
            continue

        helped: list[str] = []
        hurt: list[str] = []
        close_helped: list[str] = []
        close_hurt: list[str] = []
        shown_close_helped: list[str] = []
        shown_close_hurt: list[str] = []
        shown_trail_helped: list[str] = []
        shown_trail_hurt: list[str] = []
        priority = 5
        for category in category_names:
            if category not in in_play and category not in losing:
                continue
            value = getattr(line, category, None)
            if value is None:
                continue
            verdict = category_verdict(category, value)
            if verdict is None:
                continue
            kind, display = verdict
            if kind == "helps":
                helped.append(category)
                if category in close_set:
                    close_helped.append(category)
                    shown_close_helped.append(display)
                    priority += 3
                elif category in in_play:
                    shown_close_helped.append(display + " [near]")
                    priority += 2
                else:
                    shown_trail_helped.append(display)
                    priority += 1
            else:
                hurt.append(category)
                if category in close_set:
                    close_hurt.append(category)
                    shown_close_hurt.append(display)
                    priority -= 2
                elif category in in_play:
                    shown_close_hurt.append(display + " [near]")
                    priority -= 1
                else:
                    shown_trail_hurt.append(display)

        if games_remaining >= 3:
            priority += 2
        elif games_remaining == 2:
            priority += 1
        if availability == "DOUBTFUL":
            priority -= 2
        elif availability in ("DAY_TO_DAY", "QUESTIONABLE"):
            priority -= 1
        if len(close_helped) >= 3:
            priority += 2
        elif len(close_helped) >= 2:
            priority += 1
        priority = max(1, min(10, priority))

        parts = []
        if shown_close_helped:
            parts.append(f"Helps close categories: {', '.join(shown_close_helped)}")
        if shown_close_hurt:
            parts.append(f"Hurts close categories: {', '.join(shown_close_hurt)}")
        if shown_trail_helped:
            parts.append(f"Helps categories you trail: {', '.join(shown_trail_helped)}")
        if shown_trail_hurt:
            parts.append(
                "Hurts categories already projected lost (not penalised): "
                f"{', '.join(shown_trail_hurt)}"
            )
        if games_remaining >= 3:
            parts.append(f"{games_remaining} games remaining")
        if availability not in ("ACTIVE", "NORMAL"):
            parts.append(f"Status: {availability}{detail}")
        if line is not None and line.timeframe != inputs.basis and inputs.basis != "blend":
            parts.append(f"Per-game numbers from '{line.timeframe}' (no {inputs.basis} line)")
        if not parts:
            parts.append("Active player; no close or trailing category moved")

        recommendations.append(
            build(priority, ". ".join(parts), helped, hurt, close_helped, close_hurt)
        )

    recommendations.sort(key=lambda r: (r.priority, r.expectedGames or 0), reverse=True)

    opponent_players: list[OpponentPlayerSummary] = []
    for entry in inputs.opponent_entries:
        player = entry.playerPoolEntry.player
        games = opp_games_left.get(entry.playerId, 0)
        label, factor = opp_avail[entry.playerId]
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
                projectedPerGame=_per_game_map(proj_map.get(entry.playerId), category_names),
                basisPerGame=_per_game_map(opp_lines.get(entry.playerId), category_names),
                seasonPerGame=_per_game_map(season_map.get(entry.playerId), category_names),
            )
        )

    # ---- strategy notes, consistent with the closeness classification above
    notes: list[str] = []
    pw, pl = len(winning), len(losing)
    if pw > pl:
        notes.append(f"Projected to win {pw}-{pl}")
    elif pl > pw:
        notes.append(f"Currently trailing, projected {pw}-{pl}")
    else:
        notes.append(f"Projected tie at {pw}-{pw}")
    if close:
        notes.append(f"Focus on {len(close)} close categories: {', '.join(close)}")
    if near:
        notes.append(
            f"Within reach (margin under {NEAR_FACTOR:g}x the close threshold): {', '.join(near)}"
        )
    games_edge = round(your_expected_games - opp_expected_games, 1)
    if games_edge > 0:
        notes.append(
            f"You have {games_edge:g} more expected games remaining than your opponent - advantage"
        )
    elif games_edge < 0:
        notes.append(
            f"Opponent has {-games_edge:g} more expected games remaining - consider streaming"
        )
    if lineup_warnings:
        notes.append(f"{len(lineup_warnings)} lineup warning(s): see lineupWarnings")
    priority_cats = [c for c in category_names if c in in_play]
    if priority_cats:
        notes.append(
            "Prioritize players who help in the close and near categories: "
            + ", ".join(priority_cats)
        )
    if far_behind:
        notes.append("Projected lost by a wide margin, not worth chasing: " + ", ".join(far_behind))
    if basis_notes:
        notes.append(f"{len(basis_notes)} player(s) fell back to projections: see basisNotes")

    return MatchupAnalysis(
        matchupId=matchup.matchupId,
        scoringPeriod=matchup.scoringPeriod,
        matchupPeriod=inputs.target_period,
        yourTeamId=inputs.team_id,
        opponentTeamId=inputs.opponent_team_id,
        yourTeamName=matchup.yourTeam.teamName,
        opponentTeamName=matchup.opponentTeam.teamName,
        yourTeamAbbrev=matchup.yourTeam.teamAbbrev,
        opponentTeamAbbrev=matchup.opponentTeam.teamAbbrev,
        basis=inputs.basis,
        basisDescription=BASIS_DESCRIPTIONS.get(inputs.basis, inputs.basis),
        basisNotes=basis_notes,
        rosterSource=inputs.roster_source,
        categoryProjections=category_projections,
        categoriesWinning=winning,
        categoriesLosing=losing,
        categoriesTied=tied,
        closeCategories=close,
        nearCategories=near,
        playerRecommendations=recommendations,
        projectionMethod=projection_method(inputs.end_date, inputs.basis),
        yourGamesRemaining=your_games_remaining,
        opponentGamesRemaining=opp_games_remaining,
        yourExpectedGames=your_expected_games,
        opponentExpectedGames=opp_expected_games,
        expectedGamesBreakdown=expected_games_breakdown(
            inputs.your_entries, your_games_left, your_avail
        ),
        opponentExpectedGamesBreakdown=expected_games_breakdown(
            inputs.opponent_entries, opp_games_left, opp_avail
        ),
        opponentPlayers=opponent_players,
        currentCategoryWins=cur_w,
        currentCategoryLosses=cur_l,
        currentCategoryTies=cur_t,
        projectedCategoryWins=pw,
        projectedCategoryLosses=pl,
        strategyNotes=notes,
        lineupWarnings=lineup_warnings,
    )


async def analyze_matchup(
    client: ESPNFantasyBasketballClient,
    team_id: int,
    matchup_period: int | None = None,
    basis: str = "projections",
) -> MatchupAnalysis:
    """Analyze a matchup: category projections, close categories, start/sit priorities.

    By default analyzes the next matchup (current + 1). `basis` selects the per-game numbers
    used for BOTH teams: projections (default), season, last_7, last_15, last_30, or blend.
    """
    inputs = await gather_inputs(client, team_id, matchup_period, basis)
    return compute_analysis(inputs)


# --------------------------------------------------------------------------- what-if
def _roster_entry_for(player_entry: RosterEntry) -> RosterEntry:
    """A copy of a roster entry placed on the bench (slot only matters for IR)."""
    return replace_slot(player_entry, SLOT_BENCH)


def replace_slot(entry: RosterEntry, slot: int) -> RosterEntry:
    return entry.model_copy(
        update={"lineupSlotId": slot, "lineupSlotName": LINEUP_SLOT_NAMES.get(slot)}
    )


def _record(analysis: MatchupAnalysis) -> str:
    return f"{analysis.projectedCategoryWins}-{analysis.projectedCategoryLosses}-{len(analysis.categoriesTied)}"


async def simulate_roster_move(
    client: ESPNFantasyBasketballClient,
    team_id: int,
    drop_ids: list[int],
    add_ids: list[int],
    matchup_period: int | None = None,
    basis: str = "projections",
) -> RosterMoveSimulation:
    """Re-run the matchup projection with players dropped and/or added; report the deltas.

    Before and after use the same basis, the same window and the same opponent. Added players
    are looked up in the league (free agents or anyone else), given a bench slot, and their
    NBA schedule for the window is fetched like a rostered player's.
    """
    inputs = await gather_inputs(client, team_id, matchup_period, basis)
    before = compute_analysis(inputs)

    drop_set = set(drop_ids)
    kept = [e for e in inputs.your_entries if e.playerId not in drop_set]
    dropped_names = [
        f"{e.playerPoolEntry.player.fullName} ({e.playerId})"
        for e in inputs.your_entries
        if e.playerId in drop_set
    ]
    unknown_drops = sorted(drop_set - {e.playerId for e in inputs.your_entries})

    wanted_adds = [pid for pid in dict.fromkeys(add_ids) if pid not in {e.playerId for e in kept}]
    added_entries = await client.roster_entries_for_players(wanted_adds)
    added_entries = [_roster_entry_for(e) for e in added_entries]
    unknown_adds = sorted(set(wanted_adds) - {e.playerId for e in added_entries})
    new_entries = kept + added_entries

    subjects = [
        (e.playerId, e.playerPoolEntry.player.fullName, e.playerPoolEntry.player.proTeamId, True)
        for e in new_entries
    ]
    new_schedule = await client._schedule_summary(
        subjects, inputs.start_date, inputs.end_date, inputs.target_period, team_id=team_id
    )
    new_ids = [e.playerId for e in added_entries]
    extra_stats = await fetch_stats(client, new_ids, basis) if new_ids else {}
    merged_stats = {k: dict(v) for k, v in inputs.stats.items()}
    for timeframe, by_id in extra_stats.items():
        merged_stats.setdefault(timeframe, {}).update(by_id)

    after_inputs = replace(
        inputs,
        your_entries=new_entries,
        your_schedule=new_schedule,
        stats=merged_stats,
        roster_source=inputs.roster_source
        + f"; simulated: dropped {len(dropped_names)}, added {len(added_entries)}",
    )
    after = compute_analysis(after_inputs)

    before_by = {c.category: c for c in before.categoryProjections}
    deltas: list[CategoryDelta] = []
    flipped: list[str] = []
    for c in after.categoryProjections:
        b = before_by.get(c.category)
        b_proj = b.yourProjected if b else None
        delta = (
            round(c.yourProjected - b_proj, 4)
            if c.yourProjected is not None and b_proj is not None
            else None
        )
        changed = bool(b and (b.projectedResult != c.projectedResult or b.closeness != c.closeness))
        if b and b.projectedResult != c.projectedResult:
            flipped.append(f"{c.category}: {b.projectedResult} -> {c.projectedResult}")
        deltas.append(
            CategoryDelta(
                category=c.category,
                before=b_proj,
                after=c.yourProjected,
                delta=delta,
                opponentProjected=c.opponentProjected,
                resultBefore=b.projectedResult if b else None,
                resultAfter=c.projectedResult,
                closenessBefore=b.closeness if b else None,
                closenessAfter=c.closeness,
                changed=changed,
            )
        )

    legality: RosterLegality | None = None
    try:
        legality = await client.check_roster_move(team_id, wanted_adds, list(drop_set))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not check roster legality: {e}")

    added_recs = [r for r in after.playerRecommendations if r.playerId in set(new_ids)]
    summary = [
        f"Projected record {_record(before)} -> {_record(after)} on basis '{basis}'",
        f"Expected games {before.yourExpectedGames} -> {after.yourExpectedGames}",
    ]
    if flipped:
        summary.append("Categories that flip: " + "; ".join(flipped))
    else:
        summary.append("No category changes its projected result")
    if unknown_drops:
        summary.append(f"Not on your roster, ignored: {unknown_drops}")
    if unknown_adds:
        summary.append(f"Unknown player IDs, ignored: {unknown_adds}")
    if legality is not None and not legality.canMake:
        summary.append("Move is NOT legal as-is: " + "; ".join(legality.reasons))

    return RosterMoveSimulation(
        teamId=team_id,
        matchupPeriod=inputs.target_period,
        basis=basis,
        dropped=dropped_names,
        added=[f"{e.playerPoolEntry.player.fullName} ({e.playerId})" for e in added_entries],
        unknownDropIds=unknown_drops,
        unknownAddIds=unknown_adds,
        gamesRemainingBefore=before.yourGamesRemaining,
        gamesRemainingAfter=after.yourGamesRemaining,
        expectedGamesBefore=before.yourExpectedGames,
        expectedGamesAfter=after.yourExpectedGames,
        projectedRecordBefore=_record(before),
        projectedRecordAfter=_record(after),
        categoryDeltas=deltas,
        categoriesFlipped=flipped,
        addedPlayers=added_recs,
        legality=legality,
        summary=summary,
        projectionMethod=after.projectionMethod,
    )

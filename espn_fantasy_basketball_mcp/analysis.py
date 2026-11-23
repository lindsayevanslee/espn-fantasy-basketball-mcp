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
import itertools
import logging
import math
from collections import Counter
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
    WEEKLY_LOCK_RULES,
)
from .dates import remaining_game_dates_by_player
from .models import (
    CategoryDelta,
    CategoryProjection,
    CurrentMatchup,
    LeagueSettings,
    LineupOptimization,
    LineupOption,
    MatchupAnalysis,
    OpponentPlayerSummary,
    OutcomeRange,
    PlayerRecommendation,
    PlayerStats,
    RecordProbability,
    RosterEntry,
    RosterLegality,
    RosterMoveSimulation,
    RosterScheduleSummary,
)
from .outcomes import (
    CONFIDENCE,
    COUNTING_TIE_BAND,
    METHOD,
    CategoryOutcome,
    PlayerDispersion,
    ShootingLoad,
    category_outcome,
    dispersion_from_logs,
    dispersion_ratio,
    interval,
    matchup_odds,
    percentage_variance,
    total_variance,
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


@dataclass(frozen=True)
class ExpectedGames:
    """How many of one player's remaining games the projection counts, and why.

    `playable` is what he is expected to play whatever slot he is in (scheduled games times
    the availability factor, or the games on and after a reported return date for a player
    listed OUT). `counted` is what reaches the projection: `playable` when his slot scores,
    0 when it does not (bench in a weekly-lock league, IR).
    """

    availability: str
    factor: float
    scheduled: int
    playable: float
    counted: float
    slot_scores: bool
    note: str | None = None

    @property
    def detail(self) -> str:
        """ "(note; injury detail)" for messages, or "" when there is nothing to say."""
        return f" ({self.note})" if self.note else ""


def _return_date(entry: RosterEntry) -> date | None:
    raw = entry.playerPoolEntry.player.injuryReturnDate
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def expected_games_for(
    entry: RosterEntry,
    game_dates: list[date],
    window_end: date | None,
    today: date,
    weekly_lock: bool,
    effective_from: date | None = None,
    absence: int | None = None,
) -> ExpectedGames:
    """Expected games for one roster entry from its remaining game dates.

    - A pending add (effective_from) cannot score before the day his add takes effect, so
      earlier games are left out of `scheduled` and noted.
    - A simulated absence (absence = games missed, from his next game) removes those games
      from `playable`; `scheduled` keeps the real count so the discount is visible.
    - Availability discounts as in `player_availability` (OUT = 0, DOUBTFUL = 0.5, ...).
    - A player listed OUT whose ESPN return date is a reported timeline (not the next-game
      placeholder ESPN uses for day-to-day players) and falls inside the window keeps the
      games on and after that date. A return date already passed with the status still OUT
      is treated as stale: nothing counts.
    - In a weekly-lock league a bench player's games never reach the score, so they are
      playable but not counted; the note says so. The IR slot never counts.
    """
    label, factor = player_availability(entry)
    notes: list[str] = []
    if effective_from is not None:
        eligible_dates = [d for d in game_dates if d >= effective_from]
        if len(eligible_dates) < len(game_dates):
            notes.append(
                f"pending add effective {effective_from}: {len(game_dates) - len(eligible_dates)} "
                "earlier game(s) not counted"
            )
        game_dates = eligible_dates
    scheduled = len(game_dates)
    if absence is not None and absence > 0 and scheduled:
        missed = min(absence, scheduled)
        game_dates = game_dates[missed:]
        notes.append(
            "simulated: does not play"
            if missed == scheduled
            else f"simulated: misses {missed} of {scheduled} game(s)"
        )
    playable = len(game_dates) * factor
    player = entry.playerPoolEntry.player
    return_date = _return_date(entry) if label == "OUT" and scheduled else None
    if return_date is not None:
        if player.injuryReturnDateType == "placeholder":
            notes.append(
                f"expected return {return_date} is ESPN's next-game placeholder, not an "
                "estimate; no games counted"
            )
        elif return_date <= today:
            notes.append(
                f"expected return {return_date} has passed but the status is still OUT; "
                "no games counted"
            )
        elif window_end is not None and return_date > window_end:
            notes.append(f"expected return {return_date} is after this matchup period")
        else:
            back = sum(1 for d in game_dates if d >= return_date)
            playable = float(back)
            notes.append(
                f"expected return {return_date}: {back} of {scheduled} game(s) on or after it count"
            )
    slot_scores = entry.lineupSlotId != SLOT_IR
    if weekly_lock and entry.lineupSlotId == SLOT_BENCH:
        slot_scores = False
        if playable > 0:
            notes.append("on the bench: bench games do not score under the weekly lineup lock")
    if player.injuryDetails and (factor < 1.0 or return_date is not None):
        # ESPN's own words first, then the arithmetic
        notes.insert(0, player.injuryDetails.rstrip(".") if notes else player.injuryDetails)
    if effective_from is not None and scheduled and playable > 0:
        notes.append(f"counted from {effective_from}, when the add takes effect")
    return ExpectedGames(
        availability=label,
        factor=factor,
        scheduled=scheduled,
        playable=playable,
        counted=playable if slot_scores else 0.0,
        slot_scores=slot_scores,
        note="; ".join(notes) if notes else None,
    )


def expected_games_breakdown(
    entries: list[RosterEntry], games: dict[int, ExpectedGames]
) -> list[str]:
    """One line per player whose remaining games are discounted, plus the arithmetic."""
    lines: list[str] = []
    scheduled = 0
    expected = 0.0
    for entry in entries:
        g = games.get(entry.playerId)
        if g is None:
            continue
        scheduled += g.scheduled
        expected += g.counted
        if g.scheduled > 0 and g.counted < g.scheduled:
            player = entry.playerPoolEntry.player
            label = g.availability
            if not g.slot_scores and entry.lineupSlotId == SLOT_BENCH:
                label += ", not counted"
            detail = f"; {g.note}" if g.note else ""
            lines.append(
                f"{player.fullName}: {g.scheduled} scheduled, {g.counted:g} expected "
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


def projection_method(end_date: str, basis: str = "projections", weekly_lock: bool = False) -> str:
    """Spell out how the projections are built, so the reader can weigh them."""
    slots = (
        "Only players in starting slots count: this league locks lineups for the week, so a "
        "bench player's games never reach the score (benchPlayersNotCounted lists yours). "
        if weekly_lock
        else "Every non-IR player counts, bench included, on the assumption that a daily-lock "
        "lineup is set each day. "
    )
    return (
        "Projected total = current matchup total + sum over rostered players of (per-game "
        f"average x expected remaining games), for BOTH teams on the same basis: "
        f"{BASIS_DESCRIPTIONS.get(basis, basis)} (basis='{basis}'). Expected games are the "
        f"player's scheduled games from now through {end_date} multiplied by an availability "
        "factor: OUT, suspended, in the IR slot or unsigned = 0; DOUBTFUL = 0.5; everything "
        "else = 1. A player listed OUT with a reported return date inside the window keeps the "
        "games on and after that date (ESPN's next-game placeholder dates for day-to-day "
        f"players are ignored). {slots}FG% and FT% are projected as made/attempted. A player "
        "with no numbers on the chosen basis falls back to ESPN's projections (listed in "
        "basisNotes). These are point estimates; the range around them (yourRange, "
        "opponentRange, winProbability on each category, and outcomeRange for the matchup) is "
        "described in outcomeRange.method."
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
    # playerId -> first day he can score for this team (pending adds; see Roster.pendingAdds)
    effective_from: dict[int, date] = field(default_factory=dict)
    # playerId -> games he is simulated to miss (counted from his next game); a number at
    # least as large as his schedule means he does not play at all. Simulation only.
    absences: dict[int, int] = field(default_factory=dict)
    # playerId -> game-to-game spread from his recent game logs (see outcomes.py). A player
    # missing here gets the league-typical spread, so the range still works without logs.
    dispersion: dict[int, PlayerDispersion] = field(default_factory=dict)


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


def _totals_map(
    stats: PlayerStats | None, names: list[str], games: float
) -> dict[str, float] | None:
    """Per-game line x games counted, for counting categories and made/attempted shots.

    Percentages are left out (a percentage times games means nothing); the made/attempted
    pairs beside them are what the FG% / FT% projection actually sums.
    """
    if stats is None or games <= 0:
        return None
    out = {
        n: round(v * games, 1)
        for n in names
        if n not in PERCENTAGE_CATEGORIES and (v := getattr(stats, n, None)) is not None
    }
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
    # The roster schedule is built from today's roster; pending adds are not on it yet
    your_schedule, opponent_schedule = await asyncio.gather(
        _complete_schedule(
            client,
            your_schedule,
            matchup.yourRoster.entries,
            start_date,
            end_date,
            target_matchup_period,
            team_id,
        ),
        _complete_schedule(
            client,
            opponent_schedule,
            matchup.opponentRoster.entries,
            start_date,
            end_date,
            target_matchup_period,
            opponent_team_id,
        ),
    )

    all_player_ids = [e.playerId for e in matchup.yourRoster.entries] + [
        e.playerId for e in matchup.opponentRoster.entries
    ]
    stats, dispersion = await asyncio.gather(
        fetch_stats(client, all_player_ids, basis), fetch_dispersion(client, all_player_ids)
    )

    roster_source = (
        "today's roster for both teams (the same players get_team_roster returns), with "
        "lineup slots taken from the lineup set for the matchup's first day when ESPN has one"
        if matchup.rosterNote is None
        else matchup.rosterNote
    )
    effective_from: dict[int, date] = {}
    for roster in (matchup.yourRoster, matchup.opponentRoster):
        for pending in roster.pendingAdds or []:
            if pending.effectiveDate:
                try:
                    effective_from[pending.playerId] = date.fromisoformat(pending.effectiveDate)
                except ValueError:
                    continue
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
        effective_from=effective_from,
        dispersion=dispersion,
    )


async def _complete_schedule(
    client: ESPNFantasyBasketballClient,
    summary: RosterScheduleSummary,
    entries: list[RosterEntry],
    start_date: str,
    end_date: str,
    matchup_period: int,
    team_id: int,
) -> RosterScheduleSummary:
    """Add schedules for roster players the summary lacks (pending adds, which
    get_roster_schedule_summary cannot see because it reads today's roster)."""
    have = {ps.playerId for ps in summary.playerSchedules}
    missing = [e for e in entries if e.playerId not in have]
    if not missing:
        return summary
    subjects = [
        (e.playerId, e.playerPoolEntry.player.fullName, e.playerPoolEntry.player.proTeamId, True)
        for e in missing
    ]
    extra = await client._schedule_summary(
        subjects, start_date, end_date, matchup_period, team_id=team_id
    )
    return summary.model_copy(
        update={
            "playerSchedules": summary.playerSchedules + extra.playerSchedules,
            "totalGamesThisWeek": summary.totalGamesThisWeek + extra.totalGamesThisWeek,
            "totalGamesNextWeek": summary.totalGamesNextWeek + extra.totalGamesNextWeek,
        }
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


async def fetch_dispersion(
    client: ESPNFantasyBasketballClient, player_ids: list[int]
) -> dict[int, PlayerDispersion]:
    """Game-to-game spread per player from recent game logs, for the range of outcomes.

    The range is an extra on top of the projection, so a failed fetch is logged and the
    league-typical spread is used instead of failing the analysis.
    """
    if not player_ids:
        return {}
    try:
        logs = await client.get_player_game_logs(player_ids)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not get game logs; using league-typical spread: {e}")
        return {}
    return {pid: dispersion_from_logs(games) for pid, games in logs.items()}


# --------------------------------------------------------------------------- compute
def _sample_games(inputs: MatchupInputs, player_id: int, line: PlayerStats) -> float:
    """How many games the per-game line is based on: the window's games for a last-N basis,
    this season's games played otherwise (ESPN's projection is not a sample; the season's
    games stand in for how much is known about the player)."""
    if line.timeframe.startswith("last_") and line.gamesPlayed:
        return float(line.gamesPlayed)
    season = inputs.stats.get("season", {}).get(player_id)
    return float((season.gamesPlayed if season else None) or 0)


def _counting_variance(
    inputs: MatchupInputs,
    entries: list[RosterEntry],
    lines: dict[int, PlayerStats | None],
    games: dict[int, ExpectedGames],
    stat: str,
) -> float:
    """Variance of a team's remaining total in one counting stat."""
    variance = 0.0
    for e in entries:
        line, g = lines.get(e.playerId), games.get(e.playerId)
        if line is None or g is None or g.counted <= 0:
            continue
        variance += total_variance(
            getattr(line, stat, None) or 0.0,
            dispersion_ratio(inputs.dispersion.get(e.playerId), stat),
            g.counted,
            g.factor,
            _sample_games(inputs, e.playerId, line),
        )
    return variance


def _shooting_loads(
    inputs: MatchupInputs,
    entries: list[RosterEntry],
    lines: dict[int, PlayerStats | None],
    games: dict[int, ExpectedGames],
    made_attr: str,
    att_attr: str,
    pct_attr: str,
    share: float,
) -> list[ShootingLoad]:
    """Each player's remaining makes / attempts and attempt variance, for percentage_variance."""
    loads: list[ShootingLoad] = []
    for e in entries:
        line, g = lines.get(e.playerId), games.get(e.playerId)
        if line is None or g is None or g.counted <= 0:
            continue
        shooting = _shooting_per_game(line, made_attr, att_attr, pct_attr, share)
        if not shooting:
            continue
        sample = _sample_games(inputs, e.playerId, line)
        loads.append(
            ShootingLoad(
                made=shooting[0] * g.counted,
                attempted=shooting[1] * g.counted,
                attempt_variance=total_variance(
                    shooting[1],
                    dispersion_ratio(inputs.dispersion.get(e.playerId), att_attr),
                    g.counted,
                    g.factor,
                    sample,
                ),
                games=g.counted,
                sample_games=sample,
            )
        )
    return loads


def _outcome_range(
    inputs: MatchupInputs,
    projections: list[CategoryProjection],
    outcomes: list[CategoryOutcome],
    counted_ids: list[int],
) -> OutcomeRange:
    """Matchup-level odds from the per-category outcomes."""
    odds = matchup_odds(outcomes)
    with_logs = sum(
        1 for pid in counted_ids if (d := inputs.dispersion.get(pid)) is not None and d.from_logs
    )
    return OutcomeRange(
        confidenceLevel=CONFIDENCE,
        expectedCategoryWins=round(odds.expected_wins, 2),
        expectedCategoryLosses=round(odds.expected_losses, 2),
        expectedCategoryTies=round(odds.expected_ties, 2),
        matchupWinProbability=round(odds.win, 3),
        matchupTieProbability=round(odds.tie, 3),
        matchupLossProbability=round(odds.loss, 3),
        mostLikelyRecords=[
            RecordProbability(record=record, probability=round(p, 3))
            for record, p in odds.records[:5]
        ],
        tossUpCategories=[
            c.category for c, o in zip(projections, outcomes, strict=True) if o.toss_up
        ],
        varianceSource=(
            f"{with_logs} of {len(counted_ids)} players with games counted use their own game "
            "logs for game-to-game spread; the rest use league-typical values"
        ),
        method=METHOD,
    )


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
    # Categories where the lower total wins: turnovers, and anything the league marks reverse
    lower_is_better = {"turnovers"} | {
        name
        for item in inputs.settings.scoringSettings.scoringItems
        if item.isReverseItem and (name := stat_mapping.get(str(item.statId)))
    }

    # What a starter's owner can actually do about a dead slot depends on the lock rule, and
    # under a weekly lock only starting slots score at all
    lock_rule = inputs.settings.rosterSettings.lineupLocktimeType
    weekly_lock = lock_rule in WEEKLY_LOCK_RULES
    week_in_progress = inputs.target_period <= inputs.settings.status.currentMatchupPeriod

    # Games left and expected games, per player, for both sides
    today = inputs.now.date()
    your_dates = remaining_game_dates_by_player(
        inputs.your_schedule, inputs.now, inputs.matchup_end
    )
    opp_dates = remaining_game_dates_by_player(
        inputs.opponent_schedule, inputs.now, inputs.matchup_end
    )
    your_games = {
        e.playerId: expected_games_for(
            e,
            your_dates.get(e.playerId, []),
            inputs.matchup_end,
            today,
            weekly_lock,
            effective_from=inputs.effective_from.get(e.playerId),
            absence=inputs.absences.get(e.playerId),
        )
        for e in inputs.your_entries
    }
    opp_games = {
        e.playerId: expected_games_for(
            e,
            opp_dates.get(e.playerId, []),
            inputs.matchup_end,
            today,
            weekly_lock,
            effective_from=inputs.effective_from.get(e.playerId),
        )
        for e in inputs.opponent_entries
    }
    # Per-game lines carry made/attempted next to FG% / FT% so the percentage math is checkable
    shooting_fields: list[str] = []
    if "fieldGoalPercentage" in category_names:
        shooting_fields += ["fieldGoalsMade", "fieldGoalsAttempted"]
    if "freeThrowPercentage" in category_names:
        shooting_fields += ["freeThrowsMade", "freeThrowsAttempted"]
    line_fields = category_names + shooting_fields
    your_games_left = {pid: g.scheduled for pid, g in your_games.items()}
    opp_games_left = {pid: g.scheduled for pid, g in opp_games.items()}
    your_expected = {pid: g.counted for pid, g in your_games.items()}
    opp_expected = {pid: g.counted for pid, g in opp_games.items()}
    your_games_remaining = sum(your_games_left.values())
    opp_games_remaining = sum(opp_games_left.values())
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
    category_outcomes: list[CategoryOutcome] = []
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
            your_var = percentage_variance(
                _shooting_loads(
                    inputs,
                    inputs.your_entries,
                    your_lines,
                    your_games,
                    made_attr,
                    att_attr,
                    category,
                    share,
                ),
                y_made,
                y_att,
            )
            opp_var = percentage_variance(
                _shooting_loads(
                    inputs,
                    inputs.opponent_entries,
                    opp_lines,
                    opp_games,
                    made_attr,
                    att_attr,
                    category,
                    share,
                ),
                o_made,
                o_att,
            )
            pct_fields: dict[str, Any] = {
                "yourCurrentMade": round(y_made, 2),
                "yourCurrentAttempted": round(y_att, 2),
                "yourProjectedMade": round(y_pm, 2),
                "yourProjectedAttempted": round(y_pa, 2),
                "opponentCurrentMade": round(o_made, 2),
                "opponentCurrentAttempted": round(o_att, 2),
                "opponentProjectedMade": round(o_pm, 2),
                "opponentProjectedAttempted": round(o_pa, 2),
            }
        else:
            pct_fields = {}
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
            your_var = _counting_variance(
                inputs, inputs.your_entries, your_lines, your_games, category
            )
            opp_var = _counting_variance(
                inputs, inputs.opponent_entries, opp_lines, opp_games, category
            )

        # Leads are oriented so that positive is good for you, whichever way the category runs
        sign = -1.0 if category in lower_is_better else 1.0
        current_lead = sign * (your_current - opp_current)
        projected_lead = sign * (your_projected - opp_projected)
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

        # Range of outcomes: a spread around each projected value and the odds on the lead
        your_sd, opp_sd = math.sqrt(your_var), math.sqrt(opp_var)
        lead_sd = math.sqrt(your_var + opp_var)
        outcome = category_outcome(
            projected_lead, lead_sd, 0.0 if is_pct else COUNTING_TIE_BAND, result
        )
        category_outcomes.append(outcome)
        digits = 4 if is_pct else 1
        if is_pct:
            your_range = interval(your_projected, your_sd, 0.0, 1.0)
            opp_range = interval(opp_projected, opp_sd, 0.0, 1.0)
        else:  # a counting total cannot fall below what is already scored
            your_range = interval(your_projected, your_sd, low=your_current)
            opp_range = interval(opp_projected, opp_sd, low=opp_current)

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
                lowerIsBetter=category in lower_is_better,
                yourRange=[round(v, digits) for v in your_range],
                opponentRange=[round(v, digits) for v in opp_range],
                leadStdDev=round(lead_sd, digits),
                winProbability=round(outcome.win, 3),
                tieProbability=round(outcome.tie, 3),
                lossProbability=round(outcome.loss, 3),
                **pct_fields,
            )
        )

    # ---- player recommendations and lineup warnings (every non-IR player is listed)
    recommendations: list[PlayerRecommendation] = []
    lineup_warnings: list[str] = []
    close_set = set(close)

    next_period = inputs.target_period + 1
    if weekly_lock and week_in_progress:
        fix_now = (
            f"the slot is locked for the week (weekly lock), so nothing can change until "
            f"matchup period {next_period}"
        )
        check_now = "the slot is locked for the week (weekly lock); nothing to change"
    elif weekly_lock:
        fix_now = "bench or replace him before the week's first game locks every slot"
        check_now = "decide before the week's first game locks every slot"
    else:
        fix_now = "move to bench and start a healthy player"
        check_now = "check status before tip-off"
    in_play = set(close) | set(near)
    season_map = inputs.stats.get("season", {})
    proj_map = inputs.stats.get("projections", {})

    bench_not_counted: list[str] = []

    for entry in inputs.your_entries:
        pid = entry.playerId
        player = entry.playerPoolEntry.player
        g = your_games[pid]
        games_remaining = g.scheduled
        availability = g.availability
        slot_name = entry.lineupSlotName or dict(LINEUP_SLOT_NAMES).get(
            entry.lineupSlotId, f"SLOT_{entry.lineupSlotId}"
        )
        is_starter = entry.lineupSlotId not in (SLOT_BENCH, SLOT_IR)
        detail = g.detail

        if is_starter and g.playable == 0.0:
            if availability == "FA":
                lineup_warnings.append(
                    f"{player.fullName} ({slot_name}) is not on an NBA roster and cannot "
                    f"score; {fix_now}"
                )
            elif games_remaining > 0:
                lineup_warnings.append(
                    f"{player.fullName} ({slot_name}) is {availability}{detail} with "
                    f"{games_remaining} game(s) left; {fix_now}"
                )
        elif (
            is_starter
            and games_remaining > 0
            and availability not in ("ACTIVE", "NORMAL", "PROBABLE")
        ):
            lineup_warnings.append(
                f"{player.fullName} ({slot_name}) is {availability}{detail}; {check_now}"
            )

        # A bench player's games are real but do not score under a weekly lock. Say what the
        # owner can still do about it, by the slot's own lock flag when ESPN gives one.
        bench_text: str | None = None
        if not g.slot_scores and entry.lineupSlotId == SLOT_BENCH and g.playable > 0:
            bench_not_counted.append(f"{player.fullName}: {g.playable:g} playable game(s)")
            if not week_in_progress:
                bench_text = (
                    "On the bench in the planned lineup: his games count only if he is "
                    "started before the week's first game locks the slot"
                )
            elif entry.lineupLocked is False:
                bench_text = (
                    "On the bench with the slot not yet locked: his games count only if he "
                    "is moved into the lineup before his first game"
                )
            elif entry.lineupLocked is True or lock_rule == "FIRSTGAME_WEEKLY":
                bench_text = (
                    "On the bench and locked for the week: his games do not count this period"
                )
            else:
                bench_text = (
                    "On the bench: his games do not count unless the slot is still unlocked "
                    "(see lineupLocked on get_team_roster)"
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
            _g: ExpectedGames = g,
            _slot: str = slot_name,
        ) -> PlayerRecommendation:
            p = _entry.playerPoolEntry.player
            return PlayerRecommendation(
                playerId=_entry.playerId,
                playerName=p.fullName,
                position=p.defaultPosition,
                lineupSlotId=_entry.lineupSlotId,
                lineupSlotName=_slot,
                gamesRemaining=_g.scheduled,
                availability=_g.availability,
                expectedGames=round(_g.playable, 1),
                gamesInProjection=round(_g.counted, 1),
                countsInProjection=_g.slot_scores,
                availabilityNote=_g.note,
                priority=priority,
                reasoning=reasoning,
                categoriesHelped=helped,
                categoriesHurt=hurt,
                closeCategoriesHelped=close_helped,
                closeCategoriesHurt=close_hurt,
                injuryStatus=_entry.injuryStatus,
                injuryDetails=p.injuryDetails,
                todaysGame=_entry.todaysGame,
                basisPerGame=_per_game_map(_line, line_fields),
                seasonPerGame=_per_game_map(_season, line_fields),
                projectedPerGame=_per_game_map(proj_map.get(_entry.playerId), line_fields),
                projectedTotals=_totals_map(_line, line_fields, _g.counted),
                seasonGamesPlayed=_season.gamesPlayed if _season else None,
            )

        if games_remaining == 0 or g.playable == 0.0 or line is None:
            if games_remaining == 0:
                why = "No games left in this matchup window"
            elif g.playable == 0.0:
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
        elif availability in ("DAY_TO_DAY", "QUESTIONABLE", "OUT"):
            priority -= 1  # OUT reaches here only with a return date inside the window
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
        if bench_text:
            parts.append(bench_text)
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
        og = opp_games[entry.playerId]
        opponent_players.append(
            OpponentPlayerSummary(
                playerId=entry.playerId,
                playerName=player.fullName,
                lineupSlotName=entry.lineupSlotName
                or dict(LINEUP_SLOT_NAMES).get(entry.lineupSlotId, f"SLOT_{entry.lineupSlotId}"),
                gamesRemaining=og.scheduled,
                availability=og.availability,
                expectedGames=round(og.playable, 1),
                gamesInProjection=round(og.counted, 1),
                countsInProjection=og.slot_scores,
                availabilityNote=og.note,
                injuryStatus=entry.injuryStatus or player.injuryStatus,
                injuryDetails=player.injuryDetails,
                projectedPerGame=_per_game_map(proj_map.get(entry.playerId), line_fields),
                basisPerGame=_per_game_map(opp_lines.get(entry.playerId), line_fields),
                seasonPerGame=_per_game_map(season_map.get(entry.playerId), line_fields),
                projectedTotals=_totals_map(opp_lines.get(entry.playerId), line_fields, og.counted),
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
    if bench_not_counted:
        notes.append(
            f"Weekly lineup lock: {len(bench_not_counted)} bench player(s) with games left "
            "are not in the projection (bench games do not score): " + "; ".join(bench_not_counted)
        )
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
    counted_ids = [pid for pid, n in your_expected.items() if n > 0] + [
        pid for pid, n in opp_expected.items() if n > 0
    ]
    outcome_range = _outcome_range(inputs, category_projections, category_outcomes, counted_ids)
    odds_note = (
        f"Estimated matchup odds: {outcome_range.matchupWinProbability:.0%} win, "
        f"{outcome_range.matchupTieProbability:.0%} tie, "
        f"{outcome_range.matchupLossProbability:.0%} loss "
        f"(expected categories {outcome_range.expectedCategoryWins:g}-"
        f"{outcome_range.expectedCategoryLosses:g}-{outcome_range.expectedCategoryTies:g}); "
        "an approximation, see outcomeRange.method"
    )
    if outcome_range.tossUpCategories:
        odds_note += ". Toss-ups (35-65% to win): " + ", ".join(outcome_range.tossUpCategories)
    notes.append(odds_note)

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
        lineupLockRule=lock_rule,
        lineupLockDescription=inputs.settings.rosterSettings.lineupLocktimeDescription,
        categoryProjections=category_projections,
        categoriesWinning=winning,
        categoriesLosing=losing,
        categoriesTied=tied,
        closeCategories=close,
        nearCategories=near,
        playerRecommendations=recommendations,
        projectionMethod=projection_method(inputs.end_date, inputs.basis, weekly_lock),
        yourGamesRemaining=your_games_remaining,
        opponentGamesRemaining=opp_games_remaining,
        yourExpectedGames=your_expected_games,
        opponentExpectedGames=opp_expected_games,
        expectedGamesBreakdown=expected_games_breakdown(inputs.your_entries, your_games),
        opponentExpectedGamesBreakdown=expected_games_breakdown(inputs.opponent_entries, opp_games),
        benchPlayersNotCounted=bench_not_counted,
        opponentPlayers=opponent_players,
        currentCategoryWins=cur_w,
        currentCategoryLosses=cur_l,
        currentCategoryTies=cur_t,
        projectedCategoryWins=pw,
        projectedCategoryLosses=pl,
        outcomeRange=outcome_range,
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
    return with_alternate_basis(compute_analysis(inputs), inputs)


def with_alternate_basis(analysis: MatchupAnalysis, inputs: MatchupInputs) -> MatchupAnalysis:
    """Re-run the projection on the other everyday basis and mark where the two disagree.

    ESPN's projections and this season's actuals are both fetched for every analysis, so the
    comparison is free. Season actuals are the alternate to any other basis; projections are
    the alternate to season. A category where the two give a different result, or where one
    calls it close and the other clear, is listed in basisDisagreements; a reader should
    treat those calls as uncertain.
    """
    alternate = "season" if inputs.basis != "season" else "projections"
    if not inputs.stats.get(alternate):
        return analysis
    other = compute_analysis(replace(inputs, basis=alternate, basis_notes=[]))
    other_by = {c.category: c for c in other.categoryProjections}
    disagreements: list[str] = []
    result_flips: list[str] = []
    closeness_only: list[str] = []
    for c in analysis.categoryProjections:
        o = other_by.get(c.category)
        if o is None:
            continue
        same_result = c.projectedResult == o.projectedResult
        agree = same_result and {c.closeness, o.closeness} != {"close", "clear"}
        if not same_result:
            result_flips.append(c.category)
        elif not agree:
            closeness_only.append(c.category)
        c.alternateBasis = alternate
        c.alternateProjectedLead = o.projectedLead
        c.alternateResult = o.projectedResult
        c.alternateCloseness = o.closeness
        c.basesAgree = agree
        if not agree:
            disagreements.append(
                f"{c.category}: {inputs.basis} says {c.projectedResult} ({c.closeness}, lead "
                f"{(c.projectedLead or 0):+.4g}); {alternate} says {o.projectedResult} "
                f"({o.closeness}, lead {(o.projectedLead or 0):+.4g})"
            )
    analysis.alternateBasis = alternate
    analysis.alternateProjectedRecord = _record(other)
    analysis.basisDisagreements = disagreements
    if result_flips:
        plural = "y" if len(result_flips) == 1 else "ies"
        note = (
            f"The {alternate} basis gives a different result in {len(result_flips)} "
            f"categor{plural} ({_record(other)} on {alternate} vs {_record(analysis)} on "
            f"{inputs.basis}): {', '.join(result_flips)}. Treat those calls as uncertain"
        )
        if closeness_only:
            note += f"; it also differs on how close {', '.join(closeness_only)} are"
        analysis.strategyNotes.append(note + " (see basisDisagreements)")
    elif closeness_only:
        how_many = "y is" if len(closeness_only) == 1 else "ies are"
        analysis.strategyNotes.append(
            f"The {alternate} basis agrees with every result ({_record(other)}) but differs on "
            f"how close {len(closeness_only)} categor{how_many}: {', '.join(closeness_only)}. "
            "A category one basis calls close and the other clear is less safe than it looks "
            "(see basisDisagreements)"
        )
    else:
        analysis.strategyNotes.append(
            f"The {alternate} basis agrees with every category result ({_record(other)})"
        )
    return analysis


# --------------------------------------------------------------------------- what-if
def _roster_entry_for(player_entry: RosterEntry) -> RosterEntry:
    """A copy of a roster entry placed on the bench (slot only matters for IR)."""
    return replace_slot(player_entry, SLOT_BENCH)


def replace_slot(entry: RosterEntry, slot: int) -> RosterEntry:
    return entry.model_copy(
        update={"lineupSlotId": slot, "lineupSlotName": LINEUP_SLOT_NAMES.get(slot)}
    )


def _slot_label(slot: int) -> str:
    return LINEUP_SLOT_NAMES.get(slot, f"SLOT_{slot}")


def _apply_lineup_changes(
    entries: list[RosterEntry],
    start_ids: list[int],
    sit_ids: list[int],
    slot_counts: dict[str, int],
    week_in_progress: bool,
    target_period: int,
) -> tuple[list[str], list[str], list[str], list[str], list[RosterEntry]]:
    """Move players between starting slots and the bench for a what-if lineup.

    Returns (started, benched, changes, warnings, entries). Pairing is by position in the two
    lists: start_ids[i] takes sit_ids[i]'s slot if eligible; otherwise, and for unpaired
    starts, the first open starting slot he is eligible for (from rosterSettings.lineupSlotCounts
    minus the slots in use). Unpaired sits go to the bench and leave the slot open. Eligibility
    comes from the player's eligibleSlots; when ESPN gives none, the move is allowed and noted.
    """
    started: list[str] = []
    benched: list[str] = []
    changes: list[str] = []
    warnings: list[str] = []
    if not start_ids and not sit_ids:
        return started, benched, changes, warnings, entries
    by_id = {e.playerId: e for e in entries}
    starting_slots = (SLOT_BENCH, SLOT_IR)

    def name(e: RosterEntry) -> str:
        return e.playerPoolEntry.player.fullName

    def label(e: RosterEntry) -> str:
        return f"{name(e)} ({e.playerId})"

    def eligible(e: RosterEntry, slot: int) -> bool:
        slots = e.playerPoolEntry.player.eligibleSlots
        return slots is None or slot in slots

    def open_slots() -> list[int]:
        occupied = Counter(e.lineupSlotId for e in by_id.values())
        out: list[int] = []
        for raw, count in slot_counts.items():
            try:
                slot = int(raw)
            except (TypeError, ValueError):
                continue
            if slot in starting_slots or count <= 0:
                continue
            out.extend([slot] * max(0, count - occupied.get(slot, 0)))
        return out

    def move(pid: int, slot: int) -> None:
        by_id[pid] = replace_slot(by_id[pid], slot)

    def lock_check(e: RosterEntry) -> None:
        if week_in_progress and e.lineupLocked:
            warnings.append(
                f"{name(e)}'s slot is locked for this period; the change is simulated but "
                f"cannot be made until matchup period {target_period + 1}"
            )

    for i, start_pid in enumerate(start_ids):
        starter = by_id.get(start_pid)
        if starter is None:
            warnings.append(
                f"Player {start_pid} is not on the roster after the drops/adds; cannot start"
            )
            continue
        sit_pid = sit_ids[i] if i < len(sit_ids) else None
        sitter = by_id.get(sit_pid) if sit_pid is not None else None
        if sit_pid is not None and sitter is None:
            warnings.append(f"Player {sit_pid} is not on the roster; cannot sit")
        target: int | None = None
        if sitter is not None and sitter.playerId == start_pid:
            warnings.append(f"{name(starter)} cannot both start and sit")
            sitter = None
        if sitter is not None and sitter.lineupSlotId in starting_slots:
            warnings.append(f"{name(sitter)} is already on the bench")
            sitter = None
        if sitter is not None:
            if eligible(starter, sitter.lineupSlotId):
                target = sitter.lineupSlotId
            else:
                names = [
                    _slot_label(s)
                    for s in starter.playerPoolEntry.player.eligibleSlots or []
                    if s not in starting_slots
                ]
                warnings.append(
                    f"{name(starter)} is not eligible at {_slot_label(sitter.lineupSlotId)} "
                    f"({name(sitter)}'s slot); eligible at {', '.join(names) or 'unknown'}"
                )
        if target is None:
            target = next((s for s in open_slots() if eligible(starter, s)), None)
        if target is None:
            if starter.lineupSlotId not in starting_slots:
                warnings.append(
                    f"{name(starter)} already starts at {_slot_label(starter.lineupSlotId)}"
                )
            else:
                warnings.append(
                    f"No open starting slot {name(starter)} is eligible for; name a starter to sit"
                )
            continue
        if starter.playerPoolEntry.player.eligibleSlots is None:
            warnings.append(
                f"{name(starter)}: ESPN lists no eligible slots; eligibility not checked"
            )
        replaced = sitter is not None and sitter.lineupSlotId == target
        if replaced and sitter is not None:
            lock_check(sitter)
            move(sitter.playerId, SLOT_BENCH)
            benched.append(label(sitter))
        lock_check(starter)
        old_slot = starter.lineupSlotId
        move(start_pid, target)
        started.append(label(starter))
        change = f"{name(starter)} starts at {_slot_label(target)}"
        if replaced and sitter is not None:
            change += f" in place of {name(sitter)}, who goes to the bench"
        elif old_slot not in starting_slots:
            change += f" (his {_slot_label(old_slot)} slot is left open)"
        changes.append(change)

    for sit_pid in sit_ids[len(start_ids) :]:
        sitter = by_id.get(sit_pid)
        if sitter is None:
            warnings.append(f"Player {sit_pid} is not on the roster; cannot sit")
            continue
        if sitter.lineupSlotId in starting_slots:
            warnings.append(f"{name(sitter)} is already on the bench")
            continue
        lock_check(sitter)
        slot = sitter.lineupSlotId
        move(sit_pid, SLOT_BENCH)
        benched.append(label(sitter))
        changes.append(f"{name(sitter)} to the bench ({_slot_label(slot)} left open)")

    return started, benched, changes, warnings, [by_id[e.playerId] for e in entries]


ABSENT_ALL = 10**6  # an absence this long means "does not play at all"


def _record(analysis: MatchupAnalysis) -> str:
    return f"{analysis.projectedCategoryWins}-{analysis.projectedCategoryLosses}-{len(analysis.categoriesTied)}"


def _win_probability(analysis: MatchupAnalysis) -> float | None:
    return analysis.outcomeRange.matchupWinProbability if analysis.outcomeRange else None


def _expected_wins(analysis: MatchupAnalysis) -> float | None:
    return analysis.outcomeRange.expectedCategoryWins if analysis.outcomeRange else None


async def simulate_roster_move(
    client: ESPNFantasyBasketballClient,
    team_id: int,
    drop_ids: list[int],
    add_ids: list[int],
    matchup_period: int | None = None,
    basis: str = "projections",
    start_ids: list[int] | None = None,
    sit_ids: list[int] | None = None,
    absent_ids: list[int] | None = None,
    missed_games: dict[int, int] | None = None,
) -> RosterMoveSimulation:
    """Re-run the matchup projection with players dropped, added, started, sat or absent;
    report the deltas.

    Absences ("what if he does not play"): absent_ids lose every remaining game; missed_games
    maps a player to the number of games he misses, counted from his next one. His slot is
    unchanged, so a starter who does not play is a dead slot in the after projection.

    Lineup changes: start_ids[i] takes sit_ids[i]'s starting slot when he is eligible for it
    (the sat player goes to the bench); an unpaired start goes into an open starting slot he
    is eligible for; an unpaired sit frees his slot. Anything that cannot be done as asked
    (ineligible, no open slot, not on the roster) is reported in lineupWarnings and skipped;
    a change to a slot ESPN has locked for the period is simulated but flagged.

    Before and after use the same basis, the same window and the same opponent. Added players
    are looked up in the league (free agents or anyone else) and their NBA schedule for the
    window is fetched like a rostered player's. Each added player takes the starting slot of
    a dropped starter when that slot can still be filled (the week has not started, or ESPN
    says the slot is not locked); otherwise he goes to the bench, which under a weekly lock
    means his games do not count this period.
    """
    inputs = await gather_inputs(client, team_id, matchup_period, basis)
    before = compute_analysis(inputs)
    weekly_lock = inputs.settings.rosterSettings.lineupLocktimeType in WEEKLY_LOCK_RULES
    week_in_progress = inputs.target_period <= inputs.settings.status.currentMatchupPeriod

    drop_set = set(drop_ids)
    kept = [e for e in inputs.your_entries if e.playerId not in drop_set]
    dropped = [e for e in inputs.your_entries if e.playerId in drop_set]
    dropped_names = [f"{e.playerPoolEntry.player.fullName} ({e.playerId})" for e in dropped]
    unknown_drops = sorted(drop_set - {e.playerId for e in inputs.your_entries})

    wanted_adds = [pid for pid in dict.fromkeys(add_ids) if pid not in {e.playerId for e in kept}]
    added_entries = await client.roster_entries_for_players(wanted_adds)
    # Starting slots freed by the drops that an added player could still take
    open_slots = [
        e
        for e in dropped
        if e.lineupSlotId not in (SLOT_BENCH, SLOT_IR)
        and (not week_in_progress or e.lineupLocked is False)
    ]
    placements: list[str] = []
    placed: list[RosterEntry] = []
    for e in added_entries:
        name = e.playerPoolEntry.player.fullName
        if open_slots:
            freed = open_slots.pop(0)
            placed.append(replace_slot(e, freed.lineupSlotId))
            placements.append(
                f"{name} takes {freed.playerPoolEntry.player.fullName}'s "
                f"{LINEUP_SLOT_NAMES.get(freed.lineupSlotId, freed.lineupSlotId)} slot"
            )
        else:
            placed.append(_roster_entry_for(e))
            placements.append(f"{name} goes to the bench")
    added_entries = placed
    unknown_adds = sorted(set(wanted_adds) - {e.playerId for e in added_entries})
    new_entries = kept + added_entries

    absences: dict[int, int] = dict.fromkeys(absent_ids or [], ABSENT_ALL)
    conflicts: list[int] = []
    for pid, games in (missed_games or {}).items():
        if games > 0:
            if pid in absences:
                conflicts.append(pid)  # absent_ids is the stronger statement and wins
            absences[pid] = max(absences.get(pid, 0), games)
    by_id_now = {e.playerId: e for e in new_entries}
    absence_lines: list[str] = []
    for pid, games in absences.items():
        entry = by_id_now.get(pid)
        if entry is None:
            absence_lines.append(f"Player {pid} is not on the roster; absence ignored")
            continue
        who = entry.playerPoolEntry.player.fullName
        absence_lines.append(
            f"{who} does not play" if games >= ABSENT_ALL else f"{who} misses {games} game(s)"
        )
        if pid in conflicts:
            absence_lines.append(
                f"{who} is in both absent_ids and missed_games; absent_ids wins (he does not "
                "play). Give one or the other"
            )
    absences = {pid: g for pid, g in absences.items() if pid in by_id_now}

    started, benched, lineup_changes, lineup_warnings, new_entries = _apply_lineup_changes(
        new_entries,
        list(dict.fromkeys(start_ids or [])),
        list(dict.fromkeys(sit_ids or [])),
        inputs.settings.rosterSettings.lineupSlotCounts or {},
        week_in_progress,
        inputs.target_period,
    )

    subjects = [
        (e.playerId, e.playerPoolEntry.player.fullName, e.playerPoolEntry.player.proTeamId, True)
        for e in new_entries
    ]
    new_schedule = await client._schedule_summary(
        subjects, inputs.start_date, inputs.end_date, inputs.target_period, team_id=team_id
    )
    new_ids = [e.playerId for e in added_entries]
    extra_stats = await fetch_stats(client, new_ids, basis) if new_ids else {}
    extra_dispersion = await fetch_dispersion(client, new_ids)
    merged_stats = {k: dict(v) for k, v in inputs.stats.items()}
    for timeframe, by_id in extra_stats.items():
        merged_stats.setdefault(timeframe, {}).update(by_id)

    after_inputs = replace(
        inputs,
        your_entries=new_entries,
        your_schedule=new_schedule,
        stats=merged_stats,
        absences=absences,
        dispersion={**inputs.dispersion, **extra_dispersion},
        roster_source=inputs.roster_source
        + f"; simulated: dropped {len(dropped_names)}, added {len(added_entries)}, "
        f"lineup changes {len(lineup_changes)}, absences {len(absences)}",
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
                winProbabilityBefore=b.winProbability if b else None,
                winProbabilityAfter=c.winProbability,
                changed=changed,
                yourMadeAttemptedBefore=(
                    [b.yourProjectedMade, b.yourProjectedAttempted]
                    if b
                    and b.yourProjectedMade is not None
                    and b.yourProjectedAttempted is not None
                    else None
                ),
                yourMadeAttemptedAfter=(
                    [c.yourProjectedMade, c.yourProjectedAttempted]
                    if c.yourProjectedMade is not None and c.yourProjectedAttempted is not None
                    else None
                ),
            )
        )

    # Legality is about adds and drops; a lineup-only or absence-only what-if has none to check
    legality: RosterLegality | None = None
    if wanted_adds or drop_set:
        try:
            legality = await client.check_roster_move(team_id, wanted_adds, list(drop_set))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not check roster legality: {e}")

    added_recs = [r for r in after.playerRecommendations if r.playerId in set(new_ids)]
    summary = [
        f"Projected record {_record(before)} -> {_record(after)} on basis '{basis}'",
        f"Expected games {before.yourExpectedGames} -> {after.yourExpectedGames}",
    ]
    p_before, p_after = _win_probability(before), _win_probability(after)
    if p_before is not None and p_after is not None:
        summary.append(
            f"Estimated chance to win the matchup {p_before:.0%} -> {p_after:.0%} (an "
            "approximation; see analyze_matchup's outcomeRange.method)"
        )
    if placements:
        summary.append("Slots: " + "; ".join(placements))
    if lineup_changes:
        summary.append("Lineup: " + "; ".join(lineup_changes))
        if not weekly_lock:
            summary.append(
                "Daily lineup lock: bench players count in the projection anyway, so lineup "
                "changes alone do not move the projected totals"
            )
    if lineup_warnings:
        summary.append("Lineup warnings: " + "; ".join(lineup_warnings))
    if absence_lines:
        summary.append("Absences simulated: " + "; ".join(absence_lines))
    benched_adds = [r for r in added_recs if not r.countsInProjection]
    if weekly_lock and benched_adds:
        names = ", ".join(r.playerName for r in benched_adds)
        if week_in_progress:
            summary.append(
                f"Weekly lineup lock: {names} cannot enter a starting slot until matchup "
                f"period {inputs.target_period + 1} (no dropped starter's slot is open), so the "
                "deltas above give him no games this period"
            )
        else:
            summary.append(
                f"Weekly lineup lock: {names} is on the bench in this simulation, so the deltas "
                "above give him no games; drop a starter or start him before the week's first "
                "game for his games to count"
            )
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
    if legality is not None and legality.warnings:
        summary.append("Legality warnings: " + "; ".join(legality.warnings))

    return RosterMoveSimulation(
        teamId=team_id,
        matchupPeriod=inputs.target_period,
        basis=basis,
        dropped=dropped_names,
        added=[f"{e.playerPoolEntry.player.fullName} ({e.playerId})" for e in added_entries],
        unknownDropIds=unknown_drops,
        unknownAddIds=unknown_adds,
        placements=placements,
        started=started,
        benched=benched,
        lineupChanges=lineup_changes,
        lineupWarnings=lineup_warnings,
        absences=absence_lines,
        gamesRemainingBefore=before.yourGamesRemaining,
        gamesRemainingAfter=after.yourGamesRemaining,
        expectedGamesBefore=before.yourExpectedGames,
        expectedGamesAfter=after.yourExpectedGames,
        projectedRecordBefore=_record(before),
        projectedRecordAfter=_record(after),
        matchupWinProbabilityBefore=_win_probability(before),
        matchupWinProbabilityAfter=_win_probability(after),
        expectedCategoryWinsBefore=_expected_wins(before),
        expectedCategoryWinsAfter=_expected_wins(after),
        categoryDeltas=deltas,
        categoriesFlipped=flipped,
        addedPlayers=added_recs,
        legality=legality,
        summary=summary,
        projectionMethod=after.projectionMethod,
    )


# --------------------------------------------------------------------------- optimizer
OPTIMIZER_MAX_LINEUPS = 5000
SCORING_RULE = (
    "Lineups are ranked by projected category wins, then ties, then the sum over categories of "
    "the projected lead divided by that category's close threshold, each clipped to [-3, 3] so "
    "a blowout in one category cannot outweigh a close loss in another"
)


def _assign_slots(players: list[RosterEntry], slots: list[int]) -> dict[int, int] | None:
    """Match players to starting slots by eligibility (one player per slot); None if impossible."""
    if len(players) > len(slots):
        return None
    match: dict[int, int] = {}  # slot index -> player index

    def try_player(i: int, seen: set[int]) -> bool:
        eligible = players[i].playerPoolEntry.player.eligibleSlots
        for j, slot in enumerate(slots):
            if j in seen or (eligible is not None and slot not in eligible):
                continue
            seen.add(j)
            if j not in match or try_player(match[j], seen):
                match[j] = i
                return True
        return False

    for i in range(len(players)):
        if not try_player(i, set()):
            return None
    return {players[i].playerId: slots[j] for j, i in match.items()}


def _lineup_score(analysis: MatchupAnalysis) -> float:
    margins = 0.0
    for c in analysis.categoryProjections:
        if c.projectedLead is None or not c.closeThreshold:
            continue
        margins += max(-3.0, min(3.0, c.projectedLead / c.closeThreshold))
    return (
        (analysis.projectedCategoryWins or 0) * 1000
        + len(analysis.categoriesTied) * 100
        + round(margins, 3)
    )


def _lineup_map(entries: list[RosterEntry]) -> tuple[dict[str, str], list[str]]:
    """{"PG": name, "UTIL1": name, ...} for starters, plus the bench names."""
    lineup: dict[str, str] = {}
    bench: list[str] = []
    seen: Counter[str] = Counter()
    for e in sorted(entries, key=lambda e: e.lineupSlotId):
        name = e.playerPoolEntry.player.fullName
        if e.lineupSlotId == SLOT_IR:
            continue
        if e.lineupSlotId == SLOT_BENCH:
            bench.append(name)
            continue
        label = _slot_label(e.lineupSlotId)
        seen[label] += 1
        key = f"{label}{seen[label]}" if seen[label] > 1 or label == "UTIL" else label
        lineup[key] = name
    return lineup, bench


def _starting_ids(entries: list[RosterEntry]) -> set[int]:
    return {e.playerId for e in entries if e.lineupSlotId not in (SLOT_BENCH, SLOT_IR)}


async def optimize_lineup(
    client: ESPNFantasyBasketballClient,
    team_id: int,
    matchup_period: int | None = None,
    basis: str = "projections",
    top: int = 3,
) -> LineupOptimization:
    """Evaluate every valid starting lineup with the matchup projection and rank them.

    Only matters under a weekly lineup lock, where bench games do not score; in a daily-lock
    league every non-IR player counts, so the current lineup is returned with a note. Players
    whose slot ESPN has locked for the period in progress stay where they are. Players with no
    playable games are never started unless a slot would otherwise be empty, which shrinks
    the search; if the remaining choice still exceeds OPTIMIZER_MAX_LINEUPS, the players with
    the fewest playable games are dropped from consideration and the note says so.
    """
    inputs = await gather_inputs(client, team_id, matchup_period, basis)
    current = compute_analysis(inputs)
    settings = inputs.settings
    lock_rule = settings.rosterSettings.lineupLocktimeType
    weekly_lock = lock_rule in WEEKLY_LOCK_RULES
    week_in_progress = inputs.target_period <= settings.status.currentMatchupPeriod
    current_lineup, _ = _lineup_map(inputs.your_entries)
    current_starters = _starting_ids(inputs.your_entries)
    notes: list[str] = []

    def option(rank: int, analysis: MatchupAnalysis, entries: list[RosterEntry]) -> LineupOption:
        lineup, bench = _lineup_map(entries)
        after = _starting_ids(entries)
        by_id = {e.playerId: e for e in entries}
        games = {r.playerId: r.expectedGames or 0.0 for r in analysis.playerRecommendations}

        def line(verb: str, pid: int) -> str:
            return (
                f"{verb} {by_id[pid].playerPoolEntry.player.fullName} ({games.get(pid, 0):g} games)"
            )

        changes = [
            line("start", pid)
            for pid in sorted(after - current_starters, key=lambda p: -games.get(p, 0))
        ] + [
            line("sit", pid)
            for pid in sorted(current_starters - after, key=lambda p: -games.get(p, 0))
        ]
        return LineupOption(
            rank=rank,
            projectedRecord=_record(analysis),
            projectedCategoryWins=analysis.projectedCategoryWins or 0,
            projectedCategoryLosses=analysis.projectedCategoryLosses or 0,
            projectedCategoryTies=len(analysis.categoriesTied),
            score=_lineup_score(analysis),
            matchupWinProbability=_win_probability(analysis),
            expectedCategoryWins=_expected_wins(analysis),
            categoriesWon=analysis.categoriesWinning,
            categoriesLost=analysis.categoriesLosing,
            closeCategories=analysis.closeCategories,
            expectedGames=analysis.yourExpectedGames or 0.0,
            lineup=lineup,
            bench=bench,
            changes=changes,
            isCurrent=after == current_starters,
        )

    if not weekly_lock:
        notes.append(
            "Daily lineup lock: every non-IR player counts in the projection, so which players "
            "start does not change it; set the lineup day by day with get_team_roster"
        )
        return LineupOptimization(
            teamId=team_id,
            matchupPeriod=inputs.target_period,
            basis=basis,
            lineupLockRule=lock_rule,
            currentProjectedRecord=_record(current),
            currentLineup=current_lineup,
            currentIsBest=True,
            options=[option(1, current, inputs.your_entries)],
            lineupsEvaluated=1,
            scoring=SCORING_RULE,
            notes=notes,
            projectionMethod=current.projectionMethod,
        )

    starting_slots: list[int] = []
    for raw, count in (settings.rosterSettings.lineupSlotCounts or {}).items():
        try:
            slot = int(raw)
        except (TypeError, ValueError):
            continue
        if slot not in (SLOT_BENCH, SLOT_IR) and count > 0:
            starting_slots.extend([slot] * count)
    if not starting_slots:
        starting_slots = [
            e.lineupSlotId
            for e in inputs.your_entries
            if e.lineupSlotId not in (SLOT_BENCH, SLOT_IR)
        ]

    ir = [e for e in inputs.your_entries if e.lineupSlotId == SLOT_IR]
    active = [e for e in inputs.your_entries if e.lineupSlotId != SLOT_IR]
    fixed = [e for e in active if week_in_progress and e.lineupLocked]
    fixed_ids = {e.playerId for e in fixed}
    movable = [e for e in active if e.playerId not in fixed_ids]
    free_slots = list(starting_slots)
    for e in fixed:
        if e.lineupSlotId in free_slots:
            free_slots.remove(e.lineupSlotId)
    fixed_names = [
        f"{e.playerPoolEntry.player.fullName} ({_slot_label(e.lineupSlotId)}, locked)"
        for e in fixed
    ]

    # Playable games per movable player (slot-independent): the search only needs who plays
    today = inputs.now.date()
    dates = remaining_game_dates_by_player(inputs.your_schedule, inputs.now, inputs.matchup_end)
    playable = {
        e.playerId: expected_games_for(
            replace_slot(e, 0),
            dates.get(e.playerId, []),
            inputs.matchup_end,
            today,
            True,
            effective_from=inputs.effective_from.get(e.playerId),
        ).playable
        for e in movable
    }
    candidates = sorted(movable, key=lambda e: -playable[e.playerId])
    with_games = [e for e in candidates if playable[e.playerId] > 0]
    fillers = [e for e in candidates if playable[e.playerId] == 0]
    k = len(free_slots)
    search_note: str | None = None
    pool = list(with_games)
    if len(pool) > k and math.comb(len(pool), k) > OPTIMIZER_MAX_LINEUPS:
        while len(pool) > k and math.comb(len(pool), k) > OPTIMIZER_MAX_LINEUPS:
            pool.pop()
        search_note = (
            f"Search limited to the {len(pool)} players with the most playable games "
            f"({math.comb(len(pool), k)} lineups); {len(with_games) - len(pool)} player(s) with "
            "fewer games were not considered"
        )

    def build(starters: list[RosterEntry]) -> list[RosterEntry] | None:
        chosen = list(starters)
        chosen_ids = {e.playerId for e in chosen}
        extra = [e for e in fillers if e.playerId not in chosen_ids]
        while len(chosen) < k and extra:
            chosen.append(extra.pop(0))
        # Keep every starter who stays a starter in his current slot and place only the
        # newcomers, so an option differs from the lineup as set only where it has to;
        # fall back to a full reshuffle when that leaves a newcomer no eligible slot.
        kept_slots: dict[int, int] = {}
        open_slots = list(free_slots)
        newcomers: list[RosterEntry] = []
        for e in chosen:
            if e.lineupSlotId in open_slots and e.lineupSlotId not in (SLOT_BENCH, SLOT_IR):
                kept_slots[e.playerId] = e.lineupSlotId
                open_slots.remove(e.lineupSlotId)
            else:
                newcomers.append(e)
        assignment = _assign_slots(newcomers, open_slots)
        if assignment is not None:
            assignment.update(kept_slots)
        else:
            assignment = _assign_slots(chosen, free_slots)
            if assignment is None:
                return None
        out = list(fixed) + list(ir)
        for e in movable:
            out.append(replace_slot(e, assignment.get(e.playerId, SLOT_BENCH)))
        return out

    evaluated: list[tuple[float, MatchupAnalysis, list[RosterEntry]]] = []
    combos = itertools.combinations(pool, min(k, len(pool))) if pool else [()]
    for combo in combos:
        entries = build(list(combo))
        if entries is None:
            continue
        analysis = compute_analysis(replace(inputs, your_entries=entries))
        evaluated.append((_lineup_score(analysis), analysis, entries))
    if not evaluated:
        notes.append(
            "No valid assignment of players to slots was found; the current lineup is returned"
        )
        evaluated.append((_lineup_score(current), current, inputs.your_entries))
    evaluated.sort(key=lambda t: -t[0])
    current_score = _lineup_score(current)
    best_score = evaluated[0][0]
    options = [option(i + 1, a, e) for i, (_, a, e) in enumerate(evaluated[: max(1, top)])]
    if current_score < best_score:
        notes.append(
            f"Current lineup projects {_record(current)} (score {current_score:.3f}); the best "
            f"found projects {options[0].projectedRecord} (score {best_score:.3f})"
        )
    if fixed_names:
        notes.append("Locked for this period and not moved: " + ", ".join(fixed_names))
    if fillers:
        notes.append(
            "Never started unless a slot would be empty (no playable games): "
            + ", ".join(e.playerPoolEntry.player.fullName for e in fillers)
        )
    return LineupOptimization(
        teamId=team_id,
        matchupPeriod=inputs.target_period,
        basis=basis,
        lineupLockRule=lock_rule,
        currentProjectedRecord=_record(current),
        currentLineup=current_lineup,
        currentIsBest=current_score >= best_score,
        options=options,
        lineupsEvaluated=len(evaluated),
        fixedPlayers=fixed_names,
        scoring=SCORING_RULE,
        searchNote=search_note,
        notes=notes,
        projectionMethod=current.projectionMethod,
    )

"""Range of outcomes for a matchup projection: how far the totals can move, and how likely
each category and the matchup are to be won.

The projection in `analysis.py` is a point estimate (per-game average x expected games).
This module puts a spread around it. Everything here is pure arithmetic on numbers already
fetched; nothing is simulated and nothing touches the network.

Model, per player and counting stat:

- One game's value has variance `dispersion x per-game mean`. The dispersion (variance / mean)
  comes from the player's own recent game logs, shrunk toward the league-typical value so a
  handful of games cannot produce a wild number. With no usable logs the league value is used.
- An uncertain game (DOUBTFUL, availability factor 0.5) is a coin flip at that probability,
  which adds variance on top of the game-to-game noise.
- The per-game average is itself an estimate from a limited number of games, so its error
  (variance / games in the sample) is carried through the remaining games.

Percentages: makes given attempts are binomial (checked against live game logs: observed
variance / binomial variance has a median of 0.90 for FG and 1.03 for FT), plus the effect of
attempt volume moving between players who shoot better or worse than the team.

A team's total is treated as normal (a sum over many player-games), the two teams as
independent, and so the lead is normal. Category results are treated as independent of each
other when they are combined into a matchup win probability; they are not (points and made
field goals move together), so that one number is somewhat overconfident.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from statistics import NormalDist

# Median variance / mean of one game's value, over the 149 NBA players with at least 10 games
# and 24 minutes a game on 2026-11-22 (ESPN game logs, 2027 season). Most box-score stats are
# close to Poisson (1.0); points and free throws are about twice as wide.
LEAGUE_DISPERSION: dict[str, float] = {
    "points": 2.55,
    "rebounds": 1.13,
    "assists": 1.06,
    "steals": 0.97,
    "blocks": 1.04,
    "threePointMade": 1.03,
    "turnovers": 0.93,
    "fieldGoalsMade": 1.12,
    "fieldGoalsAttempted": 1.06,
    "freeThrowsMade": 1.76,
    "freeThrowsAttempted": 1.98,
}
DEFAULT_DISPERSION = 1.0  # a stat with no league figure is treated as Poisson
# A player's own dispersion is weighted by his games against this many games of the league value
PRIOR_GAMES = 10.0
MIN_LOG_GAMES = 5  # fewer logged games than this: league value only
# The per-game average is never trusted as if it came from fewer games than this
MIN_SAMPLE_GAMES = 5.0
CONFIDENCE = 0.80  # ranges are central 80% intervals
_Z = NormalDist().inv_cdf(0.5 + CONFIDENCE / 2)
# A counting category is tied when the (whole-number) totals are equal: |lead| < 0.5
COUNTING_TIE_BAND = 0.5
# A category whose win probability sits in this band is a toss-up
TOSS_UP_BAND = (0.35, 0.65)

METHOD = (
    f"Ranges are central {CONFIDENCE:.0%} intervals and probabilities come from a normal "
    "approximation, not a simulation. One game's variance = dispersion x the per-game average, "
    "where dispersion (variance / mean) is taken from the player's recent game logs shrunk "
    f"toward the league-typical value ({PRIOR_GAMES:g} games' weight), or the league value alone "
    f"with fewer than {MIN_LOG_GAMES} logged games. A DOUBTFUL game is a coin flip, and the "
    "error in the per-game average itself (variance / games it is based on) is carried "
    "through. FG% and FT% treat makes given attempts as binomial. The teams are independent. "
    "matchupWinProbability also treats categories as independent, which they are not (points "
    "and made shots move together), so it is somewhat overconfident; injuries not yet "
    "reported, rest days and lineup changes are not modelled at all."
)


@dataclass(frozen=True)
class PlayerDispersion:
    """Variance / mean of one game's value per stat, from a player's game logs."""

    games: int = 0
    ratios: dict[str, float] = field(default_factory=dict)

    @property
    def from_logs(self) -> bool:
        return bool(self.ratios)


def dispersion_from_logs(logs: Sequence[dict[str, float]]) -> PlayerDispersion:
    """Per-stat dispersion from box-score lines, shrunk toward the league value.

    `logs` is one dict per game played (stat name -> value). A stat the player never records
    (mean 0) is left out and falls back to the league value.
    """
    n = len(logs)
    if n < MIN_LOG_GAMES:
        return PlayerDispersion(games=n)
    ratios: dict[str, float] = {}
    for name, league in LEAGUE_DISPERSION.items():
        values = [float(game.get(name) or 0.0) for game in logs]
        mean = statistics.fmean(values)
        if mean <= 0:
            continue
        own = statistics.variance(values) / mean
        ratios[name] = (n * own + PRIOR_GAMES * league) / (n + PRIOR_GAMES)
    return PlayerDispersion(games=n, ratios=ratios)


def dispersion_ratio(dispersion: PlayerDispersion | None, stat: str) -> float:
    """The player's dispersion for `stat`, or the league-typical one."""
    if dispersion is not None and stat in dispersion.ratios:
        return dispersion.ratios[stat]
    return LEAGUE_DISPERSION.get(stat, DEFAULT_DISPERSION)


def total_variance(
    per_game: float, ratio: float, counted: float, factor: float, sample_games: float
) -> float:
    """Variance of one player's total over his remaining games.

    `counted` is his expected games (already multiplied by the availability `factor`). With a
    factor strictly between 0 and 1 the games are coin flips: counted / factor games, each
    played with probability factor. `sample_games` is how many games the per-game average is
    based on.
    """
    if counted <= 0 or per_game <= 0:
        return 0.0
    if 0.0 < factor < 1.0:
        games, p = counted / factor, factor
    else:
        games, p = counted, 1.0
    game_variance = ratio * per_game
    noise = games * (p * game_variance + p * (1.0 - p) * per_game**2)
    average_error = counted**2 * game_variance / max(sample_games, MIN_SAMPLE_GAMES)
    return noise + average_error


@dataclass(frozen=True)
class ShootingLoad:
    """One player's remaining shooting: expected makes and attempts, and attempt variance."""

    made: float
    attempted: float
    attempt_variance: float
    games: float
    sample_games: float


def percentage_variance(
    loads: Iterable[ShootingLoad], current_made: float, current_attempted: float
) -> float:
    """Variance of a team's final FG% or FT% (as a fraction), by the delta method.

    Final % = (current makes + remaining makes) / (current attempts + remaining attempts).
    Each player contributes binomial noise in his makes (widened for the error in his own
    percentage) and, when he shoots better or worse than the team, the effect of his attempt
    volume moving.
    """
    loads = [load for load in loads if load.attempted > 0]
    total_made = current_made + sum(load.made for load in loads)
    total_attempted = current_attempted + sum(load.attempted for load in loads)
    if total_attempted <= 0:
        return 0.0
    team_pct = total_made / total_attempted
    variance = 0.0
    for load in loads:
        pct = min(1.0, max(0.0, load.made / load.attempted))
        widen = 1.0 + load.games / max(load.sample_games, MIN_SAMPLE_GAMES)
        variance += load.attempted * pct * (1.0 - pct) * widen
        variance += (pct - team_pct) ** 2 * load.attempt_variance
    return variance / total_attempted**2


def interval(
    mean: float, sd: float, low: float | None = None, high: float | None = None
) -> tuple[float, float]:
    """Central CONFIDENCE interval around `mean`, clamped to [low, high] when given."""
    a, b = mean - _Z * sd, mean + _Z * sd
    if low is not None:
        a, b = max(a, low), max(b, low)
    if high is not None:
        a, b = min(a, high), min(b, high)
    return a, b


@dataclass(frozen=True)
class CategoryOutcome:
    """Probability of winning, tying and losing one category."""

    win: float
    tie: float
    loss: float

    @property
    def toss_up(self) -> bool:
        return TOSS_UP_BAND[0] <= self.win <= TOSS_UP_BAND[1]


def category_outcome(lead: float, sd: float, tie_band: float, result: str) -> CategoryOutcome:
    """Win / tie / loss probabilities for a category.

    `lead` is the projected lead oriented so positive is good (turnovers already flipped) and
    `sd` its standard deviation. With nothing left to play (sd 0) the projected `result`
    stands. `tie_band` is the half-width of a tie: 0.5 for counting totals, 0 for percentages.
    """
    if sd <= 1e-9:
        return CategoryOutcome(
            win=1.0 if result == "win" else 0.0,
            tie=1.0 if result == "tie" else 0.0,
            loss=1.0 if result == "loss" else 0.0,
        )
    dist = NormalDist(lead, sd)
    loss = dist.cdf(-tie_band)
    win = 1.0 - dist.cdf(tie_band)
    return CategoryOutcome(win=win, tie=max(0.0, 1.0 - win - loss), loss=loss)


@dataclass(frozen=True)
class MatchupOdds:
    """The matchup as a whole, from independent category outcomes."""

    win: float
    tie: float
    loss: float
    expected_wins: float
    expected_losses: float
    expected_ties: float
    records: list[tuple[str, float]]  # ("W-L-T", probability), most likely first


def matchup_odds(categories: Sequence[CategoryOutcome]) -> MatchupOdds:
    """Distribution of the category record, treating categories as independent.

    The matchup is won with more category wins than losses, as ESPN scores a
    head-to-head categories week.
    """
    states: dict[tuple[int, int], float] = {(0, 0): 1.0}
    for c in categories:
        nxt: dict[tuple[int, int], float] = {}
        for (w, lo), p in states.items():
            for dw, dl, q in ((1, 0, c.win), (0, 1, c.loss), (0, 0, c.tie)):
                if q > 0:
                    key = (w + dw, lo + dl)
                    nxt[key] = nxt.get(key, 0.0) + p * q
        states = nxt
    n = len(categories)
    records = sorted(
        ((f"{w}-{lo}-{n - w - lo}", p) for (w, lo), p in states.items()),
        key=lambda item: -item[1],
    )
    win = math.fsum(p for (w, lo), p in states.items() if w > lo)
    loss = math.fsum(p for (w, lo), p in states.items() if w < lo)
    return MatchupOdds(
        win=win,
        tie=max(0.0, 1.0 - win - loss),
        loss=loss,
        expected_wins=math.fsum(c.win for c in categories),
        expected_losses=math.fsum(c.loss for c in categories),
        expected_ties=math.fsum(c.tie for c in categories),
        records=records,
    )

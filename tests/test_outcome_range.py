"""Range of outcomes: spread, win probabilities and the game logs behind them.

Three layers, none of which touches the network:

1. `outcomes.py` is pure arithmetic and is tested directly against hand-worked numbers.
2. `analyze_matchup` is run with every client fetch mocked, to pin the properties a reader
   relies on: the range narrows as games run out, a toss-up is 50%, a DOUBTFUL player widens
   the range, turnovers are won by the LOWER total, and the analysis survives a failed
   game-log fetch.
3. `get_player_game_logs` is run against an ESPN-shaped payload (synthetic, no account data).
"""

from __future__ import annotations

import json
import math
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

from espn_fantasy_basketball import analyze_matchup as analyze_matchup_tool
from espn_fantasy_basketball_mcp import outcomes
from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient
from espn_fantasy_basketball_mcp.models import (
    CurrentMatchup,
    MatchupAnalysis,
    MatchupTeam,
    Roster,
    RosterEntry,
    ScoringItem,
)
from espn_fantasy_basketball_mcp.outcomes import (
    LEAGUE_DISPERSION,
    PRIOR_GAMES,
    CategoryOutcome,
    ShootingLoad,
    category_outcome,
    dispersion_from_logs,
    dispersion_ratio,
    interval,
    matchup_odds,
    percentage_variance,
    total_variance,
)
from tests.fixture_espn import use_fixtures
from tests.test_matchup_analysis import (
    CURRENT_PERIOD,
    TODAY,
    _day,
    _entry,
    _schedule,
    _settings,
    _stats,
)

WINDOW = (TODAY - timedelta(days=3), TODAY + timedelta(days=3))


# --------------------------------------------------------------------------- pure maths
def test_dispersion_needs_enough_games_and_otherwise_uses_league_value():
    few = dispersion_from_logs([{"points": 30.0}] * 4)
    assert few.games == 4 and not few.from_logs
    assert dispersion_ratio(few, "points") == LEAGUE_DISPERSION["points"]
    assert dispersion_ratio(None, "steals") == LEAGUE_DISPERSION["steals"]
    assert dispersion_ratio(None, "doubleDoubles") == outcomes.DEFAULT_DISPERSION


def test_dispersion_is_shrunk_toward_the_league_value():
    # Ten identical games: own variance 0, so the ratio is the league value at half weight
    steady = dispersion_from_logs([{"points": 20.0, "blocks": 0.0}] * 10)
    assert steady.from_logs
    assert steady.ratios["points"] == pytest.approx(
        PRIOR_GAMES * LEAGUE_DISPERSION["points"] / (10 + PRIOR_GAMES)
    )
    assert "blocks" not in steady.ratios, "a stat he never records falls back to the league"
    # Alternating 10 and 30: mean 20, sample variance 1000/9, ratio 5.56 before shrinking
    streaky = dispersion_from_logs([{"points": p} for p in (10.0, 30.0) * 5])
    own = (1000 / 9) / 20
    assert streaky.ratios["points"] == pytest.approx(
        (10 * own + PRIOR_GAMES * LEAGUE_DISPERSION["points"]) / (10 + PRIOR_GAMES)
    )
    assert streaky.ratios["points"] > LEAGUE_DISPERSION["points"] > steady.ratios["points"]


def test_total_variance_matches_the_formula_by_hand():
    # 20 a game, dispersion 2 -> one game's variance 40. Three certain games from a 30-game
    # sample: 3 * 40 of noise + 3^2 * 40 / 30 for the error in the average.
    assert total_variance(20.0, 2.0, 3.0, 1.0, 30.0) == pytest.approx(120.0 + 12.0)
    assert total_variance(20.0, 2.0, 0.0, 1.0, 30.0) == 0.0
    assert total_variance(0.0, 2.0, 3.0, 1.0, 30.0) == 0.0


def test_a_doubtful_game_is_wider_than_a_certain_one_with_the_same_expectation():
    certain = total_variance(20.0, 2.0, 1.0, 1.0, 30.0)  # one game he plays
    doubtful = total_variance(20.0, 2.0, 1.0, 0.5, 30.0)  # two games at 50% each
    # 2 * (0.5 * 40 + 0.25 * 400) = 240, plus the same 40 / 30 for the average
    assert doubtful == pytest.approx(240.0 + 40.0 / 30.0)
    assert doubtful > certain


def test_a_small_sample_widens_the_range_and_is_floored():
    assert total_variance(20.0, 2.0, 3.0, 1.0, 5.0) > total_variance(20.0, 2.0, 3.0, 1.0, 50.0)
    # zero games played is treated as MIN_SAMPLE_GAMES, not a division by zero
    assert total_variance(20.0, 2.0, 3.0, 1.0, 0.0) == total_variance(
        20.0, 2.0, 3.0, 1.0, outcomes.MIN_SAMPLE_GAMES
    )


def test_percentage_variance_is_binomial_for_a_single_shooter():
    # 50% on 100 attempts over 4 games from a 40-game sample, no attempts banked yet:
    # 100 * 0.25 * (1 + 4/40) / 100^2
    load = ShootingLoad(
        made=50.0, attempted=100.0, attempt_variance=0.0, games=4.0, sample_games=40
    )
    assert percentage_variance([load], 0.0, 0.0) == pytest.approx(27.5 / 10000)
    # the same remaining shots matter less once 300 attempts are already in the book
    assert percentage_variance([load], 150.0, 300.0) < percentage_variance([load], 0.0, 0.0)
    assert percentage_variance([], 0.0, 0.0) == 0.0
    assert percentage_variance([], 40.0, 80.0) == 0.0, "nothing left to shoot: the % is final"


def test_percentage_variance_counts_volume_only_for_shooters_off_the_team_mark():
    # A 50% shooter on a 50% team: his attempt volume moving changes nothing
    on_mark = ShootingLoad(50.0, 100.0, attempt_variance=400.0, games=4.0, sample_games=40)
    quiet = ShootingLoad(50.0, 100.0, attempt_variance=0.0, games=4.0, sample_games=40)
    assert percentage_variance([on_mark], 0.0, 0.0) == pytest.approx(
        percentage_variance([quiet], 0.0, 0.0)
    )
    # A 90% shooter beside a 50% one: his volume now moves the team percentage
    good = ShootingLoad(90.0, 100.0, attempt_variance=400.0, games=4.0, sample_games=40)
    good_fixed = ShootingLoad(90.0, 100.0, attempt_variance=0.0, games=4.0, sample_games=40)
    assert percentage_variance([good, quiet], 0.0, 0.0) > percentage_variance(
        [good_fixed, quiet], 0.0, 0.0
    )


def test_category_outcome_is_even_at_a_zero_lead_and_sums_to_one():
    counting = category_outcome(0.0, 10.0, 0.5, "tie")
    assert counting.win == pytest.approx(counting.loss)
    assert counting.win + counting.tie + counting.loss == pytest.approx(1.0)
    assert 0 < counting.tie < 0.1 and counting.toss_up
    pct = category_outcome(0.0, 0.02, 0.0, "tie")
    assert pct.win == pytest.approx(0.5) and pct.tie == 0.0


def test_category_outcome_rises_with_the_lead_and_falls_with_the_spread():
    assert (
        category_outcome(10.0, 10.0, 0.5, "win").win > category_outcome(5.0, 10.0, 0.5, "win").win
    )
    assert (
        category_outcome(10.0, 5.0, 0.5, "win").win > category_outcome(10.0, 20.0, 0.5, "win").win
    )
    assert category_outcome(-10.0, 5.0, 0.5, "loss").win < 0.05
    # one standard deviation ahead in a percentage: the textbook 84.1%
    assert category_outcome(0.02, 0.02, 0.0, "win").win == pytest.approx(0.8413, abs=1e-4)


@pytest.mark.parametrize("result", ["win", "tie", "loss"])
def test_category_outcome_with_nothing_left_to_play_is_the_projected_result(result):
    done = category_outcome(3.0, 0.0, 0.5, result)
    assert (done.win, done.tie, done.loss) == tuple(
        float(result == r) for r in ("win", "tie", "loss")
    )


def test_matchup_odds_for_certain_categories():
    won, lost = CategoryOutcome(1.0, 0.0, 0.0), CategoryOutcome(0.0, 0.0, 1.0)
    odds = matchup_odds([won, won, lost])
    assert (odds.win, odds.tie, odds.loss) == (1.0, 0.0, 0.0)
    assert odds.records[0] == ("2-1-0", 1.0) and odds.expected_wins == 2.0
    level = matchup_odds([won, lost])
    assert level.tie == 1.0 and level.records[0][0] == "1-1-0"


def test_matchup_odds_for_three_coin_flips():
    coin = CategoryOutcome(0.5, 0.0, 0.5)
    odds = matchup_odds([coin, coin, coin])
    assert odds.win == pytest.approx(0.5) and odds.loss == pytest.approx(0.5)
    assert odds.expected_wins == pytest.approx(1.5)
    assert dict(odds.records) == pytest.approx(
        {"3-0-0": 0.125, "2-1-0": 0.375, "1-2-0": 0.375, "0-3-0": 0.125}
    )
    assert math.fsum(p for _, p in odds.records) == pytest.approx(1.0)


def test_matchup_odds_handles_no_categories():
    odds = matchup_odds([])
    assert odds.tie == 1.0 and odds.records == [("0-0-0", 1.0)]


def test_interval_is_symmetric_and_respects_bounds():
    low, high = interval(100.0, 10.0)
    assert (low + high) / 2 == pytest.approx(100.0)
    assert high - 100.0 == pytest.approx(12.8155, abs=1e-3), "80% interval is +/- 1.28 sd"
    assert interval(100.0, 10.0, low=95.0)[0] == 95.0
    assert interval(0.98, 0.05, 0.0, 1.0)[1] == 1.0
    assert interval(50.0, 0.0) == (50.0, 50.0)


# --------------------------------------------------------------------------- analysis
async def _analyze(
    monkeypatch,
    *,
    stat_ids: list[int],
    mine: list[RosterEntry],
    theirs: list[RosterEntry],
    my_games: dict[int, list[str]],
    their_games: dict[int, list[str]],
    per_game: dict[int, dict[str, float]],
    my_scores: dict[str, float],
    their_scores: dict[str, float],
    season_games: int = 20,
    logs: dict[int, list[dict[str, float]]] | Exception | None = None,
    reverse_stat_ids: tuple[int, ...] = (),
    scoring_type: str = "H2H_CATEGORY",
) -> MatchupAnalysis:
    """analyze_matchup for the current period with every fetch mocked."""
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    settings = _settings(stat_ids)
    settings.scoringSettings.scoringType = scoring_type
    settings.scoringSettings.scoringItems = [
        ScoringItem(statId=i, points=1.0, isReverseItem=i in reverse_stat_ids) for i in stat_ids
    ]
    matchup = CurrentMatchup(
        matchupId=1,
        scoringPeriod=30,
        yourTeam=MatchupTeam(teamId=1, teamName="Me", categoryScores=my_scores),
        opponentTeam=MatchupTeam(teamId=2, teamName="Them", categoryScores=their_scores),
        yourRoster=Roster(teamId=1, entries=mine),
        opponentRoster=Roster(teamId=2, entries=theirs),
    )

    async def fake_stats(player_ids, timeframe):
        if timeframe == "season":
            return [
                _stats(pid, "season", gamesPlayed=season_games, **values)
                for pid, values in per_game.items()
            ]
        return [_stats(pid, timeframe, **values) for pid, values in per_game.items()]

    async def fake_schedule(team_id, start, end, period):
        return _schedule(team_id, my_games if team_id == 1 else their_games)

    game_logs = (
        AsyncMock(side_effect=logs)
        if isinstance(logs, Exception)
        else AsyncMock(return_value=logs or {})
    )
    with (
        patch.object(client, "get_league_settings", AsyncMock(return_value=settings)),
        patch.object(client, "get_matchup_for_period", AsyncMock(return_value=matchup)),
        patch.object(client, "get_matchup_period_dates", AsyncMock(return_value=WINDOW)),
        patch.object(client, "get_roster_schedule_summary", side_effect=fake_schedule),
        patch.object(client, "get_player_stats", side_effect=fake_stats),
        patch.object(client, "get_player_game_logs", game_logs),
    ):
        return await client.analyze_matchup(team_id=1, matchup_period=CURRENT_PERIOD)


def _points_matchup(games: list[str], lead: float = 10.0, **kwargs):
    """One 20-point scorer a side with the same games left; I lead by `lead` points."""
    return {
        "stat_ids": [0],
        "mine": [_entry(101)],
        "theirs": [_entry(201)],
        "my_games": {101: games},
        "their_games": {201: games},
        "per_game": {101: {"points": 20.0}, 201: {"points": 20.0}},
        "my_scores": {"points": 300.0 + lead},
        "their_scores": {"points": 300.0},
        **kwargs,
    }


def _category(analysis: MatchupAnalysis, name: str):
    return next(c for c in analysis.categoryProjections if c.category == name)


@pytest.mark.asyncio
async def test_the_same_lead_is_safer_with_fewer_games_left(monkeypatch):
    one = await _analyze(monkeypatch, **_points_matchup([_day(1)]))
    three = await _analyze(monkeypatch, **_points_matchup([_day(1), _day(2), _day(3)]))
    p1, p3 = _category(one, "points"), _category(three, "points")
    assert p1.projectedLead == p3.projectedLead == pytest.approx(10.0)
    assert p1.winProbability > p3.winProbability > 0.5
    assert p1.leadStdDev < p3.leadStdDev
    width = lambda c: c.yourRange[1] - c.yourRange[0]  # noqa: E731
    assert width(p1) < width(p3)
    # hand check for one game: each side's variance is 2.55 * 20 * (1 + 1/20) = 53.55
    assert p1.leadStdDev == pytest.approx(math.sqrt(2 * 53.55), abs=0.05)
    assert one.outcomeRange.matchupWinProbability > three.outcomeRange.matchupWinProbability


@pytest.mark.asyncio
async def test_level_matchup_is_a_toss_up_and_probabilities_sum_to_one(monkeypatch):
    analysis = await _analyze(monkeypatch, **_points_matchup([_day(1), _day(2)], lead=0.0))
    points = _category(analysis, "points")
    assert points.winProbability == pytest.approx(points.lossProbability)
    assert points.winProbability + points.tieProbability + points.lossProbability == pytest.approx(
        1.0, abs=0.002
    )
    odds = analysis.outcomeRange
    assert odds.tossUpCategories == ["points"]
    assert odds.matchupWinProbability == pytest.approx(odds.matchupLossProbability)
    assert odds.confidenceLevel == 0.8 and "normal approximation" in odds.method
    assert any("Toss-ups" in note and "points" in note for note in analysis.strategyNotes)


@pytest.mark.asyncio
async def test_with_no_games_left_the_result_is_certain_and_the_range_is_a_point(monkeypatch):
    analysis = await _analyze(monkeypatch, **_points_matchup([_day(-1)]))
    points = _category(analysis, "points")
    assert (points.winProbability, points.tieProbability, points.lossProbability) == (1.0, 0.0, 0.0)
    assert points.yourRange == [310.0, 310.0] and points.opponentRange == [300.0, 300.0]
    assert points.leadStdDev == 0.0
    assert analysis.outcomeRange.matchupWinProbability == 1.0
    assert analysis.outcomeRange.mostLikelyRecords[0].record == "1-0-0"


@pytest.mark.asyncio
async def test_a_finished_percentage_has_a_point_range_at_the_rounded_projection(monkeypatch):
    """Live report: with no games left the rounded range sat a hair off the unrounded
    projection (0.4622 vs 0.46218...), which the live check read as inconsistent."""
    analysis = await _analyze(
        monkeypatch,
        stat_ids=[19],
        mine=[_entry(101)],
        theirs=[_entry(201)],
        my_games={101: [_day(-1)]},
        their_games={201: [_day(-1)]},
        per_game={
            101: {"fieldGoalsMade": 8.0, "fieldGoalsAttempted": 17.0},
            201: {"fieldGoalsMade": 7.0, "fieldGoalsAttempted": 15.0},
        },
        my_scores={"fieldGoalPercentage": 0.46218},
        their_scores={"fieldGoalPercentage": 0.49613},
    )
    fg = _category(analysis, "fieldGoalPercentage")
    assert fg.yourRange == [0.4622, 0.4622] and fg.opponentRange == [0.4961, 0.4961]
    assert abs(fg.yourRange[0] - fg.yourProjected) <= 5e-5
    assert (fg.winProbability, fg.lossProbability, fg.leadStdDev) == (0.0, 1.0, 0.0)
    note = next(n for n in analysis.strategyNotes if n.startswith("Expected category record"))
    assert "0% win, 0% tie, 100% loss" in note


@pytest.mark.asyncio
async def test_a_counting_range_never_drops_below_the_current_total(monkeypatch):
    # 2 points a game on top of 300 banked: the low end is clamped at 300, not below it
    setup = _points_matchup([_day(1)])
    setup["per_game"] = {101: {"points": 2.0}, 201: {"points": 2.0}}
    setup["season_games"] = 1
    points = _category(await _analyze(monkeypatch, **setup), "points")
    assert points.yourRange[0] >= 310.0 and points.opponentRange[0] >= 300.0


@pytest.mark.asyncio
async def test_turnovers_are_won_by_the_lower_total(monkeypatch):
    """Regression: more turnovers used to be projected (and counted) as a category win."""
    analysis = await _analyze(
        monkeypatch,
        stat_ids=[11],
        mine=[_entry(101)],
        theirs=[_entry(201)],
        my_games={101: [_day(1)]},
        their_games={201: [_day(1)]},
        per_game={101: {"turnovers": 4.0}, 201: {"turnovers": 2.0}},
        my_scores={"turnovers": 40.0},
        their_scores={"turnovers": 25.0},
    )
    turnovers = _category(analysis, "turnovers")
    assert turnovers.lowerIsBetter is True
    assert turnovers.yourProjected == pytest.approx(44.0), "raw totals are not flipped"
    assert turnovers.currentLead == pytest.approx(-15.0)
    assert turnovers.projectedLead == pytest.approx(-17.0)
    assert turnovers.projectedResult == "loss"
    assert analysis.categoriesLosing == ["turnovers"] and analysis.categoriesWinning == []
    assert (analysis.currentCategoryWins, analysis.currentCategoryLosses) == (0, 1)
    assert turnovers.winProbability < 0.01
    assert analysis.outcomeRange.matchupLossProbability > 0.99


@pytest.mark.asyncio
async def test_a_category_the_league_marks_reverse_is_also_lower_wins(monkeypatch):
    setup = _points_matchup([_day(1)], reverse_stat_ids=(0,))
    points = _category(await _analyze(monkeypatch, **setup), "points")
    assert points.lowerIsBetter and points.projectedResult == "loss"
    assert points.projectedLead == pytest.approx(-10.0)


@pytest.mark.asyncio
async def test_a_players_own_game_logs_set_his_spread(monkeypatch):
    games = [_day(1), _day(2)]
    steady = {pid: [{"points": 20.0}] * 20 for pid in (101, 201)}
    streaky = {pid: [{"points": p} for p in (5.0, 35.0) * 10] for pid in (101, 201)}
    calm = await _analyze(monkeypatch, **_points_matchup(games, logs=steady))
    wild = await _analyze(monkeypatch, **_points_matchup(games, logs=streaky))
    league = await _analyze(monkeypatch, **_points_matchup(games))
    sd = lambda a: _category(a, "points").leadStdDev  # noqa: E731
    assert sd(calm) < sd(league) < sd(wild)
    assert _category(calm, "points").winProbability > _category(wild, "points").winProbability
    assert calm.outcomeRange.varianceSource.startswith("2 of 2 players")
    assert league.outcomeRange.varianceSource.startswith("0 of 2 players")
    # the point estimate is the same whatever the spread
    assert _category(calm, "points").yourProjected == _category(wild, "points").yourProjected


@pytest.mark.asyncio
async def test_a_failed_game_log_fetch_falls_back_to_league_spread(monkeypatch):
    failed = await _analyze(
        monkeypatch, **_points_matchup([_day(1)], logs=RuntimeError("ESPN is down"))
    )
    league = await _analyze(monkeypatch, **_points_matchup([_day(1)]))
    assert _category(failed, "points").leadStdDev == _category(league, "points").leadStdDev
    assert failed.outcomeRange.varianceSource.startswith("0 of 2 players")


@pytest.mark.asyncio
async def test_a_doubtful_player_widens_the_range(monkeypatch):
    # Same expected games (1.0) for me either way: one certain game, or two at 50%
    certain = await _analyze(monkeypatch, **_points_matchup([_day(1)]))
    setup = _points_matchup([_day(1)])
    setup["mine"] = [_entry(101, injury="DOUBTFUL")]
    setup["my_games"] = {101: [_day(1), _day(2)]}
    doubtful = await _analyze(monkeypatch, **setup)
    a, b = _category(certain, "points"), _category(doubtful, "points")
    assert a.yourProjected == b.yourProjected == pytest.approx(330.0)
    assert b.leadStdDev > a.leadStdDev and b.winProbability < a.winProbability
    assert (b.yourRange[1] - b.yourRange[0]) > (a.yourRange[1] - a.yourRange[0])


@pytest.mark.asyncio
async def test_percentage_range_is_a_fraction_and_tighter_with_attempts_banked(monkeypatch):
    def setup(banked: float) -> dict:
        return {
            "stat_ids": [20],
            "mine": [_entry(101)],
            "theirs": [_entry(201)],
            "my_games": {101: [_day(1), _day(2)]},
            "their_games": {201: [_day(1), _day(2)]},
            "per_game": {
                101: {"freeThrowsMade": 8.0, "freeThrowsAttempted": 10.0},
                201: {"freeThrowsMade": 7.0, "freeThrowsAttempted": 10.0},
            },
            "my_scores": {"freeThrowPercentage": 0.8},
            "their_scores": {"freeThrowPercentage": 0.7},
        }

    fresh = await _analyze(monkeypatch, **setup(0.0))
    ft = _category(fresh, "freeThrowPercentage")
    assert ft.yourProjected == pytest.approx(0.8) and ft.projectedResult == "win"
    assert 0.0 <= ft.yourRange[0] < 0.8 < ft.yourRange[1] <= 1.0
    assert ft.tieProbability == 0.0 and 0.5 < ft.winProbability < 1.0
    # 20 attempts at 80%, 2 games on a 20-game sample: sqrt(20 * .16 * 1.1) / 20 = 0.0938
    assert (ft.yourRange[1] - ft.yourRange[0]) / 2 == pytest.approx(1.2816 * 0.0938, abs=0.002)


@pytest.mark.asyncio
async def test_fewer_season_games_means_a_wider_range(monkeypatch):
    games = [_day(1), _day(2), _day(3)]
    veteran = await _analyze(monkeypatch, **_points_matchup(games, season_games=60))
    rookie = await _analyze(monkeypatch, **_points_matchup(games, season_games=3))
    assert _category(rookie, "points").leadStdDev > _category(veteran, "points").leadStdDev


# --------------------------------------------------------------------------- fixtures e2e
@pytest.fixture
def espn(monkeypatch):
    monkeypatch.setenv("ESPN_LEAGUE_ID", "12345")
    monkeypatch.setenv("ESPN_YEAR", "2027")
    monkeypatch.setenv("ESPN_TEAM_ID", "8")
    monkeypatch.delenv("ESPN_S2", raising=False)
    monkeypatch.delenv("ESPN_SWID", raising=False)
    return use_fixtures(monkeypatch)


@pytest.mark.asyncio
async def test_analyze_matchup_tool_returns_the_range_as_json(espn):
    result = await analyze_matchup_tool(matchup_period=3)
    json.dumps(result)  # everything the tool returns must serialise
    odds = result["outcomeRange"]
    total = (
        odds["matchupWinProbability"]
        + odds["matchupTieProbability"]
        + odds["matchupLossProbability"]
    )
    assert total == pytest.approx(1.0, abs=0.002)
    assert odds["expectedCategoryWins"] + odds["expectedCategoryLosses"] + odds[
        "expectedCategoryTies"
    ] == pytest.approx(9.0, abs=0.02)
    assert len(odds["mostLikelyRecords"]) == 5
    for c in result["categoryProjections"]:
        low, high = c["yourRange"]
        assert low <= c["yourProjected"] <= high, c["category"]
        # the probability agrees with the point estimate about who is ahead
        if c["projectedResult"] == "win":
            assert c["winProbability"] > c["lossProbability"], c["category"]
        elif c["projectedResult"] == "loss":
            assert c["winProbability"] < c["lossProbability"], c["category"]
    turnovers = next(c for c in result["categoryProjections"] if c["category"] == "turnovers")
    assert turnovers["lowerIsBetter"] and turnovers["projectedResult"] == "loss"
    assert turnovers["yourProjected"] > turnovers["opponentProjected"]


@pytest.mark.asyncio
async def test_simulation_and_optimizer_carry_the_odds(espn):
    client = ESPNFantasyBasketballClient(12345, 2027)
    sim = await client.simulate_roster_move(8, drop_ids=[1004], add_ids=[9001], matchup_period=3)
    assert (sim.projectedRecordBefore, sim.projectedRecordAfter) == ("5-4-0", "7-2-0")
    assert sim.matchupWinProbabilityAfter > sim.matchupWinProbabilityBefore
    assert sim.expectedCategoryWinsAfter > sim.expectedCategoryWinsBefore
    assert any(line.startswith("Expected category wins") for line in sim.summary)
    assert all(d.winProbabilityBefore is not None for d in sim.categoryDeltas)
    assert all(d.winProbabilityAfter is not None for d in sim.categoryDeltas)

    best = await client.optimize_lineup(8, matchup_period=3)
    assert best.options, "the optimizer returns at least the current lineup"
    for option in best.options:
        assert option.matchupWinProbability is not None
        assert option.expectedCategoryWins is not None


# --------------------------------------------------------------------------- game logs
def _game(season: int, period: int, **stats: float) -> dict:
    return {
        "id": f"05{season}{period}",
        "seasonId": season,
        "scoringPeriodId": period,
        "statSourceId": 0,
        "statSplitTypeId": 5,
        "stats": {str(k).removeprefix("s"): v for k, v in stats.items()},
    }


GAME_LOG_PAYLOAD = {
    "players": [
        {
            "player": {
                "id": 501,
                "fullName": "Log Player",
                "stats": [
                    _game(2027, 3, s0=30, s6=8, s3=5, s13=11, s14=20, s40=35),
                    _game(2027, 9, s0=18, s6=4, s3=9, s11=3, s17=2, s40=31),
                    _game(2026, 170, s0=25, s1=2, s2=1, s15=6, s16=7, s40=33),
                    _game(2027, 6),  # did not play: ESPN sends an empty stat set
                    _game(2027, 7, s0=0, s40=0),  # dressed, no minutes
                    {  # season totals, not a game
                        "id": "002027",
                        "seasonId": 2027,
                        "scoringPeriodId": 0,
                        "statSourceId": 0,
                        "statSplitTypeId": 0,
                        "stats": {"0": 48, "40": 66},
                    },
                    {  # a projected game is not a played game
                        "id": "152027",
                        "seasonId": 2027,
                        "scoringPeriodId": 12,
                        "statSourceId": 1,
                        "statSplitTypeId": 5,
                        "stats": {"0": 22, "40": 32},
                    },
                ],
            }
        },
        {
            "player": {
                "id": 999,
                "fullName": "Not Asked For",
                "stats": [_game(2027, 3, s0=9, s40=20)],
            }
        },
        {"player": {"id": 502, "fullName": "No Games Yet"}},
    ]
}


@pytest.mark.asyncio
async def test_game_logs_are_parsed_newest_first_and_skip_games_not_played():
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    with patch.object(client, "_make_request", new_callable=AsyncMock) as request:
        request.return_value = GAME_LOG_PAYLOAD
        logs = await client.get_player_game_logs([501, 502], games=30)

    assert set(logs) == {501, 502}, "a player who was not asked for is ignored"
    assert logs[502] == []
    assert [g["points"] for g in logs[501]] == [18.0, 30.0, 25.0], "2027 periods 9, 3; then 2026"
    newest = logs[501][0]
    assert newest["assists"] == 9.0 and newest["turnovers"] == 3.0
    assert newest["threePointMade"] == 2.0 and newest["minutes"] == 31.0
    assert newest["blocks"] == 0.0, "a stat missing from the box score is zero"
    assert logs[501][1]["fieldGoalsMade"] == 11.0 and logs[501][1]["fieldGoalsAttempted"] == 20.0
    assert logs[501][2]["freeThrowsMade"] == 6.0 and logs[501][2]["freeThrowsAttempted"] == 7.0

    url, params, headers = request.call_args.args
    assert url.endswith("/seasons/2027/segments/0/leagues/12345")
    assert params == {"view": "kona_player_info"}
    sent = json.loads(headers["x-fantasy-filter"])["players"]
    assert sent["filterIds"]["value"] == [501, 502]
    assert sent["filterStatsForTopScoringPeriodIds"]["value"] == 30


@pytest.mark.asyncio
async def test_game_logs_are_capped_at_the_number_asked_for():
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    with patch.object(client, "_make_request", new_callable=AsyncMock) as request:
        request.return_value = GAME_LOG_PAYLOAD
        logs = await client.get_player_game_logs([501], games=2)
    assert [g["points"] for g in logs[501]] == [18.0, 30.0]


@pytest.mark.asyncio
async def test_game_logs_validate_input_and_skip_the_request_for_no_players():
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    with patch.object(client, "_make_request", new_callable=AsyncMock) as request:
        assert await client.get_player_game_logs([]) == {}
        with pytest.raises(ValueError):
            await client.get_player_game_logs([-1])
        with pytest.raises(ValueError):
            await client.get_player_game_logs([501], games=0)
        request.assert_not_called()


@pytest.mark.asyncio
async def test_the_suite_cannot_reach_the_network():
    """conftest.py blocks the client's real HTTP GET for every test."""
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    with pytest.raises(RuntimeError, match="network access attempted in tests"):
        await client._make_request("https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba")

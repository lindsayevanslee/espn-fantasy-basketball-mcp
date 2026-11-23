"""Regression tests for the feedback on the first live use of the range of outcomes
(23 November 2026). Four gaps were reported or visible in that session:

1. Comparing free agents meant one simulate_roster_move call per candidate: `rank_streamers`
   ranks a pool in one call, trying each candidate in every sensible slot.
2. A player listed OUT with ESPN's placeholder return date gets no games, and nothing said
   what happens if he plays: `outcomeRange.returnScenarios` re-runs the matchup with them.
3. The matchup win probability was quoted in a league whose standings count every category:
   `standingsUnit` / `standingsNote` say which figure matters, and the notes lead with it.
4. A move was judged on ESPN projections alone although one candidate's projection was far
   from his season: the simulator reports the alternate basis and flags such players.

Nothing here touches the network (conftest.py blocks it).
"""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

from espn_fantasy_basketball import rank_streamers as rank_streamers_tool
from espn_fantasy_basketball_mcp.analysis import _streamer_lineups, projection_gap_note
from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient
from espn_fantasy_basketball_mcp.constants import SLOT_BENCH
from espn_fantasy_basketball_mcp.models import (
    CurrentMatchup,
    MatchupTeam,
    PlayerOwnership,
    PlayerPoolEntry,
    Roster,
    RosterEntry,
    RosterLegality,
    StreamerRanking,
)
from tests.fixture_espn import use_fixtures
from tests.test_lineup_feedback import _out
from tests.test_matchup_analysis import (
    CURRENT_PERIOD,
    TODAY,
    _day,
    _entry,
    _schedule,
    _settings,
    _stats,
)
from tests.test_outcome_range import _analyze, _category, _points_matchup

WINDOW = (TODAY - timedelta(days=3), TODAY + timedelta(days=3))
PG, SG = 0, 1


def _with(entry: RosterEntry, **player_fields) -> RosterEntry:
    """A copy of a roster entry with fields of its player (or lineupLocked) changed."""
    locked = player_fields.pop("lineupLocked", entry.lineupLocked)
    player = entry.playerPoolEntry.player.model_copy(update=player_fields)
    return entry.model_copy(
        update={
            "playerPoolEntry": PlayerPoolEntry(id=entry.playerId, player=player),
            "lineupLocked": locked,
        }
    )


# --------------------------------------------------------------------------- placements
def _texts(options: list[tuple[str, list[RosterEntry]]]) -> list[str]:
    return [text for text, _ in options]


def test_daily_lock_candidate_only_goes_to_the_bench():
    kept, dropped, candidate = [_entry(101, PG)], _entry(102, SLOT_BENCH), _entry(301, SLOT_BENCH)
    options = _streamer_lineups(kept, dropped, candidate, weekly_lock=False, week_in_progress=False)
    assert _texts(options) == ["goes to the bench"]
    assert [e.playerId for e in options[0][1]] == [101, 301]


def test_candidate_takes_a_dropped_starters_slot_when_eligible():
    kept, dropped = [_entry(101, SG)], _entry(102, PG)
    eligible = _with(_entry(301, SLOT_BENCH), eligibleSlots=[PG])
    options = _streamer_lineups(kept, dropped, eligible, weekly_lock=True, week_in_progress=False)
    assert _texts(options) == ["takes Player 102's PG slot", "goes to the bench"]
    assert next(e for e in options[0][1] if e.playerId == 301).lineupSlotId == PG

    wrong_position = _with(_entry(301, SLOT_BENCH), eligibleSlots=[SG])
    options = _streamer_lineups(
        kept, dropped, wrong_position, weekly_lock=True, week_in_progress=False
    )
    # not eligible at PG: he takes SG and the SG (eligible anywhere) slides to the open PG slot
    assert _texts(options) == ["starts at SG; Player 101 moves to PG", "goes to the bench"]
    slots = {e.playerId: e.lineupSlotId for e in options[0][1]}
    assert slots == {101: PG, 301: SG}


def test_weekly_lock_tries_every_starting_slot_when_the_drop_is_on_the_bench():
    kept = [_entry(101, PG), _entry(103, SG)]
    candidate = _with(_entry(301, SLOT_BENCH), eligibleSlots=[SG])
    options = _streamer_lineups(
        kept, _entry(102, SLOT_BENCH), candidate, weekly_lock=True, week_in_progress=False
    )
    assert _texts(options) == ["starts at SG; Player 103 goes to the bench", "goes to the bench"]
    slots = {e.playerId: e.lineupSlotId for e in options[0][1]}
    assert slots == {101: PG, 103: SLOT_BENCH, 301: SG}


def test_locked_slots_are_left_alone_once_the_week_is_in_progress():
    locked_starter = _with(_entry(101, PG), lineupLocked=True)
    open_starter = _with(_entry(103, SG), lineupLocked=False)
    locked_drop = _with(_entry(102, PG), lineupLocked=True)
    options = _streamer_lineups(
        [locked_starter, open_starter],
        locked_drop,
        _entry(301, SLOT_BENCH),
        weekly_lock=True,
        week_in_progress=True,
    )
    assert _texts(options) == ["starts at SG; Player 103 goes to the bench", "goes to the bench"]


# --------------------------------------------------------------------------- ranking
async def _rank(
    monkeypatch,
    *,
    lock_type: str = "FIRSTGAME_WEEKLY",
    scoring_type: str = "H2H_CATEGORY",
    drop_id: int | None = 102,
    candidate_ids: list[int] | None = None,
    illegal: tuple[int, ...] = (),
    **kwargs,
) -> tuple[StreamerRanking, dict[str, AsyncMock]]:
    """rank_streamers for next week in a points-only league, every fetch mocked.

    My team: 101 starts at PG (5 points a game), 102 is on the bench. Opponent: 201, 20 a
    game. Free agents: 301 (25 a game), 302 (10 a game), 303 (30 a game but listed OUT).
    Everyone has three games.
    """
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    settings = _settings([0], lock_type=lock_type)
    settings.scoringSettings.scoringType = scoring_type
    period = CURRENT_PERIOD + 1
    matchup = CurrentMatchup(
        matchupId=1,
        scoringPeriod=30,
        yourTeam=MatchupTeam(teamId=1, teamName="Me", categoryScores={"points": 0.0}),
        opponentTeam=MatchupTeam(teamId=2, teamName="Them", categoryScores={"points": 0.0}),
        yourRoster=Roster(teamId=1, entries=[_entry(101, PG), _entry(102, SLOT_BENCH)]),
        opponentRoster=Roster(teamId=2, entries=[_entry(201, PG)]),
    )
    games = [_day(1), _day(2), _day(3)]
    points = {101: 5.0, 102: 4.0, 201: 20.0, 301: 25.0, 302: 10.0, 303: 30.0}
    season_points = {**points, 302: 6.0}  # 302's projection is 67% above his season
    free_agents = {
        301: _with(_entry(301, SLOT_BENCH), ownership=PlayerOwnership(percentOwned=40.0)),
        302: _entry(302, SLOT_BENCH),
        303: _entry(303, SLOT_BENCH, injury="OUT"),
    }

    async def fake_stats(player_ids, timeframe):
        source = season_points if timeframe == "season" else points
        extra = {"gamesPlayed": 20} if timeframe == "season" else {}
        return [_stats(pid, timeframe, points=source[pid], **extra) for pid in player_ids]

    async def fake_schedule(team_id, start, end, matchup_period):
        return _schedule(team_id, {101: games, 102: games} if team_id == 1 else {201: games})

    async def fake_subject_schedule(subjects, start, end, matchup_period, team_id=None):
        return _schedule(team_id or 1, {pid: games for pid, *_ in subjects})

    async def fake_entries(player_ids):
        return [free_agents[pid] for pid in player_ids if pid in free_agents]

    async def fake_legality(team_id, add_ids, drop_ids=None):
        bad = add_ids[0] in illegal
        return RosterLegality(
            teamId=team_id,
            rosterSizeNow=2,
            rosterSizeAfter=2,
            canMake=not bad,
            reasons=["5 centers against a limit of 4"] if bad else [],
        )

    mocks = {
        "get_free_agents": AsyncMock(
            return_value=[e.playerPoolEntry.player for e in free_agents.values()]
        ),
        "roster_entries_for_players": AsyncMock(side_effect=fake_entries),
        "check_roster_move": AsyncMock(side_effect=fake_legality),
        "_schedule_summary": AsyncMock(side_effect=fake_subject_schedule),
        "get_player_game_logs": AsyncMock(return_value={}),
    }
    with (
        patch.object(client, "get_league_settings", AsyncMock(return_value=settings)),
        patch.object(client, "get_matchup_for_period", AsyncMock(return_value=matchup)),
        patch.object(client, "get_matchup_period_dates", AsyncMock(return_value=WINDOW)),
        patch.object(client, "get_roster_schedule_summary", side_effect=fake_schedule),
        patch.object(client, "get_player_stats", side_effect=fake_stats),
        patch.multiple(client, **mocks),
    ):
        ranking = await client.rank_streamers(
            1, drop_id, candidate_ids, matchup_period=period, **kwargs
        )
    return ranking, mocks


@pytest.mark.asyncio
async def test_streamers_are_ranked_in_one_call_with_their_best_slot(monkeypatch):
    ranking, mocks = await _rank(monkeypatch)
    assert [o.playerName for o in ranking.options] == ["Player 301", "Player 302", "Player 303"]
    assert [o.rank for o in ranking.options] == [1, 2, 3]
    assert ranking.dropped == "Player 102 (102)" and ranking.candidatesConsidered == 3
    assert ranking.baselineProjectedRecord == "0-1-0", "5 a game against 20 a game"

    best = ranking.options[0]
    # the dropped player is on the bench under a weekly lock: the streamer must start to count
    assert best.placement == "starts at PG; Player 101 goes to the bench"
    assert (best.gamesThisPeriod, best.expectedGames, best.gamesInProjection) == (3, 3.0, 3.0)
    assert best.projectedRecord == "1-0-0" and best.categoriesFlipped == ["points: loss -> win"]
    assert best.expectedCategoryWinsDelta > 0.5 and best.matchupWinProbabilityDelta > 0.5
    assert best.winProbabilityChanges["points"] == pytest.approx(
        best.matchupWinProbabilityDelta, abs=0.01
    )
    assert best.percentOwned == 40.0 and best.perGame == {"points": 25.0}
    assert best.canAdd is True and best.legalityNotes == []

    out = ranking.options[2]
    assert out.availability == "OUT" and out.expectedGames == 0.0
    assert out.expectedCategoryWinsDelta <= 0.0, "30 a game is worth nothing if he does not play"

    # one batch of fetches for the pool, plus one legality check per option returned
    assert mocks["get_free_agents"].await_count == 1
    assert mocks["roster_entries_for_players"].await_count == 1
    assert mocks["_schedule_summary"].await_count == 1
    assert mocks["check_roster_move"].await_count == 3
    assert any("most-owned free agents" in note for note in ranking.notes)
    assert any("tried in every starting slot" in note for note in ranking.notes)


@pytest.mark.asyncio
async def test_streamer_ranking_flags_projection_gaps_and_gives_the_alternate_basis(monkeypatch):
    ranking, _ = await _rank(monkeypatch)
    by_name = {o.playerName: o for o in ranking.options}
    gap = by_name["Player 302"]
    assert "67% above the 6 he has averaged over 20 games" in gap.projectionNote
    assert by_name["Player 301"].projectionNote is None
    assert gap.alternateBasis == "season"
    # on season actuals he scores 6 a game, so he helps less than his projection says
    assert gap.alternateExpectedCategoryWinsDelta < gap.expectedCategoryWinsDelta
    assert any("far from this season's actuals for: Player 302" in n for n in ranking.notes)


@pytest.mark.asyncio
async def test_an_illegal_add_is_ranked_but_flagged(monkeypatch):
    ranking, _ = await _rank(monkeypatch, illegal=(301,))
    best = ranking.options[0]
    assert best.playerName == "Player 301" and best.canAdd is False
    assert best.legalityNotes == ["5 centers against a limit of 4"]
    assert any(n.startswith("Not allowed under the roster rules") for n in ranking.notes)


@pytest.mark.asyncio
async def test_specific_candidates_and_top_are_respected(monkeypatch):
    ranking, mocks = await _rank(monkeypatch, candidate_ids=[302, 301, 101, 999], top=1)
    assert [o.playerId for o in ranking.options] == [301]
    assert ranking.candidatesConsidered == 2
    mocks["get_free_agents"].assert_not_awaited()
    assert mocks["check_roster_move"].await_count == 1, "legality only for what is returned"
    assert "Already on your roster, ignored: [101]" in ranking.notes
    assert "Unknown player IDs, ignored: [999]" in ranking.notes


@pytest.mark.asyncio
async def test_daily_lock_and_matchup_leagues_are_described_as_such(monkeypatch):
    ranking, _ = await _rank(
        monkeypatch, lock_type="INDIVIDUAL_GAME", scoring_type="H2H_MOST_CATEGORIES"
    )
    assert ranking.rankedBy.startswith("matchup win probability")
    assert ranking.options[0].placement == "goes to the bench"
    assert ranking.options[0].gamesInProjection == 3.0, "bench games count under a daily lock"
    assert any(n.startswith("Daily lineup lock") for n in ranking.notes)


@pytest.mark.asyncio
async def test_ranking_without_a_drop_says_what_that_assumes(monkeypatch):
    ranking, mocks = await _rank(monkeypatch, drop_id=None)
    assert ranking.dropped is None
    assert any(n.startswith("No drop_id given") for n in ranking.notes)
    assert mocks["check_roster_move"].await_args.args[2] == []


@pytest.mark.asyncio
async def test_ranking_rejects_bad_arguments(monkeypatch):
    with pytest.raises(ValueError, match="not on team 1's roster"):
        await _rank(monkeypatch, drop_id=777)
    with pytest.raises(ValueError, match="pool_size must be between 1 and 50"):
        await _rank(monkeypatch, pool_size=0)
    with pytest.raises(ValueError, match="top must be between 1 and 50"):
        await _rank(monkeypatch, top=51)
    with pytest.raises(ValueError, match="At most 50 candidate_ids"):
        await _rank(monkeypatch, candidate_ids=list(range(1000, 1051)))
    with pytest.raises(ValueError):
        await _rank(monkeypatch, drop_id=-5)


@pytest.fixture
def espn(monkeypatch):
    monkeypatch.setenv("ESPN_LEAGUE_ID", "12345")
    monkeypatch.setenv("ESPN_YEAR", "2027")
    monkeypatch.setenv("ESPN_TEAM_ID", "8")
    monkeypatch.delenv("ESPN_S2", raising=False)
    monkeypatch.delenv("ESPN_SWID", raising=False)
    return use_fixtures(monkeypatch)


@pytest.mark.asyncio
async def test_rank_streamers_tool_end_to_end_on_fixtures(espn):
    result = await rank_streamers_tool(drop_id="1004", matchup_period=3, top="3")
    json.dumps(result)  # everything the tool returns must serialise
    assert result["dropped"] == "Benched Guy (1004)"
    assert result["rankedBy"].startswith("expected category wins")
    assert result["baselineProjectedRecord"] == "5-4-0"
    options = result["options"]
    assert [o["rank"] for o in options] == [1, 2, 3]
    deltas = [o["expectedCategoryWinsDelta"] for o in options]
    assert deltas == sorted(deltas, reverse=True), "best first"
    for o in options:
        assert o["gamesThisPeriod"] >= o["expectedGames"] >= 0
        assert o["canAdd"] in (True, False)
        assert o["expectedCategoryWins"] == pytest.approx(
            result["baselineExpectedCategoryWins"] + o["expectedCategoryWinsDelta"], abs=0.011
        )


# --------------------------------------------------------------------------- return scenarios
def _with_opponent(entry: RosterEntry, games: list[str]) -> dict:
    """The level points matchup, with the opponent's scorer replaced by `entry`."""
    setup = _points_matchup([_day(1), _day(2)], lead=0.0)
    setup["theirs"] = [entry]
    setup["their_games"] = {201: games}
    return setup


@pytest.mark.asyncio
async def test_a_placeholder_return_date_gets_a_what_if_scenario(monkeypatch):
    """Live report: Giannis was OUT with ESPN's next-game placeholder date, so the projection
    gave him no games and could not say what happens if he plays."""
    star = _out(201, PG, _day(1), "placeholder")
    analysis = await _analyze(monkeypatch, **_with_opponent(star, [_day(1), _day(2)]))
    points = _category(analysis, "points")
    assert points.opponentProjected == pytest.approx(300.0), "no games counted for him"
    assert points.projectedResult == "win"

    [scenario] = analysis.outcomeRange.returnScenarios
    assert (scenario.playerName, scenario.side) == ("Player 201", "opponent")
    assert scenario.returnDate == _day(1) and scenario.returnDateType == "placeholder"
    assert scenario.gamesAssumed == 2.0
    assert scenario.projectedRecord == "0-0-1", "2 games each at 20 a game: level"
    assert scenario.categoriesFlipped == ["points: win -> tie"]
    assert scenario.matchupWinProbability < analysis.outcomeRange.matchupWinProbability
    assert scenario.expectedCategoryWins < analysis.outcomeRange.expectedCategoryWins
    note = next(n for n in analysis.strategyNotes if n.startswith("What if the opponent's"))
    assert "Player 201" in note and "placeholder" in note and "2 game(s)" in note
    # the what-if never leaks into the projection itself
    assert analysis.opponentExpectedGames == 0.0


@pytest.mark.asyncio
async def test_your_own_returning_player_is_a_scenario_too(monkeypatch):
    setup = _points_matchup([_day(1), _day(2)], lead=0.0)
    setup["mine"] = [_out(101, PG, _day(2), "placeholder")]
    analysis = await _analyze(monkeypatch, **setup)
    [scenario] = analysis.outcomeRange.returnScenarios
    assert scenario.side == "you" and scenario.gamesAssumed == 1.0, "only the game on day 2"
    assert scenario.matchupWinProbability > analysis.outcomeRange.matchupWinProbability
    assert any(n.startswith("What if your Player 101") for n in analysis.strategyNotes)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("entry", "why"),
    [
        (_out(201, PG, _day(1), "reported"), "a reported date is already counted"),
        (_out(201, PG, _day(9), "placeholder"), "the return is after the window"),
        (_out(201, PG, None), "no return date to assume"),
        (_entry(201, PG), "a healthy player needs no what-if"),
    ],
)
async def test_no_scenario_when_nothing_would_change(monkeypatch, entry, why):
    analysis = await _analyze(monkeypatch, **_with_opponent(entry, [_day(1), _day(2)]))
    assert analysis.outcomeRange.returnScenarios == [], why
    assert not any(n.startswith("What if") for n in analysis.strategyNotes), why


# --------------------------------------------------------------------------- standings
@pytest.mark.asyncio
async def test_each_category_league_leads_with_the_category_record(monkeypatch):
    analysis = await _analyze(monkeypatch, **_points_matchup([_day(1)]))
    odds = analysis.outcomeRange
    assert odds.standingsUnit == "categories"
    assert "expectedCategoryWins is the figure that moves your standing" in odds.standingsNote
    note = next(n for n in analysis.strategyNotes if "odds of taking more categories" in n)
    assert note.startswith("Expected category record ")
    assert "this league's standings count every category" in note


@pytest.mark.asyncio
async def test_most_categories_league_leads_with_the_matchup_odds(monkeypatch):
    setup = _points_matchup([_day(1)], scoring_type="H2H_MOST_CATEGORIES")
    analysis = await _analyze(monkeypatch, **setup)
    assert analysis.outcomeRange.standingsUnit == "matchups"
    assert "matchupWinProbability is the figure" in analysis.outcomeRange.standingsNote
    assert any(n.startswith("Estimated matchup odds:") for n in analysis.strategyNotes)


@pytest.mark.asyncio
async def test_unknown_scoring_type_makes_no_claim_about_standings(monkeypatch):
    analysis = await _analyze(monkeypatch, **_points_matchup([_day(1)], scoring_type="ROTO"))
    assert analysis.outcomeRange.standingsUnit is None
    assert analysis.outcomeRange.standingsNote is None


# --------------------------------------------------------------------------- second opinion
def test_projection_gap_note_needs_a_real_gap_and_enough_games():
    def stats(projected: float, season: float, games: int) -> dict:
        return {
            "projections": {7: _stats(7, "projections", points=projected)},
            "season": {7: _stats(7, "season", points=season, gamesPlayed=games)},
        }

    # live report: Wiggins projected at 15.7 against 9.2 actual
    note = projection_gap_note(stats(15.7, 9.2, 14), 7)
    assert "ESPN projects 15.7 points a game, 71% above the 9.2" in note
    assert "over 14 games" in note
    assert "below" in projection_gap_note(stats(8.0, 16.0, 14), 7)
    assert projection_gap_note(stats(10.0, 9.0, 14), 7) is None, "11% is ordinary"
    assert projection_gap_note(stats(15.7, 9.2, 4), 7) is None, "four games is too few"
    assert projection_gap_note(stats(15.7, 0.0, 14), 7) is None
    assert projection_gap_note({"projections": {}, "season": {}}, 7) is None


@pytest.mark.asyncio
async def test_simulation_reports_the_move_on_the_alternate_basis(espn):
    client = ESPNFantasyBasketballClient(12345, 2027)
    sim = await client.simulate_roster_move(8, drop_ids=[1004], add_ids=[9001], matchup_period=3)
    assert sim.alternateBasis == "season"
    assert sim.alternateProjectedRecordBefore and sim.alternateProjectedRecordAfter
    assert sim.alternateExpectedCategoryWinsAfter > sim.alternateExpectedCategoryWinsBefore
    assert any(line.startswith("On the season basis: projected record") for line in sim.summary)
    assert any("standings count every category" in line for line in sim.summary)

    season = await client.simulate_roster_move(
        8, drop_ids=[1004], add_ids=[9001], matchup_period=3, basis="season"
    )
    assert season.alternateBasis == "projections"

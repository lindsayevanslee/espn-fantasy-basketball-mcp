"""Regression tests for the lineup feedback on the live league (15 November 2026).

1. Weekly-lock leagues: only starting-slot players count in the projection. Bench players
   are still ranked for start/sit and listed under benchPlayersNotCounted; a simulated add
   takes a dropped starter's slot when it can, else sits on the bench and counts nothing.
2. Returning players: a player listed OUT with a reported return date inside the window
   gets the games on and after that date, not zero. Placeholder, stale and out-of-window
   dates still give zero, and every case says why.
3. Centre limit: the verdict's basis is configurable (ESPN_POSITION_LIMIT_BASIS), the
   current roster is used as evidence about which count ESPN enforces, and the eligibility
   warning says what to do if ESPN rejects the add.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from espn_fantasy_basketball_mcp.analysis import expected_games_for
from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient
from espn_fantasy_basketball_mcp.constants import SLOT_BENCH, SLOT_IR
from espn_fantasy_basketball_mcp.dates import (
    games_remaining_by_player,
    remaining_game_dates_by_player,
)
from espn_fantasy_basketball_mcp.models import (
    CurrentMatchup,
    MatchupTeam,
    OverallRecord,
    Player,
    PlayerPoolEntry,
    Roster,
    RosterEntry,
    RosterLegality,
    Team,
    TeamRecord,
)
from tests.test_matchup_analysis import (
    CURRENT_PERIOD,
    NOW,
    TODAY,
    _day,
    _entry,
    _schedule,
    _settings,
    _stats,
)

WINDOW = (TODAY - timedelta(days=3), TODAY + timedelta(days=3))


def _out(
    pid: int,
    slot: int,
    return_date: str | None,
    return_type: str | None = "reported",
    details: str | None = "Knee - Sprain (left)",
) -> RosterEntry:
    """A roster entry listed OUT with an ESPN return date."""
    entry = _entry(pid, slot=slot, injury="OUT")
    player = entry.playerPoolEntry.player.model_copy(
        update={
            "injuryReturnDate": return_date,
            "injuryReturnDateType": return_type if return_date else None,
            "injuryDetails": details,
        }
    )
    return entry.model_copy(update={"playerPoolEntry": PlayerPoolEntry(id=pid, player=player)})


def _dates(*offsets: int) -> list[date]:
    return [TODAY + timedelta(days=o) for o in offsets]


# ------------------------------------------------------------------ dates
def test_remaining_game_dates_feed_the_count():
    schedule = _schedule(1, {1: [_day(-1), _day(0), _day(1), _day(9)]})
    by_date = remaining_game_dates_by_player(schedule, NOW, WINDOW[1])
    assert by_date == {1: _dates(0, 1)}, "yesterday is played; day 9 is next period"
    assert games_remaining_by_player(schedule, NOW, WINDOW[1]) == {1: 2}


# ------------------------------------------------------------------ 2. returning players
def test_out_player_with_reported_return_inside_window_keeps_later_games():
    entry = _out(1, slot=3, return_date=_day(2))
    g = expected_games_for(entry, _dates(1, 2, 3), WINDOW[1], TODAY, weekly_lock=False)
    assert (g.availability, g.scheduled, g.playable, g.counted) == ("OUT", 3, 2.0, 2.0)
    assert g.slot_scores
    assert g.note == (
        f"Knee - Sprain (left); expected return {_day(2)}: 2 of 3 game(s) on or after it count"
    )


@pytest.mark.parametrize(
    ("return_date", "return_type", "why"),
    [
        (_day(2), "placeholder", "ESPN's next-game placeholder"),
        (_day(0), "reported", "has passed but the status is still OUT"),
        (_day(-1), "reported", "has passed but the status is still OUT"),
        (_day(5), "reported", "is after this matchup period"),
        (None, None, None),
    ],
)
def test_out_player_gets_no_games_unless_the_return_date_is_usable(return_date, return_type, why):
    entry = _out(1, slot=3, return_date=return_date, return_type=return_type)
    g = expected_games_for(entry, _dates(1, 2, 3), WINDOW[1], TODAY, weekly_lock=False)
    assert g.playable == 0.0 and g.counted == 0.0
    if why is None:
        assert g.note == "Knee - Sprain (left)"
    else:
        assert why in g.note and g.note.startswith("Knee - Sprain (left);")


def test_return_date_without_a_window_bound_still_counts_later_games():
    entry = _out(1, slot=3, return_date=_day(2), details=None)
    g = expected_games_for(entry, _dates(1, 2), None, TODAY, weekly_lock=False)
    assert (
        g.playable == 1.0
        and g.note == f"expected return {_day(2)}: 1 of 2 game(s) on or after it count"
    )


@pytest.mark.asyncio
async def test_returning_starter_projects_partial_games_and_is_ranked(monkeypatch):
    """OUT with a return date two days out: the later games count, the warning says so, and
    the player is ranked on his line instead of parked at priority 1."""
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    settings = _settings([0])
    my_roster = Roster(
        teamId=1,
        entries=[_entry(101), _out(102, slot=1, return_date=_day(2))],
    )
    their_roster = Roster(teamId=2, entries=[_entry(201)])
    matchup = CurrentMatchup(
        matchupId=1,
        scoringPeriod=30,
        yourTeam=MatchupTeam(teamId=1, teamName="Me", categoryScores={"points": 100.0}),
        opponentTeam=MatchupTeam(teamId=2, teamName="Them", categoryScores={"points": 100.0}),
        yourRoster=my_roster,
        opponentRoster=their_roster,
    )
    three = [_day(1), _day(2), _day(3)]
    schedules = {1: _schedule(1, {101: three, 102: three}), 2: _schedule(2, {201: three})}
    projections = [_stats(pid, "projections", points=10.0) for pid in (101, 102, 201)]

    async def fake_stats(player_ids, timeframe):
        return projections

    async def fake_schedule(team_id, start, end, period):
        return schedules[team_id]

    with (
        patch.object(client, "get_league_settings", AsyncMock(return_value=settings)),
        patch.object(client, "get_matchup_for_period", AsyncMock(return_value=matchup)),
        patch.object(client, "get_matchup_period_dates", AsyncMock(return_value=WINDOW)),
        patch.object(client, "get_roster_schedule_summary", side_effect=fake_schedule),
        patch.object(client, "get_player_stats", side_effect=fake_stats),
    ):
        analysis = await client.analyze_matchup(team_id=1, matchup_period=CURRENT_PERIOD)

    points = next(c for c in analysis.categoryProjections if c.category == "points")
    assert points.yourProjected == pytest.approx(100 + 3 * 10 + 2 * 10), "2 of 102's 3 games"
    assert analysis.yourGamesRemaining == 6 and analysis.yourExpectedGames == 5.0
    assert analysis.expectedGamesBreakdown == [
        f"Player 102: 3 scheduled, 2 expected (OUT; Knee - Sprain (left); expected return "
        f"{_day(2)}: 2 of 3 game(s) on or after it count)",
        "6 scheduled - 1 discounted = 5 expected",
    ]
    rec = next(r for r in analysis.playerRecommendations if r.playerId == 102)
    assert rec.availability == "OUT" and rec.expectedGames == 2.0 and rec.gamesInProjection == 2.0
    assert rec.priority > 1, "ranked on his line, not parked with the unavailable"
    assert "Status: OUT (Knee - Sprain (left); expected return" in rec.reasoning
    healthy = next(r for r in analysis.playerRecommendations if r.playerId == 101)
    assert rec.priority < healthy.priority, "a returning player ranks below a healthy one"
    [warning] = analysis.lineupWarnings
    assert warning.startswith("Player 102 (SG) is OUT (Knee - Sprain (left); expected return")
    assert "2 of 3 game(s) on or after it count); check status before tip-off" in warning
    assert "keeps the games on and after that date" in analysis.projectionMethod


# ------------------------------------------------------------------ 1. bench under a weekly lock
@pytest.mark.parametrize(
    ("slot", "weekly", "counted", "scores"),
    [
        (SLOT_BENCH, True, 0.0, False),
        (SLOT_BENCH, False, 2.0, True),
        (0, True, 2.0, True),
        (SLOT_IR, True, 0.0, False),
        (SLOT_IR, False, 0.0, False),
    ],
)
def test_only_scoring_slots_count(slot, weekly, counted, scores):
    g = expected_games_for(_entry(1, slot=slot), _dates(1, 2), WINDOW[1], TODAY, weekly)
    assert (g.scheduled, g.playable if slot != SLOT_IR else 0.0, g.counted, g.slot_scores) == (
        2,
        2.0 if slot != SLOT_IR else 0.0,
        counted,
        scores,
    )
    if slot == SLOT_BENCH and weekly:
        assert g.note == "on the bench: bench games do not score under the weekly lineup lock"
    elif slot != SLOT_IR:
        assert g.note is None


def _weekly_fixture(lock_type: str, period: int):
    settings = _settings([0], lock_type=lock_type)
    bench = _entry(103, slot=SLOT_BENCH).model_copy(update={"lineupLocked": False})
    my_roster = Roster(teamId=1, entries=[_entry(101), _entry(102, slot=1, injury="OUT"), bench])
    their_roster = Roster(teamId=2, entries=[_entry(201), _entry(202, slot=SLOT_BENCH)])
    matchup = CurrentMatchup(
        matchupId=1,
        scoringPeriod=30,
        yourTeam=MatchupTeam(teamId=1, teamName="Me", categoryScores={"points": 100.0}),
        opponentTeam=MatchupTeam(teamId=2, teamName="Them", categoryScores={"points": 100.0}),
        yourRoster=my_roster,
        opponentRoster=their_roster,
    )
    two = [_day(1), _day(2)]
    schedules = {
        1: _schedule(1, {101: two, 102: two, 103: two}),
        2: _schedule(2, {201: two, 202: two}),
    }
    return settings, matchup, schedules


async def _analyze(client, settings, matchup, schedules, period, **kwargs):
    projections = [_stats(pid, "projections", points=10.0) for pid in (101, 102, 103, 201, 202)]

    async def fake_stats(player_ids, timeframe):
        return projections

    async def fake_schedule(team_id, start, end, period_):
        return schedules[team_id]

    with (
        patch.object(client, "get_league_settings", AsyncMock(return_value=settings)),
        patch.object(client, "get_matchup_for_period", AsyncMock(return_value=matchup)),
        patch.object(client, "get_matchup_period_dates", AsyncMock(return_value=WINDOW)),
        patch.object(client, "get_roster_schedule_summary", side_effect=fake_schedule),
        patch.object(client, "get_player_stats", side_effect=fake_stats),
    ):
        return await client.analyze_matchup(team_id=1, matchup_period=period, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("lock_type", ["FIRSTGAME_WEEKLY", "INDIVIDUAL_FIRSTGAME_WEEKLY"])
async def test_weekly_lock_counts_starters_only_but_still_ranks_the_bench(monkeypatch, lock_type):
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    settings, matchup, schedules = _weekly_fixture(lock_type, CURRENT_PERIOD)
    analysis = await _analyze(client, settings, matchup, schedules, CURRENT_PERIOD)

    points = next(c for c in analysis.categoryProjections if c.category == "points")
    assert points.yourProjected == pytest.approx(120.0), "only 101 (2 games) scores"
    assert points.opponentProjected == pytest.approx(120.0), "their bench is excluded too"
    assert analysis.yourGamesRemaining == 6 and analysis.yourExpectedGames == 2.0
    assert analysis.expectedGamesBreakdown == [
        "Player 102: 2 scheduled, 0 expected (OUT)",
        "Player 103: 2 scheduled, 0 expected (ACTIVE, not counted; on the bench: bench games "
        "do not score under the weekly lineup lock)",
        "6 scheduled - 4 discounted = 2 expected",
    ]
    assert analysis.benchPlayersNotCounted == ["Player 103: 2 playable game(s)"]
    assert any(
        n.startswith("Weekly lineup lock: 1 bench player(s)") for n in analysis.strategyNotes
    )
    assert "Only players in starting slots count" in analysis.projectionMethod

    by_id = {r.playerId: r for r in analysis.playerRecommendations}
    bench = by_id[103]
    assert bench.expectedGames == 2.0 and bench.gamesInProjection == 0.0
    assert bench.countsInProjection is False
    assert bench.priority == by_id[101].priority, "ranked on his line like any starter"
    assert "slot not yet locked" in bench.reasoning, "lineupLocked=False: can still be started"
    assert bench.availabilityNote == (
        "on the bench: bench games do not score under the weekly lineup lock"
    )
    their_bench = next(p for p in analysis.opponentPlayers if p.playerId == 202)
    assert their_bench.expectedGames == 2.0 and their_bench.gamesInProjection == 0.0
    assert their_bench.countsInProjection is False


@pytest.mark.asyncio
async def test_weekly_lock_bench_message_follows_the_lock_state(monkeypatch):
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    settings, matchup, schedules = _weekly_fixture("FIRSTGAME_WEEKLY", CURRENT_PERIOD)

    # next week: the planned lineup is not locked yet
    upcoming = await _analyze(client, settings, matchup, schedules, CURRENT_PERIOD + 1)
    bench = next(r for r in upcoming.playerRecommendations if r.playerId == 103)
    assert "started before the week's first game" in bench.reasoning

    # this week, every slot locked at the first game
    locked = matchup.yourRoster.entries[2].model_copy(update={"lineupLocked": True})
    matchup.yourRoster.entries[2] = locked
    current = await _analyze(client, settings, matchup, schedules, CURRENT_PERIOD)
    bench = next(r for r in current.playerRecommendations if r.playerId == 103)
    assert "locked for the week: his games do not count this period" in bench.reasoning


@pytest.mark.asyncio
async def test_daily_lock_still_counts_the_bench(monkeypatch):
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    settings, matchup, schedules = _weekly_fixture("INDIVIDUAL_GAME", CURRENT_PERIOD)
    analysis = await _analyze(client, settings, matchup, schedules, CURRENT_PERIOD)
    points = next(c for c in analysis.categoryProjections if c.category == "points")
    assert points.yourProjected == pytest.approx(140.0), "101 and bench 103, 2 games each"
    assert analysis.benchPlayersNotCounted == []
    assert "Every non-IR player counts, bench included" in analysis.projectionMethod
    bench = next(r for r in analysis.playerRecommendations if r.playerId == 103)
    assert bench.countsInProjection and bench.gamesInProjection == 2.0


# ------------------------------------------------------------------ 1b. simulated adds
def _added_entry(pid: int) -> RosterEntry:
    return _entry(pid, slot=SLOT_BENCH).model_copy(
        update={
            "playerPoolEntry": PlayerPoolEntry(
                id=pid,
                player=Player(
                    id=pid,
                    fullName=f"Streamer {pid}",
                    defaultPositionId=2,
                    proTeamId=2,
                    proTeamAbbrev="BOS",
                ),
            )
        }
    )


async def _simulate(client, settings, matchup, schedules, period, drops, adds):
    projections = [
        _stats(pid, "projections", points=10.0) for pid in (101, 102, 103, 201, 202, 901)
    ]
    legality = RosterLegality(
        teamId=1,
        canMake=True,
        rosterSizeNow=3,
        rosterSizeAfter=3,
        warnings=["3 players are eligible at C against a limit of 2; allowed if ..."],
    )

    async def fake_stats(player_ids, timeframe):
        return projections

    async def fake_schedule(team_id, start, end, period_):
        return schedules[team_id]

    async def fake_summary(subjects, start, end, period_, team_id=None):
        return _schedule(1, {pid: [_day(1), _day(2)] for pid, _, _, _ in subjects})

    with (
        patch.object(client, "get_league_settings", AsyncMock(return_value=settings)),
        patch.object(client, "get_matchup_for_period", AsyncMock(return_value=matchup)),
        patch.object(client, "get_matchup_period_dates", AsyncMock(return_value=WINDOW)),
        patch.object(client, "get_roster_schedule_summary", side_effect=fake_schedule),
        patch.object(client, "get_player_stats", side_effect=fake_stats),
        patch.object(
            client,
            "roster_entries_for_players",
            AsyncMock(return_value=[_added_entry(pid) for pid in adds]),
        ),
        patch.object(client, "_schedule_summary", side_effect=fake_summary),
        patch.object(client, "check_roster_move", AsyncMock(return_value=legality)),
    ):
        return await client.simulate_roster_move(1, drops, adds, period)


@pytest.mark.asyncio
async def test_simulated_add_takes_a_dropped_starters_slot_next_week(monkeypatch):
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    settings, matchup, schedules = _weekly_fixture("FIRSTGAME_WEEKLY", CURRENT_PERIOD + 1)
    sim = await _simulate(client, settings, matchup, schedules, CURRENT_PERIOD + 1, [102], [901])
    assert sim.placements == ["Streamer 901 takes Player 102's SG slot"]
    [added] = sim.addedPlayers
    assert added.lineupSlotName == "SG" and added.countsInProjection
    assert added.gamesInProjection == 2.0
    assert (sim.expectedGamesBefore, sim.expectedGamesAfter) == (2.0, 4.0)
    assert not any(line.startswith("Weekly lineup lock") for line in sim.summary)
    assert "Slots: Streamer 901 takes Player 102's SG slot" in sim.summary
    # legality warnings reach the summary, not only the nested object
    assert any(line.startswith("Legality warnings: 3 players are eligible") for line in sim.summary)


@pytest.mark.asyncio
async def test_simulated_add_for_a_dropped_bench_player_counts_nothing_under_weekly_lock(
    monkeypatch,
):
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    settings, matchup, schedules = _weekly_fixture("FIRSTGAME_WEEKLY", CURRENT_PERIOD)
    sim = await _simulate(client, settings, matchup, schedules, CURRENT_PERIOD, [103], [901])
    assert sim.placements == ["Streamer 901 goes to the bench"]
    [added] = sim.addedPlayers
    assert added.countsInProjection is False and added.gamesInProjection == 0.0
    assert added.expectedGames == 2.0, "he would play; his games just do not score"
    assert sim.expectedGamesAfter == sim.expectedGamesBefore == 2.0
    caveat = next(line for line in sim.summary if line.startswith("Weekly lineup lock"))
    assert f"until matchup period {CURRENT_PERIOD + 1}" in caveat
    assert "give him no games this period" in caveat


@pytest.mark.asyncio
async def test_simulated_add_takes_an_unlocked_slot_this_week(monkeypatch):
    """INDIVIDUAL_FIRSTGAME_WEEKLY mid-week: a dropped starter whose slot ESPN says is not
    locked can be replaced, so the added player counts."""
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    settings, matchup, schedules = _weekly_fixture("INDIVIDUAL_FIRSTGAME_WEEKLY", CURRENT_PERIOD)
    starter = matchup.yourRoster.entries[1]
    matchup.yourRoster.entries[1] = starter.model_copy(update={"lineupLocked": False})
    sim = await _simulate(client, settings, matchup, schedules, CURRENT_PERIOD, [102], [901])
    assert sim.placements == ["Streamer 901 takes Player 102's SG slot"]
    assert sim.expectedGamesAfter == 4.0

    # the same drop with the slot locked (or the flag unknown) leaves the add on the bench
    matchup.yourRoster.entries[1] = starter.model_copy(update={"lineupLocked": True})
    locked = await _simulate(client, settings, matchup, schedules, CURRENT_PERIOD, [102], [901])
    assert locked.placements == ["Streamer 901 goes to the bench"]
    assert locked.expectedGamesAfter == 2.0


@pytest.mark.asyncio
async def test_daily_lock_simulation_is_unchanged_by_slot_placement(monkeypatch):
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    settings, matchup, schedules = _weekly_fixture("INDIVIDUAL_GAME", CURRENT_PERIOD)
    sim = await _simulate(client, settings, matchup, schedules, CURRENT_PERIOD, [103], [901])
    assert sim.placements == ["Streamer 901 goes to the bench"]
    assert sim.expectedGamesAfter == sim.expectedGamesBefore == 4.0, "bench counts daily"
    assert not any(line.startswith("Weekly lineup lock") for line in sim.summary)


# ------------------------------------------------------------------ 3. centre limit
def _player(pid: int, position: str, eligible: list[int], on_team: int | None = None):
    pos_id = {"PG": 1, "SG": 2, "SF": 3, "PF": 4, "C": 5}[position]
    return RosterEntry(
        playerId=pid,
        lineupSlotId=SLOT_BENCH,
        playerPoolEntry=PlayerPoolEntry(
            id=pid,
            onTeamId=on_team,
            player=Player(
                id=pid,
                fullName=f"Player {pid}",
                defaultPositionId=pos_id,
                defaultPosition=position,
                eligibleSlots=eligible,
                proTeamId=2,
                proTeamAbbrev="BOS",
            ),
        ),
    )


def _legality_patches(client, roster_entries, adds, center_limit: int):
    settings = _settings([0])
    settings.rosterSettings.positionLimitNames = {
        "PG": -1,
        "SG": -1,
        "SF": -1,
        "PF": -1,
        "C": center_limit,
    }
    settings.rosterSettings.rosterSize = 13
    team = Team(
        id=1,
        abbrev="ME",
        name="Me",
        record=TeamRecord(overall=OverallRecord(wins=1, losses=0, ties=0)),
        acquisitionsRemainingThisMatchup=5,
    )
    return (
        patch.object(client, "get_league_settings", AsyncMock(return_value=settings)),
        patch.object(
            client,
            "get_team_roster",
            AsyncMock(return_value=Roster(teamId=1, entries=roster_entries)),
        ),
        patch.object(client, "get_league_teams", AsyncMock(return_value=[team])),
        patch.object(client, "roster_entries_for_players", AsyncMock(return_value=adds)),
    )


# Two primary centres plus two PF/C forwards: 2 by primary, 4 by eligibility.
ROSTER = [
    _player(1, "C", [4, 11, 12]),
    _player(2, "C", [4, 11, 12]),
    _player(3, "PF", [3, 4, 6, 11, 12]),
    _player(4, "PF", [3, 4, 6, 11, 12]),
    _player(5, "PG", [0, 5, 11, 12]),
]
ADD_FC = [_player(9, "SF", [2, 4, 6, 11, 12])]  # a forward also eligible at C


@pytest.mark.asyncio
async def test_primary_basis_allows_the_add_and_warns_about_eligibility(monkeypatch):
    monkeypatch.delenv("ESPN_POSITION_LIMIT_BASIS", raising=False)
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    patches = _legality_patches(client, ROSTER, ADD_FC, center_limit=4)
    with patches[0], patches[1], patches[2], patches[3]:
        result = await client.check_roster_move(1, [9])
    assert result.canMake and result.positionLimitBasisSetting == "primary"
    assert result.positionCountsNowByDefaultPosition["C"] == 2
    assert result.positionCountsNowByEligibility["C"] == 4
    assert result.positionCountsAfterByDefaultPosition["C"] == 2
    assert result.positionCountsAfterByEligibility["C"] == 5
    [warning] = result.warnings
    assert warning.startswith("5 players are eligible at C against a limit of 4")
    assert "set ESPN_POSITION_LIMIT_BASIS=eligibility" in warning
    assert result.positionLimitEvidence == [], "4 eligible against 4 proves nothing"
    assert "keys positionLimits by defaultPositionId" in result.positionLimitBasis


@pytest.mark.asyncio
async def test_current_roster_over_the_limit_by_eligibility_is_evidence(monkeypatch):
    monkeypatch.delenv("ESPN_POSITION_LIMIT_BASIS", raising=False)
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    patches = _legality_patches(client, ROSTER, ADD_FC, center_limit=3)
    with patches[0], patches[1], patches[2], patches[3]:
        result = await client.check_roster_move(1, [9])
    assert result.canMake, "2 primary centres against 3"
    assert result.positionLimitEvidence == [
        "Your current roster has 4 players eligible at C against a limit of 3 and ESPN "
        "accepted it, so ESPN is not counting eligibility for this limit (unless a player "
        "gained that eligibility after he was rostered)"
    ]


@pytest.mark.asyncio
async def test_eligibility_basis_makes_the_count_a_verdict(monkeypatch):
    monkeypatch.setenv("ESPN_POSITION_LIMIT_BASIS", "Eligibility")
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    patches = _legality_patches(client, ROSTER, ADD_FC, center_limit=4)
    with patches[0], patches[1], patches[2], patches[3]:
        result = await client.check_roster_move(1, [9])
    assert not result.canMake and result.positionLimitBasisSetting == "eligibility"
    assert result.reasons == [
        "5 players are eligible at C; the limit is 4 (ESPN_POSITION_LIMIT_BASIS=eligibility)"
    ]
    assert result.warnings == []
    assert result.positionLimitBasis.startswith("Verdict counts every position")

    # a drop that frees a C-eligible spot makes it legal again
    with patches[0], patches[1], patches[2], patches[3]:
        with_drop = await client.check_roster_move(1, [9], drop_ids=[3])
    assert with_drop.canMake and with_drop.positionCountsAfterByEligibility["C"] == 4


def test_unknown_basis_value_falls_back_to_primary(monkeypatch):
    monkeypatch.setenv("ESPN_POSITION_LIMIT_BASIS", "both")
    assert ESPNFantasyBasketballClient._position_limit_basis() == "primary"
    monkeypatch.setenv("ESPN_POSITION_LIMIT_BASIS", " eligibility ")
    assert ESPNFantasyBasketballClient._position_limit_basis() == "eligibility"
    monkeypatch.delenv("ESPN_POSITION_LIMIT_BASIS")
    assert ESPNFantasyBasketballClient._position_limit_basis() == "primary"


def test_window_pins_utc():
    """Guard against a system-local date straddling midnight (see test_matchup_analysis)."""
    assert NOW.tzinfo == timezone.utc and isinstance(NOW, datetime)

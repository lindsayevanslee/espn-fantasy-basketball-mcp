"""Regression tests for the second round of live feedback (15 November 2026).

1. Pending adds. ESPN applies an add made after today's games started from
   status.transactionScoringPeriod, so the player is on that day's roster and not today's
   (live: Queta on the period-28 roster, 12 players and an empty UTIL on today's). Projections
   for next week and the legality check must use that effective roster.
2. Conflicting roster state: the legality check said a pending add was "already on your
   roster" while counting the roster without him.
3. Lineup-swap simulation: "start Sheppard, sit Dunn" via start_ids / sit_ids.
4. Attempt counts: made/attempted beside FG% and FT% everywhere a percentage is projected.
"""

from __future__ import annotations

import copy
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

from espn_fantasy_basketball_mcp.analysis import _apply_lineup_changes, expected_games_for
from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient
from espn_fantasy_basketball_mcp.constants import SLOT_BENCH, SLOT_IR
from espn_fantasy_basketball_mcp.models import (
    CurrentMatchup,
    MatchupTeam,
    OverallRecord,
    PendingAdd,
    PlayerPoolEntry,
    Roster,
    RosterEntry,
    RosterLegality,
    Team,
    TeamRecord,
)
from tests.fixture_espn import fixture_name, use_fixtures
from tests.test_lineup_feedback import WINDOW, _dates, _weekly_fixture
from tests.test_matchup_analysis import (
    CURRENT_PERIOD,
    TODAY,
    _day,
    _entry,
    _schedule,
    _settings,
    _stats,
)

LEAGUE, YEAR, MY_TEAM = 12345, 2027, 8


def _owned(pid: int, slot: int, on_team: int | None, eligible: list[int] | None = None):
    entry = _entry(pid, slot=slot)
    player = entry.playerPoolEntry.player.model_copy(update={"eligibleSlots": eligible})
    return entry.model_copy(
        update={"playerPoolEntry": PlayerPoolEntry(id=pid, player=player, onTeamId=on_team)}
    )


# ------------------------------------------------------------------ 1. merging rosters
def test_merge_rosters_keeps_the_union_and_names_the_differences():
    today = Roster(
        teamId=1,
        entries=[
            _owned(101, 0, 1),
            _owned(102, 1, 1),
            _owned(103, 11, 0),  # dropped tonight: ESPN already points him at the pool
            _owned(104, 12, 1),  # on today's roster only (a later roster can lag an add)
        ],
    )
    later = Roster(
        teamId=1,
        scoringPeriodId=28,
        scoringPeriodDate="2026-11-16",
        entries=[
            _owned(101, 5, 1).model_copy(update={"lineupLocked": False}),
            _owned(102, 1, 1),
            _owned(105, 11, 1),  # the pending add, in the UTIL slot 103 left
        ],
    )
    merged = ESPNFantasyBasketballClient._merge_rosters(today, later, 28, "2026-11-16", False)
    assert [e.playerId for e in merged.entries] == [101, 102, 104, 105]
    assert merged.entries[0].lineupSlotId == 0, "slots stay today's without slots_from_later"
    assert merged.pendingAdds == [
        PendingAdd(
            playerId=105,
            playerName="Player 105",
            effectiveScoringPeriod=28,
            effectiveDate="2026-11-16",
            lineupSlotName=None,
        )
    ]
    assert merged.missingFromLaterRoster == ["Player 104"]

    planned = ESPNFantasyBasketballClient._with_planned_lineup(today, later)
    assert planned.entries[0].lineupSlotId == 5 and planned.entries[0].lineupLocked is False
    assert planned.scoringPeriodId == 28 and planned.scoringPeriodDate == "2026-11-16"
    assert [p.playerId for p in planned.pendingAdds] == [105]


@pytest.mark.asyncio
async def test_effective_roster_reads_the_transaction_period_only_when_it_is_later():
    client = ESPNFantasyBasketballClient(league_id=LEAGUE, year=YEAR)
    settings = _settings([0])
    settings.status.latestScoringPeriod = 26
    settings.status.transactionScoringPeriod = 28
    settings.status.transactionScoringPeriodDate = "2026-11-16"
    today = Roster(teamId=1, entries=[_owned(101, 0, 1)])
    later = Roster(teamId=1, entries=[_owned(101, 0, 1), _owned(105, 11, 1)])
    calls: list[int | None] = []

    async def fake_roster(team_id, scoring_period=None):
        calls.append(scoring_period)
        return later if scoring_period == 28 else today

    with patch.object(client, "get_team_roster", side_effect=fake_roster):
        roster = await client.get_effective_roster(1, settings)
    assert calls == [None, 28]
    assert [e.playerId for e in roster.entries] == [101, 105]
    assert roster.pendingAdds[0].effectiveDate == "2026-11-16"

    # adds made now take effect today: today's roster is the effective roster, one request
    settings.status.transactionScoringPeriod = 26
    calls.clear()
    with patch.object(client, "get_team_roster", side_effect=fake_roster):
        same = await client.get_effective_roster(1, settings)
    assert calls == [None] and same is today


# ------------------------------------------------------------------ 2. legality on the effective roster
@pytest.mark.asyncio
async def test_legality_counts_the_pending_add_and_says_so(monkeypatch):
    """The live report: Queta added tonight, on the period-28 roster only. Before: 'already on
    your roster' next to 12 players and 3 centres. After: 13 players, 4 centres, and the reason
    says he is a pending add."""
    monkeypatch.delenv("ESPN_POSITION_LIMIT_BASIS", raising=False)
    client = ESPNFantasyBasketballClient(league_id=LEAGUE, year=YEAR)
    settings = _settings([0])
    settings.status.latestScoringPeriod = 26
    settings.status.transactionScoringPeriod = 28
    settings.status.transactionScoringPeriodDate = "2026-11-16"
    settings.rosterSettings.positionLimitNames = {"C": 4}
    settings.rosterSettings.rosterSize = 13

    def centre(pid: int, slot: int, on_team: int | None = 8) -> RosterEntry:
        e = _owned(pid, slot, on_team, eligible=[4, 11, 12])
        p = e.playerPoolEntry.player.model_copy(
            update={"defaultPositionId": 5, "defaultPosition": "C"}
        )
        return e.model_copy(
            update={"playerPoolEntry": PlayerPoolEntry(id=pid, player=p, onTeamId=on_team)}
        )

    today_entries = [centre(1, 4), centre(2, 6), centre(3, 11)] + [
        _owned(pid, 12, 8, eligible=[0, 5, 11, 12]) for pid in range(10, 19)
    ]
    queta = centre(99, 11)
    today = Roster(teamId=8, entries=today_entries)
    later = Roster(teamId=8, entries=today_entries + [queta])
    team = Team(
        id=8,
        abbrev="SA",
        name="Statistical Anomalies",
        record=TeamRecord(overall=OverallRecord(wins=2, losses=1, ties=0)),
        acquisitionsRemainingThisMatchup=6,
    )

    async def fake_roster(team_id, scoring_period=None):
        return later if scoring_period == 28 else today

    with (
        patch.object(client, "get_league_settings", AsyncMock(return_value=settings)),
        patch.object(client, "get_team_roster", side_effect=fake_roster),
        patch.object(client, "get_league_teams", AsyncMock(return_value=[team])),
        patch.object(client, "roster_entries_for_players", AsyncMock(return_value=[queta])),
    ):
        result = await client.check_roster_move(8, [99])

    assert not result.canMake
    assert result.reasons == [
        "Player 99 (99) is already on your roster: a pending add that takes effect on 2026-11-16"
    ]
    assert result.rosterSizeNow == 13 and result.rosterSizeAfter == 13
    assert result.positionCountsNowByDefaultPosition["C"] == 4
    assert result.rosterScoringPeriod == 28
    assert result.rosterNote == (
        "Counts use the roster for scoring period 28 (2026-11-16), the period an add made now "
        "takes effect, so pending adds are included (Player 99)"
    )


# ------------------------------------------------------------------ 1b. projections
def test_pending_add_games_count_only_from_the_effective_day():
    entry = _entry(1, slot=11)
    g = expected_games_for(
        entry, _dates(1, 2, 3), WINDOW[1], TODAY, False, effective_from=TODAY + timedelta(days=2)
    )
    assert (g.scheduled, g.playable, g.counted) == (2, 2.0, 2.0)
    assert g.note == (
        f"pending add effective {_day(2)}: 1 earlier game(s) not counted; counted from "
        f"{_day(2)}, when the add takes effect"
    )
    # effective before the first game: nothing to say
    g = expected_games_for(
        entry, _dates(1, 2, 3), WINDOW[1], TODAY, False, effective_from=TODAY + timedelta(days=1)
    )
    assert g.scheduled == 3 and g.note == f"counted from {_day(1)}, when the add takes effect"


@pytest.mark.asyncio
async def test_pending_add_is_projected_from_his_effective_day(monkeypatch):
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=LEAGUE, year=YEAR)
    settings = _settings([0])
    pending = _entry(105, slot=11)
    my_roster = Roster(
        teamId=1,
        entries=[_entry(101), pending],
        pendingAdds=[PendingAdd(playerId=105, playerName="Player 105", effectiveDate=_day(2))],
    )
    matchup = CurrentMatchup(
        matchupId=1,
        scoringPeriod=30,
        rosterNote="Rosters: today's players plus pending adds; pending adds included: Player 105",
        yourTeam=MatchupTeam(teamId=1, teamName="Me", categoryScores={"points": 0.0}),
        opponentTeam=MatchupTeam(teamId=2, teamName="Them", categoryScores={"points": 0.0}),
        yourRoster=my_roster,
        opponentRoster=Roster(teamId=2, entries=[_entry(201)]),
    )
    three = [_day(1), _day(2), _day(3)]
    schedules = {1: _schedule(1, {101: three, 105: three}), 2: _schedule(2, {201: three})}
    projections = [_stats(pid, "projections", points=10.0) for pid in (101, 105, 201)]

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
    assert points.yourProjected == pytest.approx(30 + 20), "101 x3, pending 105 x2"
    assert analysis.yourGamesRemaining == 5 and analysis.yourExpectedGames == 5.0
    rec = next(r for r in analysis.playerRecommendations if r.playerId == 105)
    assert rec.gamesRemaining == 2 and rec.availabilityNote.startswith("pending add effective")
    assert "pending adds included: Player 105" in analysis.rosterSource


# ------------------------------------------------------------------ 1c. end to end on fixtures
def _inject_pending_add(monkeypatch, router, pid: int = 9001):
    """Make the fixture league look like the live one: player `pid` (Streamer One, DEN) is on
    team 8's roster for the transaction period (14) only, and ESPN's player pool says he is
    owned by team 8."""
    real = ESPNFantasyBasketballClient._make_request

    async def patched(self, url, params=None, headers=None):
        data = await real(self, url, params, headers)
        name = fixture_name(url, params, headers)
        if name == "league_mRoster.json" and str((params or {}).get("scoringPeriodId")) == "14":
            team = next(t for t in data["teams"] if t["id"] == MY_TEAM)
            entry = copy.deepcopy(team["roster"]["entries"][0])
            entry["playerId"] = pid
            entry["lineupSlotId"] = 11
            pool = entry["playerPoolEntry"]
            pool["id"] = pid
            pool["onTeamId"] = MY_TEAM
            pool["player"].update(
                {
                    "id": pid,
                    "fullName": "Streamer One",
                    "firstName": "Streamer",
                    "lastName": "One",
                    "proTeamId": 7,
                    "defaultPositionId": 1,
                    "eligibleSlots": [0, 5, 11, 12],
                }
            )
            pool["player"].pop("stats", None)
            team["roster"]["entries"].append(entry)
        if name == "league_kona_player_info.json":
            for p in data.get("players", []):
                if p["player"]["id"] == pid:
                    p["onTeamId"] = MY_TEAM
                    p["player"]["availabilityStatus"] = "ONTEAM"
        return data

    monkeypatch.setattr(ESPNFantasyBasketballClient, "_make_request", patched)


@pytest.mark.asyncio
async def test_fixture_league_with_a_pending_add_end_to_end(monkeypatch):
    monkeypatch.setenv("ESPN_LEAGUE_ID", str(LEAGUE))
    monkeypatch.setenv("ESPN_YEAR", str(YEAR))
    monkeypatch.setenv("ESPN_TEAM_ID", str(MY_TEAM))
    router = use_fixtures(monkeypatch)
    _inject_pending_add(monkeypatch, router)
    client = ESPNFantasyBasketballClient(LEAGUE, YEAR)

    # Nov 1 (period 13, last day of matchup 2); adds made now land on period 14 = Nov 2, the
    # first day of matchup period 3.
    settings = await client.get_league_settings()
    assert (settings.status.latestScoringPeriod, settings.status.transactionScoringPeriod) == (
        13,
        14,
    )

    # today's roster does not have him; the effective roster does
    today = await client.get_team_roster(MY_TEAM)
    assert 9001 not in {e.playerId for e in today.entries}
    effective = await client.get_effective_roster(MY_TEAM, settings)
    assert [p.playerName for p in effective.pendingAdds] == ["Streamer One"]
    assert effective.pendingAdds[0].effectiveDate == "2026-11-02"

    # next week's projection counts his 4 DEN games (compare 8.0 without him)
    upcoming = await client.analyze_matchup(MY_TEAM, matchup_period=3)
    assert upcoming.yourExpectedGames == 12.0
    streamer = next(r for r in upcoming.playerRecommendations if r.playerId == 9001)
    assert streamer.lineupSlotName == "UTIL" and streamer.gamesInProjection == 4.0
    assert streamer.availabilityNote == "counted from 2026-11-02, when the add takes effect"
    assert upcoming.rosterSource.endswith("pending adds included: Streamer One")

    # this week ends before he takes effect: not counted, and the note says so
    current = await client.analyze_matchup(MY_TEAM, matchup_period=2)
    assert 9001 not in {r.playerId for r in current.playerRecommendations}
    assert "take effect on 2026-11-02 (scoring period 14), after this week" in current.rosterSource

    # the legality check agrees with itself: he is a pending add and he is counted
    check = await client.check_roster_move(MY_TEAM, [9001])
    assert check.reasons == [
        "Streamer One (9001) is already on your roster: a pending add that takes effect on 2026-11-02"
    ]
    assert check.rosterSizeNow == 5 and check.rosterScoringPeriod == 14
    assert "pending adds are included (Streamer One)" in check.rosterNote


# ------------------------------------------------------------------ 3. lineup swaps
SLOT_COUNTS = {"0": 1, "1": 1, "5": 1, "11": 1, "12": 3, "13": 1}


def _lineup(*specs):
    """(pid, slot, eligible, locked) -> RosterEntry"""
    out = []
    for pid, slot, eligible, *rest in specs:
        locked = rest[0] if rest else None
        out.append(_owned(pid, slot, 1, eligible).model_copy(update={"lineupLocked": locked}))
    return out


def test_start_takes_the_sat_players_slot_when_eligible():
    entries = _lineup((1, 0, [0, 1, 5, 11, 12]), (2, 12, [0, 5, 11, 12]), (3, 12, [4, 11, 12]))
    started, benched, changes, warnings, new = _apply_lineup_changes(
        entries, [2], [1], SLOT_COUNTS, False, 5
    )
    slots = {e.playerId: e.lineupSlotId for e in new}
    assert slots == {1: SLOT_BENCH, 2: 0, 3: SLOT_BENCH}
    assert started == ["Player 2 (2)"] and benched == ["Player 1 (1)"]
    assert changes == ["Player 2 starts at PG in place of Player 1, who goes to the bench"]
    assert warnings == []


def test_ineligible_swap_falls_back_to_an_open_slot_and_says_why():
    # 3 is a centre: not eligible at PG, but UTIL (11) is open
    entries = _lineup((1, 0, [0, 1, 5, 11, 12]), (3, 12, [4, 11, 12]))
    started, benched, changes, warnings, new = _apply_lineup_changes(
        entries, [3], [1], SLOT_COUNTS, False, 5
    )
    slots = {e.playerId: e.lineupSlotId for e in new}
    assert slots == {1: 0, 3: 11}, "1 keeps his slot: the swap as asked was not possible"
    assert benched == [] and started == ["Player 3 (3)"]
    assert changes == ["Player 3 starts at UTIL"]
    assert warnings == ["Player 3 is not eligible at PG (Player 1's slot); eligible at C, UTIL"]


def test_unpaired_start_needs_an_open_slot():
    full = {"0": 1, "12": 3}
    entries = _lineup((1, 0, [0, 11, 12]), (2, 12, [0, 11, 12]))
    started, benched, changes, warnings, new = _apply_lineup_changes(
        entries, [2], [], full, False, 5
    )
    assert started == [] and changes == []
    assert warnings == ["No open starting slot Player 2 is eligible for; name a starter to sit"]
    assert {e.playerId: e.lineupSlotId for e in new} == {1: 0, 2: SLOT_BENCH}


def test_unpaired_sit_and_edge_cases():
    entries = _lineup((1, 0, [0, 11, 12], True), (2, 12, [0, 11, 12]), (4, SLOT_IR, [0, 12, 13]))
    started, benched, changes, warnings, new = _apply_lineup_changes(
        entries, [2, 77, 2], [2, 1, 4], SLOT_COUNTS, True, 5
    )
    # start 2 / sit 2 -> cannot both; 2 then takes the open UTIL. start 77 -> unknown, so the
    # paired sit of 1 is not applied (a sit pairs with the start that takes its slot).
    # third pair: 2 again (already starting at UTIL now), sit 4 (IR counts as bench).
    assert warnings == [
        "Player 2 cannot both start and sit",
        "Player 77 is not on the roster after the drops/adds; cannot start",
        "Player 4 is already on the bench",
        "Player 2 already starts at UTIL",
    ]
    slots = {e.playerId: e.lineupSlotId for e in new}
    assert slots[1] == 0 and slots[2] == 11 and slots[4] == SLOT_IR
    assert benched == [] and started == ["Player 2 (2)"]

    # replacing a locked starter mid-week is simulated but flagged
    started, benched, changes, warnings, new = _apply_lineup_changes(
        entries, [2], [1], SLOT_COUNTS, True, 5
    )
    assert benched == ["Player 1 (1)"] and started == ["Player 2 (2)"]
    assert warnings == [
        "Player 1's slot is locked for this period; the change is simulated but cannot be "
        "made until matchup period 6"
    ]

    # a sit on its own frees the slot
    started, benched, changes, warnings, new = _apply_lineup_changes(
        entries, [], [1], SLOT_COUNTS, False, 5
    )
    assert benched == ["Player 1 (1)"] and changes == ["Player 1 to the bench (PG left open)"]
    assert {e.playerId: e.lineupSlotId for e in new}[1] == SLOT_BENCH


def test_unknown_eligibility_is_allowed_and_noted():
    entries = _lineup((1, 0, [0, 12]), (2, 12, None))
    started, benched, changes, warnings, new = _apply_lineup_changes(
        entries, [2], [1], SLOT_COUNTS, False, 5
    )
    assert started == ["Player 2 (2)"] and benched == ["Player 1 (1)"]
    assert warnings == ["Player 2: ESPN lists no eligible slots; eligibility not checked"]


@pytest.mark.asyncio
async def test_simulated_lineup_swap_moves_the_weekly_projection(monkeypatch):
    """start 103 (bench), sit 101 (PG): in a weekly league the bench does not score, so the
    swap moves games from one to the other; 102 (OUT) stays where he is."""
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=LEAGUE, year=YEAR)
    settings, matchup, schedules = _weekly_fixture("FIRSTGAME_WEEKLY", CURRENT_PERIOD + 1)
    settings.rosterSettings.lineupSlotCounts = {"0": 1, "1": 1, "12": 3}
    entries = matchup.yourRoster.entries
    for i, e in enumerate(entries):
        p = e.playerPoolEntry.player.model_copy(update={"eligibleSlots": [0, 1, 5, 11, 12]})
        entries[i] = e.model_copy(
            update={"playerPoolEntry": PlayerPoolEntry(id=e.playerId, player=p)}
        )

    legality = RosterLegality(teamId=1, canMake=True, rosterSizeNow=3, rosterSizeAfter=3)
    projections = [_stats(pid, "projections", points=10.0) for pid in (101, 102, 103, 201, 202)]

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
        patch.object(client, "roster_entries_for_players", AsyncMock(return_value=[])),
        patch.object(client, "_schedule_summary", side_effect=fake_summary),
        patch.object(client, "check_roster_move", AsyncMock(return_value=legality)),
    ):
        sim = await client.simulate_roster_move(
            1, [], [], CURRENT_PERIOD + 1, start_ids=[103], sit_ids=[101]
        )
        # start 103 with the sat player's slot taken AND sit 102 too: 102's SG slot opens
        both = await client.simulate_roster_move(
            1, [], [], CURRENT_PERIOD + 1, start_ids=[103], sit_ids=[101, 102]
        )
        with pytest.raises(ValueError, match="drop, add, start, sit, or mark absent"):
            await client.simulate_roster_move(1, [], [], CURRENT_PERIOD + 1)

    assert sim.started == ["Player 103 (103)"] and sim.benched == ["Player 101 (101)"]
    assert sim.lineupChanges == [
        "Player 103 starts at PG in place of Player 101, who goes to the bench"
    ]
    assert sim.lineupWarnings == []
    assert (sim.expectedGamesBefore, sim.expectedGamesAfter) == (2.0, 2.0), "101 out, 103 in"
    assert (
        "Lineup: Player 103 starts at PG in place of Player 101, who goes to the bench"
        in sim.summary
    )
    assert not any("Daily lineup lock" in line for line in sim.summary)
    assert both.benched == ["Player 101 (101)", "Player 102 (102)"]
    assert both.lineupChanges[1] == "Player 102 to the bench (SG left open)"


@pytest.mark.asyncio
async def test_daily_league_lineup_swap_is_flagged_as_not_moving_the_projection(monkeypatch):
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=LEAGUE, year=YEAR)
    settings, matchup, schedules = _weekly_fixture("INDIVIDUAL_GAME", CURRENT_PERIOD)
    projections = [_stats(pid, "projections", points=10.0) for pid in (101, 102, 103, 201, 202)]
    legality = RosterLegality(teamId=1, canMake=True, rosterSizeNow=3, rosterSizeAfter=3)

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
        patch.object(client, "roster_entries_for_players", AsyncMock(return_value=[])),
        patch.object(client, "_schedule_summary", side_effect=fake_summary),
        patch.object(client, "check_roster_move", AsyncMock(return_value=legality)),
    ):
        sim = await client.simulate_roster_move(1, [], [], CURRENT_PERIOD, sit_ids=[101])
    assert sim.benched == ["Player 101 (101)"]
    assert sim.expectedGamesBefore == sim.expectedGamesAfter
    assert any(line.startswith("Daily lineup lock: bench players count") for line in sim.summary)


# ------------------------------------------------------------------ 4. attempt counts
@pytest.mark.asyncio
async def test_percentages_carry_made_and_attempted_everywhere(monkeypatch):
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=LEAGUE, year=YEAR)
    settings = _settings([0, 19])  # points, FG%
    matchup = CurrentMatchup(
        matchupId=1,
        scoringPeriod=30,
        yourTeam=MatchupTeam(
            teamId=1,
            teamName="Me",
            categoryScores={"points": 100.0, "fieldGoalPercentage": 0.5},
            componentStats={"fieldGoalsMade": 50.0, "fieldGoalsAttempted": 100.0},
        ),
        opponentTeam=MatchupTeam(
            teamId=2,
            teamName="Them",
            categoryScores={"points": 100.0, "fieldGoalPercentage": 0.4},
            componentStats={"fieldGoalsMade": 40.0, "fieldGoalsAttempted": 100.0},
        ),
        yourRoster=Roster(teamId=1, entries=[_entry(101)]),
        opponentRoster=Roster(teamId=2, entries=[_entry(201)]),
    )
    two = [_day(1), _day(2)]
    schedules = {1: _schedule(1, {101: two}), 2: _schedule(2, {201: two})}
    projections = [
        _stats(
            101,
            "projections",
            points=20.0,
            fieldGoalsMade=8.0,
            fieldGoalsAttempted=16.0,
            fieldGoalPercentage=50.0,
        ),
        _stats(
            201,
            "projections",
            points=10.0,
            fieldGoalsMade=3.0,
            fieldGoalsAttempted=10.0,
            fieldGoalPercentage=30.0,
        ),
    ]

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

    fg = next(c for c in analysis.categoryProjections if c.category == "fieldGoalPercentage")
    assert (fg.yourCurrentMade, fg.yourCurrentAttempted) == (50.0, 100.0)
    assert (fg.yourProjectedMade, fg.yourProjectedAttempted) == (66.0, 132.0), "+ 8/16 x 2 games"
    assert fg.yourProjected == pytest.approx(66 / 132)
    assert (fg.opponentProjectedMade, fg.opponentProjectedAttempted) == (46.0, 120.0)
    assert fg.opponentProjected == pytest.approx(46 / 120)
    points = next(c for c in analysis.categoryProjections if c.category == "points")
    assert points.yourProjectedMade is None, "counting categories carry no made/attempted"

    [rec] = analysis.playerRecommendations
    assert rec.basisPerGame == {
        "points": 20.0,
        "fieldGoalPercentage": 50.0,
        "fieldGoalsMade": 8.0,
        "fieldGoalsAttempted": 16.0,
    }
    assert rec.projectedTotals == {
        "points": 40.0,
        "fieldGoalsMade": 16.0,
        "fieldGoalsAttempted": 32.0,
    }
    [opp] = analysis.opponentPlayers
    assert opp.projectedTotals == {
        "points": 20.0,
        "fieldGoalsMade": 6.0,
        "fieldGoalsAttempted": 20.0,
    }

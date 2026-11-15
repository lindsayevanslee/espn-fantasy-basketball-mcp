"""Regression tests for the third round of live feedback (15 November 2026).

1. Unknown tool arguments are rejected with the closest accepted names, instead of being
   ignored (bench_ids for sit_ids returned a normal-looking result).
2. The projection is re-run on the alternate basis and categories where projections and
   season actuals disagree are flagged.
3. "What if he does not play": absent_ids / missed_games on simulate_roster_move.
4. optimize_lineup ranks every valid starting lineup.
5. A lineup-only simulation carries no legality section, and the eligibility warning is not
   raised where the roster already shows eligibility is not the rule.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import espn_fantasy_basketball as server
from espn_fantasy_basketball_mcp.analysis import _assign_slots
from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient
from espn_fantasy_basketball_mcp.constants import SLOT_BENCH
from espn_fantasy_basketball_mcp.models import PlayerPoolEntry
from tests.fixture_espn import use_fixtures
from tests.test_lineup_feedback import WINDOW, _simulate, _weekly_fixture
from tests.test_matchup_analysis import CURRENT_PERIOD, _day, _entry, _schedule, _stats

LEAGUE, YEAR, MY_TEAM = 12345, 2027, 8


# ------------------------------------------------------------------ 1. unknown arguments
@pytest.mark.asyncio
async def test_unknown_arguments_are_rejected_with_a_suggestion():
    with pytest.raises(ValueError) as err:
        await server.mcp.call_tool("simulate_roster_move", {"bench_ids": [1], "start_ids": [2]})
    message = str(err.value)
    assert message.startswith(
        "Unknown argument(s) for simulate_roster_move: 'bench_ids' (did you mean "
    )
    suggestion = message.split("did you mean ")[1].split("?)")[0]
    assert suggestion == "'sit_ids' or 'absent_ids'", "meaning (bench -> sit) outranks spelling"
    assert "Accepted arguments: absent_ids, add_ids, basis, drop_ids" in message


@pytest.mark.asyncio
async def test_known_arguments_still_reach_the_tool(monkeypatch):
    monkeypatch.setenv("ESPN_LEAGUE_ID", str(LEAGUE))
    monkeypatch.setenv("ESPN_YEAR", str(YEAR))
    monkeypatch.setenv("ESPN_TEAM_ID", str(MY_TEAM))
    use_fixtures(monkeypatch)
    result = await server.mcp.call_tool("can_add_player", {"add_ids": [7001]})
    [block] = result
    assert '"canMake": true' in block.text


@pytest.mark.asyncio
async def test_unknown_tool_name_falls_through_to_the_sdk_error():
    with pytest.raises(Exception, match="Unknown tool"):
        await server.mcp.call_tool("no_such_tool", {})


# ------------------------------------------------------------------ 2. bases disagree
async def _analyze_with(client, settings, matchup, schedules, stats_by_timeframe, period, **kw):
    async def fake_stats(player_ids, timeframe):
        return stats_by_timeframe.get(timeframe, [])

    async def fake_schedule(team_id, start, end, period_):
        return schedules[team_id]

    with (
        patch.object(client, "get_league_settings", AsyncMock(return_value=settings)),
        patch.object(client, "get_matchup_for_period", AsyncMock(return_value=matchup)),
        patch.object(client, "get_matchup_period_dates", AsyncMock(return_value=WINDOW)),
        patch.object(client, "get_roster_schedule_summary", side_effect=fake_schedule),
        patch.object(client, "get_player_stats", side_effect=fake_stats),
    ):
        return await client.analyze_matchup(team_id=1, matchup_period=period, **kw)


@pytest.mark.asyncio
async def test_bases_that_disagree_are_flagged(monkeypatch):
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=LEAGUE, year=YEAR)
    settings, matchup, schedules = _weekly_fixture("INDIVIDUAL_GAME", CURRENT_PERIOD)
    # projections: our two active players score 10/game, theirs 5 -> win by 20 (close: the
    # points margin is 20). season: ours average 2, theirs 9 -> loss by 28 (near).
    stats = {
        "projections": [_stats(pid, "projections", points=10.0) for pid in (101, 102, 103)]
        + [_stats(pid, "projections", points=5.0) for pid in (201, 202)],
        "season": [_stats(pid, "season", points=2.0, gamesPlayed=5) for pid in (101, 102, 103)]
        + [_stats(pid, "season", points=9.0, gamesPlayed=5) for pid in (201, 202)],
    }
    analysis = await _analyze_with(client, settings, matchup, schedules, stats, CURRENT_PERIOD)
    [points] = analysis.categoryProjections
    assert points.projectedResult == "win" and points.alternateBasis == "season"
    assert points.alternateResult == "loss" and points.basesAgree is False
    assert points.alternateProjectedLead == pytest.approx((2 * 2 * 2) - (9 * 2 * 2))
    assert analysis.alternateBasis == "season" and analysis.alternateProjectedRecord == "0-1-0"
    assert analysis.basisDisagreements == [
        "points: projections says win (close, lead +20); season says loss (near, lead -28)"
    ]
    assert analysis.strategyNotes[-1] == (
        "The season basis gives a different result in 1 category (0-1-0 on season vs 1-0-0 "
        "on projections): points. Treat those calls as uncertain (see basisDisagreements)"
    )

    # the other way round: season as the basis compares against projections
    flipped = await _analyze_with(
        client, settings, matchup, schedules, stats, CURRENT_PERIOD, basis="season"
    )
    assert flipped.alternateBasis == "projections" and flipped.basis == "season"
    assert flipped.categoryProjections[0].alternateResult == "win"


@pytest.mark.asyncio
async def test_bases_that_agree_say_so(monkeypatch):
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=LEAGUE, year=YEAR)
    settings, matchup, schedules = _weekly_fixture("INDIVIDUAL_GAME", CURRENT_PERIOD)
    everyone = (101, 102, 103, 201, 202)
    stats = {
        "projections": [_stats(pid, "projections", points=10.0) for pid in everyone],
        "season": [_stats(pid, "season", points=10.0, gamesPlayed=5) for pid in everyone],
    }
    analysis = await _analyze_with(client, settings, matchup, schedules, stats, CURRENT_PERIOD)
    assert analysis.basisDisagreements == []
    assert analysis.categoryProjections[0].basesAgree is True
    # equal scoring and equal games on both sides: a tie on either basis
    assert analysis.strategyNotes[-1] == (
        "The season basis agrees with every category result (0-0-1)"
    )


# ------------------------------------------------------------------ 3. absences
async def _simulate_more(client, settings, matchup, schedules, **kwargs):
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
        patch.object(
            client, "check_roster_move", AsyncMock(side_effect=AssertionError("not called"))
        ),
    ):
        return await client.simulate_roster_move(1, [], [], CURRENT_PERIOD, **kwargs)


@pytest.mark.asyncio
async def test_absences_remove_games_without_moving_slots(monkeypatch):
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=LEAGUE, year=YEAR)
    settings, matchup, schedules = _weekly_fixture("INDIVIDUAL_GAME", CURRENT_PERIOD)
    # daily league: 101 and 103 play 2 each, 102 is OUT -> 4 expected games before
    sim = await _simulate_more(client, settings, matchup, schedules, absent_ids=[101])
    assert (sim.expectedGamesBefore, sim.expectedGamesAfter) == (4.0, 2.0)
    assert sim.absences == ["Player 101 does not play"]
    assert "Absences simulated: Player 101 does not play" in sim.summary
    assert sim.addedPlayers == [], "nobody was added"
    assert sim.legality is None, "no adds or drops: nothing to check"
    assert not any(line.startswith("Legality") for line in sim.summary)

    partial = await _simulate_more(
        client, settings, matchup, schedules, missed_games={103: 1, 999: 2}
    )
    assert partial.expectedGamesAfter == 3.0
    assert partial.absences == [
        "Player 103 misses 1 game(s)",
        "Player 999 is not on the roster; absence ignored",
    ]


@pytest.mark.asyncio
async def test_absence_arguments_are_validated():
    client = ESPNFantasyBasketballClient(league_id=LEAGUE, year=YEAR)
    with pytest.raises(ValueError, match="non-negative integer"):
        await client.simulate_roster_move(1, [], [], CURRENT_PERIOD, missed_games={101: -1})
    with pytest.raises(ValueError, match="mark absent"):
        await client.simulate_roster_move(1, [], [], CURRENT_PERIOD, missed_games={})


# ------------------------------------------------------------------ 4. optimizer
def _with_slots(pid: int, eligible: list[int]):
    entry = _entry(pid, slot=SLOT_BENCH)
    player = entry.playerPoolEntry.player.model_copy(update={"eligibleSlots": eligible})
    return entry.model_copy(update={"playerPoolEntry": PlayerPoolEntry(id=pid, player=player)})


def test_assign_slots_respects_eligibility():
    guard = _with_slots(1, [0, 5, 11, 12])
    centre = _with_slots(2, [4, 11, 12])
    assert _assign_slots([guard, centre], [0, 4]) == {1: 0, 2: 4}
    assert _assign_slots([guard, centre], [11, 4]) == {1: 11, 2: 4}
    assert _assign_slots([guard, centre], [0, 5]) is None, "no slot for the centre"
    assert _assign_slots([guard, centre], [11]) is None, "more players than slots"


def _all_guards(matchup):
    entries = matchup.yourRoster.entries
    for i, e in enumerate(entries):
        p = e.playerPoolEntry.player.model_copy(update={"eligibleSlots": [0, 1, 5, 11, 12]})
        entries[i] = e.model_copy(
            update={"playerPoolEntry": PlayerPoolEntry(id=e.playerId, player=p)}
        )


def _optimizer_patches(client, settings, matchup, schedules):
    stats = [_stats(pid, "projections", points=10.0) for pid in (101, 102, 103, 201, 202)]

    async def fake_stats(player_ids, timeframe):
        return stats if timeframe == "projections" else []

    async def fake_schedule(team_id, start, end, period_):
        return schedules[team_id]

    return (
        patch.object(client, "get_league_settings", AsyncMock(return_value=settings)),
        patch.object(client, "get_matchup_for_period", AsyncMock(return_value=matchup)),
        patch.object(client, "get_matchup_period_dates", AsyncMock(return_value=WINDOW)),
        patch.object(client, "get_roster_schedule_summary", side_effect=fake_schedule),
        patch.object(client, "get_player_stats", side_effect=fake_stats),
    )


@pytest.mark.asyncio
async def test_optimizer_finds_the_lineup_that_benches_the_out_starter(monkeypatch):
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=LEAGUE, year=YEAR)
    settings, matchup, schedules = _weekly_fixture("FIRSTGAME_WEEKLY", CURRENT_PERIOD + 1)
    settings.rosterSettings.lineupSlotCounts = {"0": 1, "1": 1, "12": 3, "13": 1}
    _all_guards(matchup)
    p = _optimizer_patches(client, settings, matchup, schedules)
    with p[0], p[1], p[2], p[3], p[4]:
        result = await client.optimize_lineup(1, CURRENT_PERIOD + 1, top=2)

    # current: 101 (PG, 2 games) and 102 (SG, OUT) start; 103 (2 games) sits. 20 points vs
    # the opponent's 20 (201 only; their bench 202 does not score under a weekly lock): a tie
    assert result.currentProjectedRecord == "0-0-1" and result.currentIsBest is False
    assert result.currentLineup == {"PG": "Player 101", "SG": "Player 102"}
    best = result.options[0]
    assert best.rank == 1 and best.projectedRecord == "1-0-0" and best.isCurrent is False
    assert best.lineup == {"PG": "Player 101", "SG": "Player 103"}, (
        "101 keeps his PG slot; only the newcomer is placed"
    )
    assert best.bench == ["Player 102"]
    assert best.changes == ["start Player 103 (2 games)", "sit Player 102 (0 games)"]
    assert best.expectedGames == 4.0
    assert best.score > 1000, "a won category outranks any margin"
    # 101 + 103 is the only pair with games; 102 would fill a slot only if one were empty
    assert result.lineupsEvaluated == 1
    assert any(n.startswith("Current lineup projects 0-0-1") for n in result.notes)
    assert any(
        "Never started unless a slot would be empty" in n and "Player 102" in n
        for n in result.notes
    )
    assert result.scoring.startswith("Lineups are ranked by projected category wins")


@pytest.mark.asyncio
async def test_optimizer_keeps_locked_players_and_handles_daily_leagues(monkeypatch):
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=LEAGUE, year=YEAR)
    settings, matchup, schedules = _weekly_fixture("INDIVIDUAL_FIRSTGAME_WEEKLY", CURRENT_PERIOD)
    settings.rosterSettings.lineupSlotCounts = {"0": 1, "1": 1, "12": 3, "13": 1}
    _all_guards(matchup)
    # mid-week: the OUT starter's slot is locked, so he cannot be benched
    entries = matchup.yourRoster.entries
    entries[1] = entries[1].model_copy(update={"lineupLocked": True})
    p = _optimizer_patches(client, settings, matchup, schedules)
    with p[0], p[1], p[2], p[3], p[4]:
        locked = await client.optimize_lineup(1, CURRENT_PERIOD)
    assert locked.fixedPlayers == ["Player 102 (SG, locked)"]
    assert locked.currentIsBest is True, "only PG is free and 101 already has it"
    assert locked.options[0].isCurrent and locked.options[0].lineup["SG"] == "Player 102"
    assert locked.options[0].lineup == locked.currentLineup, (
        "an option with the same starters echoes the current slot assignment (live report)"
    )
    assert any(n.startswith("Locked for this period and not moved") for n in locked.notes)

    settings.rosterSettings.lineupLocktimeType = "INDIVIDUAL_GAME"
    with p[0], p[1], p[2], p[3], p[4]:
        daily = await client.optimize_lineup(1, CURRENT_PERIOD)
    assert daily.lineupsEvaluated == 1 and daily.currentIsBest
    assert daily.notes[0].startswith("Daily lineup lock: every non-IR player counts")

    with pytest.raises(ValueError, match="top must be"):
        await client.optimize_lineup(1, CURRENT_PERIOD, top=0)


@pytest.mark.asyncio
async def test_optimize_lineup_tool_end_to_end(monkeypatch):
    monkeypatch.setenv("ESPN_LEAGUE_ID", str(LEAGUE))
    monkeypatch.setenv("ESPN_YEAR", str(YEAR))
    monkeypatch.setenv("ESPN_TEAM_ID", str(MY_TEAM))
    use_fixtures(monkeypatch)
    result = await server.optimize_lineup(matchup_period=3)
    # the fixture league locks daily, so the tool explains and returns the current lineup
    assert result["lineupsEvaluated"] == 1 and result["currentIsBest"] is True
    assert result["options"][0]["isCurrent"] is True
    assert result["notes"][0].startswith("Daily lineup lock")


# ------------------------------------------------------------------ 5. lineup-only has no legality
@pytest.mark.asyncio
async def test_lineup_only_simulation_has_no_legality_section(monkeypatch):
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=LEAGUE, year=YEAR)
    settings, matchup, schedules = _weekly_fixture("FIRSTGAME_WEEKLY", CURRENT_PERIOD + 1)
    _all_guards(matchup)
    sim = await _simulate_more(client, settings, matchup, schedules, start_ids=[103], sit_ids=[101])
    assert sim.legality is None
    assert not any("Legality" in line or "ESPN rejects" in line for line in sim.summary)
    assert sim.started == ["Player 103 (103)"]


@pytest.mark.asyncio
async def test_adds_still_get_a_legality_check(monkeypatch):
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=LEAGUE, year=YEAR)
    settings, matchup, schedules = _weekly_fixture("FIRSTGAME_WEEKLY", CURRENT_PERIOD + 1)
    sim = await _simulate(client, settings, matchup, schedules, CURRENT_PERIOD + 1, [102], [901])
    assert sim.legality is not None


@pytest.mark.asyncio
async def test_closeness_only_disagreement_is_worded_as_such(monkeypatch):
    """Live report: 'disagrees on 3 categories (8-0-0 vs 8-0-0)' read as a contradiction when
    only the closeness differed."""
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=LEAGUE, year=YEAR)
    settings, matchup, schedules = _weekly_fixture("INDIVIDUAL_GAME", CURRENT_PERIOD)
    # projections: win by 4 (close); season: win by 40 (clear)
    stats = {
        "projections": [_stats(pid, "projections", points=10.0) for pid in (101, 102, 103)]
        + [_stats(pid, "projections", points=9.0) for pid in (201, 202)],
        "season": [_stats(pid, "season", points=20.0, gamesPlayed=5) for pid in (101, 102, 103)]
        + [_stats(pid, "season", points=10.0, gamesPlayed=5) for pid in (201, 202)],
    }
    analysis = await _analyze_with(client, settings, matchup, schedules, stats, CURRENT_PERIOD)
    [points] = analysis.categoryProjections
    assert points.projectedResult == points.alternateResult == "win"
    assert (points.closeness, points.alternateCloseness) == ("close", "clear")
    assert points.basesAgree is False
    assert analysis.strategyNotes[-1] == (
        "The season basis agrees with every result (1-0-0) but differs on how close 1 category "
        "is: points. A category one basis calls close and the other clear is less safe than "
        "it looks (see basisDisagreements)"
    )


@pytest.mark.asyncio
async def test_absent_and_missed_for_the_same_player_is_called_out(monkeypatch):
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=LEAGUE, year=YEAR)
    settings, matchup, schedules = _weekly_fixture("INDIVIDUAL_GAME", CURRENT_PERIOD)
    sim = await _simulate_more(
        client, settings, matchup, schedules, absent_ids=[101], missed_games={101: 1}
    )
    assert sim.expectedGamesAfter == 2.0, "absent wins"
    assert sim.absences == [
        "Player 101 does not play",
        "Player 101 is in both absent_ids and missed_games; absent_ids wins (he does not "
        "play). Give one or the other",
    ]


def test_argument_suggestions_understand_meaning_and_spelling():
    accepted = [
        "absent_ids",
        "add_ids",
        "drop_ids",
        "missed_games",
        "sit_ids",
        "start_ids",
        "team_id",
    ]
    assert server._suggest("bench_ids", accepted) == " (did you mean 'sit_ids' or 'absent_ids'?)"
    assert server._suggest("playersToBench", accepted) == " (did you mean 'sit_ids'?)"
    assert server._suggest("out_players", accepted) == " (did you mean 'absent_ids'?)"
    assert server._suggest("sit_id", accepted) == " (did you mean 'sit_ids' or 'start_ids'?)"
    assert server._suggest("foo", accepted) == ""


def test_newcomer_forces_a_reshuffle_only_when_needed():
    """A guard who can only play PG joins; the current PG, who is also G-eligible, moves."""
    pg_only = _with_slots(1, [0, 11, 12])
    flexible = _with_slots(2, [0, 5, 11, 12]).model_copy(update={"lineupSlotId": 0})
    # keeping 2 at PG leaves 1 nowhere: the full reshuffle finds PG for 1 and G for 2
    assert _assign_slots([pg_only], [5]) is None
    assert _assign_slots([pg_only, flexible], [0, 5]) == {1: 0, 2: 5}

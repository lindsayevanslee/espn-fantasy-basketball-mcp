"""Regression tests for the data-quality report on the live league (November 2026).

Each test pins one item from that report:

1. tool schemas never accept the ESPN cookies (they would land in conversation logs)
2. a parameter named in a response note exists on the tool the note names
3. ESPN's record in an Each Category league sums to categories x teams x completed periods,
   and is labelled as a category record, never as matchup wins
4. get_team_season_stats reports a matchup record bounded by completed periods, alongside
   ESPN's category record with its label
5. get_league_teams says which team is yours, ranks the standings, and carries a matchup record
6. no roster entry reaches a response with onTeamId pointing at another team
7. an injury status that contradicts ESPN's injury report (OUT vs "probable") is flagged
8. closeness is judged per category: FG% by made-shot equivalents, counting stats by margin
9. start/sit priority is driven by close categories; hurting a lost-cause category is free
10. the gap between games remaining and expected games is itemised; projections are explained
11. tool output carries no null fields and no raw stat-ID blocks
12. a player with no stat line reports 0 games, the lock type is described, and projections
    prefer the requested season's stat set
"""

from __future__ import annotations

import re
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

import espn_fantasy_basketball as server
from espn_fantasy_basketball import (
    analyze_matchup as analyze_matchup_tool,
)
from espn_fantasy_basketball import (
    get_league_teams as get_league_teams_tool,
)
from espn_fantasy_basketball import (
    get_matchups as get_matchups_tool,
)
from espn_fantasy_basketball import (
    get_my_current_matchup as get_my_current_matchup_tool,
)
from espn_fantasy_basketball import (
    get_team_roster as get_team_roster_tool,
)
from espn_fantasy_basketball import (
    get_team_season_stats as get_team_season_stats_tool,
)
from espn_fantasy_basketball_mcp.analysis import category_close_threshold, category_verdict
from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient
from espn_fantasy_basketball_mcp.constants import CLOSE_MARGINS, CLOSE_PERCENTAGE_MAKES
from espn_fantasy_basketball_mcp.models import (
    CurrentMatchup,
    MatchupTeam,
    OverallRecord,
    Team,
    TeamRecord,
)
from tests.fixture_espn import use_fixtures
from tests.test_matchup_analysis import (
    CURRENT_PERIOD,
    TODAY,
    _day,
    _roster,
    _schedule,
    _settings,
    _stats,
)

LEAGUE, YEAR, MY_TEAM = 12345, 2027, 8


@pytest.fixture
def espn(monkeypatch):
    monkeypatch.setenv("ESPN_LEAGUE_ID", str(LEAGUE))
    monkeypatch.setenv("ESPN_YEAR", str(YEAR))
    monkeypatch.setenv("ESPN_TEAM_ID", str(MY_TEAM))
    monkeypatch.delenv("ESPN_S2", raising=False)
    monkeypatch.delenv("ESPN_SWID", raising=False)
    return use_fixtures(monkeypatch)


@pytest.fixture
def client(espn):
    return ESPNFantasyBasketballClient(LEAGUE, YEAR)


async def _tool_schemas() -> dict[str, dict]:
    return {t.name: t.inputSchema for t in await server.mcp.list_tools()}


# ------------------------------------------------------------------ 1. cookies are never parameters
@pytest.mark.asyncio
async def test_no_tool_accepts_espn_cookies():
    schemas = await _tool_schemas()
    assert len(schemas) == 22
    leaking = {
        name: sorted(set(schema.get("properties", {})) & {"espn_s2", "swid", "SWID"})
        for name, schema in schemas.items()
    }
    assert not any(leaking.values()), leaking


def test_credentials_come_only_from_the_environment(monkeypatch):
    monkeypatch.setenv("ESPN_S2", "env-s2")
    monkeypatch.setenv("ESPN_SWID", "{ENV}")
    assert server._get_espn_credentials(1, 2027) == (1, 2027, "env-s2", "{ENV}")
    monkeypatch.setenv("ESPN_S2", "")
    monkeypatch.delenv("ESPN_SWID")
    assert server._get_espn_credentials(1, 2027) == (1, 2027, None, None)


# ------------------------------------------------------------------ 2. notes name real parameters
_NOTE_HINT = re.compile(r"call (\w+) with (\w+)=")


def _notes(obj, found: list[str] | None = None) -> list[str]:
    found = [] if found is None else found
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "note" and isinstance(value, str):
                found.append(value)
            else:
                _notes(value, found)
    elif isinstance(obj, list):
        for item in obj:
            _notes(item, found)
    return found


@pytest.mark.asyncio
async def test_every_parameter_hinted_in_a_note_exists_on_the_named_tool(espn):
    schemas = await _tool_schemas()
    notes = _notes(await get_team_roster_tool(team_id=12))
    notes += _notes(await get_my_current_matchup_tool(team_id=12))
    hints = [m for note in notes for m in _NOTE_HINT.findall(note)]
    assert hints, "the locked roster for team 12 should produce a scoring_period hint"
    for tool_name, param in hints:
        assert tool_name in schemas, f"note names unknown tool {tool_name}"
        assert param in schemas[tool_name]["properties"], f"{tool_name} has no {param}"
    # the old wording pointed at a parameter get_my_current_matchup does not have
    assert "scoring_period" not in schemas["get_my_current_matchup"]["properties"]
    assert all(not re.search(r"\bpass scoring_period=", n) for n in notes)


# ------------------------------------------------------------------ 3. category record invariant
@pytest.mark.asyncio
async def test_espn_record_is_a_category_record_in_each_category_league(client):
    settings = await client.get_league_settings()
    teams = await client.get_league_teams()
    assert settings.scoringSettings.scoringType == "H2H_CATEGORY"
    categories = len(settings.scoringSettings.scoringItems)
    completed = settings.status.currentMatchupPeriod - 1
    total = sum(
        t.record.overall.wins + t.record.overall.losses + (t.record.overall.ties or 0)
        for t in teams
    )
    assert total == categories * len(teams) * completed, "record must be category totals"
    assert all(t.recordType == "categories" for t in teams)
    assert all("not matchup wins" in (t.recordDescription or "") for t in teams)


# ------------------------------------------------------------------ 4. season stats records
@pytest.mark.asyncio
async def test_season_stats_matchup_record_is_bounded_by_completed_periods(client):
    settings = await client.get_league_settings()
    completed = settings.status.currentMatchupPeriod - 1
    for team_id in (8, 3, 12, 5):
        stats = await client.get_team_season_stats(team_id)
        assert stats.completedMatchupPeriods == completed
        assert stats.matchupWins + stats.matchupLosses + stats.matchupTies == completed
        assert stats.matchupTies == 0, "ties are a count, not null"
        assert stats.espnRecordType == "categories"
    mine = await client.get_team_season_stats(MY_TEAM)
    # period 1: team 8 beat team 3 six categories to three -> 1-0 matchup, 6-3 ESPN record
    assert (mine.matchupWins, mine.matchupLosses) == (1, 0)
    assert (mine.espnRecord.wins, mine.espnRecord.losses) == (6, 3)
    assert mine.winPercentage == 1.0 and mine.gamesBack == 0.0
    loser = await client.get_team_season_stats(3)
    assert (loser.matchupWins, loser.matchupLosses, loser.gamesBack) == (0, 1, 1.0)
    assert "matchup record" in loser.gamesBackDescription
    dumped = await get_team_season_stats_tool(team_id=3)
    assert "totalGamesPlayed" not in dumped, "ESPN sends 0; the field was never real"


def test_matchup_records_skip_undecided_and_count_ties():
    schedule = [
        {"matchupPeriodId": 1, "winner": "HOME", "home": {"teamId": 1}, "away": {"teamId": 2}},
        {"matchupPeriodId": 2, "winner": "TIE", "home": {"teamId": 1}, "away": {"teamId": 2}},
        # finished week ESPN has not closed, and the week in progress: neither counts
        {"matchupPeriodId": 3, "winner": "UNDECIDED", "home": {"teamId": 1}, "away": {"teamId": 2}},
        {"matchupPeriodId": 4, "winner": "HOME", "home": {"teamId": 1}, "away": {"teamId": 2}},
    ]
    records = ESPNFantasyBasketballClient._matchup_records_from_schedule(schedule, 4)
    assert (records[1].wins, records[1].losses, records[1].ties) == (1, 0, 1)
    assert (records[2].wins, records[2].losses, records[2].ties) == (0, 1, 1)
    assert records[1].completedMatchupPeriods == 2


# ------------------------------------------------------------------ 5. standings and my team
@pytest.mark.asyncio
async def test_league_teams_are_ranked_and_mark_my_team(espn):
    listing = await get_league_teams_tool()
    assert listing["count"] == 4, "one object, not one message per team"
    teams = listing["teams"]
    assert [t["id"] for t in teams] == [8, 5, 12, 3], "sorted by ESPN's record"
    assert [t["standingsRank"] for t in teams] == [1, 2, 3, 4]
    assert [t["isMyTeam"] for t in teams] == [True, False, False, False]
    assert teams[0]["matchupRecord"] == {
        "wins": 1,
        "losses": 0,
        "ties": 0,
        "completedMatchupPeriods": 1,
    }
    assert teams[-1]["matchupRecord"]["losses"] == 1


def _team(team_id: int, wins: int, losses: int, seed: int | None) -> Team:
    return Team(
        id=team_id,
        abbrev=f"T{team_id}",
        name=f"Team {team_id}",
        record=TeamRecord(overall=OverallRecord(wins=wins, losses=losses, ties=0)),
        playoffSeed=seed,
    )


def test_rank_teams_prefers_distinct_espn_seeds_then_record():
    by_seed = ESPNFantasyBasketballClient._rank_teams(
        [_team(1, 10, 2, 3), _team(2, 5, 7, 1), _team(3, 7, 5, 2)]
    )
    assert [t.id for t in by_seed] == [2, 3, 1], "ESPN's seed wins when it is informative"
    by_record = ESPNFantasyBasketballClient._rank_teams(
        [_team(1, 10, 2, 1), _team(2, 5, 7, 1), _team(3, 7, 5, 1)]
    )
    assert [t.id for t in by_record] == [1, 3, 2], "all-ones seeds fall back to the record"
    assert [t.standingsRank for t in by_record] == [1, 2, 3]


# ------------------------------------------------------------------ 6. no foreign roster entries
@pytest.mark.asyncio
async def test_no_response_roster_carries_another_teams_player(espn, client):
    for team_id in (8, 3, 12, 5):
        roster = await get_team_roster_tool(team_id=team_id)
        for entry in roster["entries"]:
            assert entry["playerPoolEntry"]["onTeamId"] == team_id
    matchup = await get_my_current_matchup_tool(team_id=12)
    for key in ("yourRoster", "opponentRoster"):
        side = matchup[key]
        for entry in side["entries"]:
            assert entry["playerPoolEntry"]["onTeamId"] == side["teamId"]
    analysis = await client.analyze_matchup(MY_TEAM, matchup_period=3)  # opponent is team 12
    names = {p.playerName for p in analysis.opponentPlayers}
    assert names == {"Loyal Forward", "Solid Wing"}, "stale entries never reach the analysis"


# ------------------------------------------------------------------ 7. status vs injury report
_note = ESPNFantasyBasketballClient._injury_status_note


def test_out_status_with_probable_report_is_flagged():
    report = {"status": "Day-To-Day", "shortComment": "Johnson (ankle) is probable for Friday."}
    note = _note("OUT", "Ankle - Sprain. Johnson (ankle) is probable for Friday.", report)
    assert note and "OUT" in note and "probable (Day-To-Day)" in note
    assert "projections use the fantasy status" in note


def test_consistent_statuses_are_not_flagged():
    assert _note("OUT", "Knee. Collins is out through Nov. 10.", {"status": "Out"}) is None
    assert _note("DAY_TO_DAY", "Big (back) is probable for Tuesday.", None) is None
    assert _note("QUESTIONABLE", None, {"status": "Day-To-Day"}) is None
    assert _note(None, "anything", {"status": "Out"}) is None


def test_active_status_with_out_report_is_flagged_from_details_alone():
    note = _note(
        "ACTIVE", "Wrist - Fracture; expected return 2026-12-01. He is out indefinitely.", None
    )
    assert note and "ACTIVE" in note and "says out" in note


@pytest.mark.asyncio
async def test_roster_players_never_pair_out_with_probable(espn):
    roster = await get_team_roster_tool()
    for entry in roster["entries"]:
        player = entry["playerPoolEntry"]["player"]
        details = (player.get("injuryDetails") or "").lower()
        if player.get("injuryStatus") == "OUT" and re.search(
            r"\b(probable|questionable)\b", details
        ):
            assert player.get("injuryStatusNote"), f"{player['fullName']}: OUT but {details!r}"
    collins = next(
        e["playerPoolEntry"]["player"]
        for e in roster["entries"]
        if e["playerPoolEntry"]["player"]["fullName"] == "Jon Collins"
    )
    assert collins["injuryStatus"] == "OUT" and "injuryStatusNote" not in collins


# ------------------------------------------------------------------ 8. closeness per category
def test_close_threshold_is_per_category():
    for category, margin in CLOSE_MARGINS.items():
        assert category_close_threshold(category, False, 100.0, None) == (
            margin,
            f"margin <= {margin:g} (about two strong player-games)",
        )
    # FG%: a 0.003 lead over 350 attempts is one basket -> close; the flat 0.002 never was
    threshold, rule = category_close_threshold("fieldGoalPercentage", True, 0.45, 350.0)
    assert threshold == pytest.approx(CLOSE_PERCENTAGE_MAKES / 350.0)
    assert 0.003 <= threshold and "made shots" in rule
    # unknown attempts fall back to a flat value
    assert category_close_threshold("freeThrowPercentage", True, 0.8, None)[0] == 0.015
    # unlisted counting category keeps the old 5% rule
    assert category_close_threshold("offensiveRebounds", False, 10.0, None)[0] == 2.0


@pytest.mark.asyncio
async def test_isclose_uses_each_categorys_scale(monkeypatch):
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=LEAGUE, year=YEAR)
    settings = _settings([0, 1, 19])  # points, blocks, FG%
    matchup = CurrentMatchup(
        matchupId=1,
        scoringPeriod=30,
        yourTeam=MatchupTeam(
            teamId=1,
            categoryScores={"points": 500.0, "blocks": 20.0, "fieldGoalPercentage": 0.4714},
            componentStats={"fieldGoalsMade": 165.0, "fieldGoalsAttempted": 350.0},
        ),
        opponentTeam=MatchupTeam(
            teamId=2,
            categoryScores={"points": 540.0, "blocks": 20.4, "fieldGoalPercentage": 0.4686},
            componentStats={"fieldGoalsMade": 164.0, "fieldGoalsAttempted": 350.0},
        ),
        yourRoster=_roster(1, [101]),
        opponentRoster=_roster(2, [201]),
    )
    # nobody has a game left: the projection equals the current score
    schedules = {1: _schedule(1, {101: [_day(-1)]}), 2: _schedule(2, {201: [_day(-1)]})}

    async def fake_stats(player_ids, timeframe):
        return [_stats(pid, timeframe, points=10.0, blocks=1.0) for pid in player_ids]

    with (
        patch.object(client, "get_league_settings", AsyncMock(return_value=settings)),
        patch.object(client, "get_matchup_for_period", AsyncMock(return_value=matchup)),
        patch.object(
            client,
            "get_matchup_period_dates",
            AsyncMock(return_value=(TODAY - timedelta(days=6), TODAY)),
        ),
        patch.object(
            client,
            "get_roster_schedule_summary",
            side_effect=lambda team_id, *a: schedules[team_id],
        ),
        patch.object(client, "get_player_stats", side_effect=fake_stats),
    ):
        analysis = await client.analyze_matchup(team_id=1, matchup_period=CURRENT_PERIOD)

    by_cat = {c.category: c for c in analysis.categoryProjections}
    assert by_cat["blocks"].margin == pytest.approx(0.4) and by_cat["blocks"].isClose
    assert by_cat["points"].margin == pytest.approx(40.0) and not by_cat["points"].isClose
    fg = by_cat["fieldGoalPercentage"]
    assert fg.margin == pytest.approx(1 / 350, abs=1e-4), "one made basket over the week"
    assert fg.isClose, fg.closenessRule
    assert fg.closeThreshold == pytest.approx(CLOSE_PERCENTAGE_MAKES / 350)
    assert set(analysis.closeCategories) == {"blocks", "fieldGoalPercentage"}


# ------------------------------------------------------------------ 9. priority follows close categories
def test_category_verdict_shows_the_number_behind_the_claim():
    assert category_verdict("blocks", 0.5) == ("hurts", "blocks (0.5/g)")
    assert category_verdict("blocks", 0.9) is None, "neither notable nor harmful"
    assert category_verdict("blocks", 1.4) == ("helps", "blocks (1.4/g)")
    assert category_verdict("threePointMade", 0.6) == ("hurts", "threePointMade (0.6/g)")
    assert category_verdict("threePointMade", 1.5) is None, "1.5 threes is neither strong nor weak"
    assert category_verdict("turnovers", 1.5) == ("helps", "turnovers (1.5/g)")
    assert category_verdict("fieldGoalPercentage", 0.58) == ("helps", "fieldGoalPercentage (58.0%)")
    assert category_verdict("freeThrowPercentage", 65.0) == ("hurts", "freeThrowPercentage (65.0%)")


@pytest.mark.asyncio
async def test_priority_rewards_close_categories_and_ignores_lost_causes(monkeypatch):
    """A rim-runner who moves two close categories outranks a scorer who only pads categories
    already lost by a mile, even though the rim-runner 'hurts' those lost categories."""
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=LEAGUE, year=YEAR)
    settings = _settings([0, 3, 1, 17, 19])  # points, assists, blocks, threes, FG%
    matchup = CurrentMatchup(
        matchupId=1,
        scoringPeriod=30,
        yourTeam=MatchupTeam(
            teamId=1,
            categoryScores={
                "points": 300.0,
                "assists": 50.0,
                "blocks": 10.0,
                "threePointMade": 20.0,
            },
            componentStats={"fieldGoalsMade": 150.0, "fieldGoalsAttempted": 320.0},
        ),
        opponentTeam=MatchupTeam(
            teamId=2,
            categoryScores={
                "points": 500.0,
                "assists": 120.0,
                "blocks": 10.5,
                "threePointMade": 60.0,
            },
            componentStats={"fieldGoalsMade": 148.0, "fieldGoalsAttempted": 320.0},
        ),
        yourRoster=_roster(1, [101, 102]),  # 101 rim-runner, 102 scorer
        opponentRoster=_roster(2, [201]),
    )
    three_games = [_day(0), _day(1), _day(2)]
    schedules = {
        1: _schedule(1, {101: three_games, 102: three_games}),
        2: _schedule(2, {201: three_games}),
    }
    projections = {
        101: _stats(
            101,
            "projections",
            points=8.0,
            assists=0.5,
            blocks=2.0,
            threePointMade=0.1,
            fieldGoalPercentage=70.0,
            fieldGoalsMade=3.5,
            fieldGoalsAttempted=5.0,
        ),
        102: _stats(
            102,
            "projections",
            points=25.0,
            assists=7.0,
            blocks=0.2,
            threePointMade=3.0,
            fieldGoalPercentage=42.0,
            fieldGoalsMade=8.0,
            fieldGoalsAttempted=19.0,
        ),
        201: _stats(
            201,
            "projections",
            points=20.0,
            assists=5.0,
            blocks=1.5,
            threePointMade=2.0,
            fieldGoalPercentage=45.0,
            fieldGoalsMade=5.0,
            fieldGoalsAttempted=11.0,
        ),
    }

    async def fake_stats(player_ids, timeframe):
        if timeframe == "projections":
            return [projections[pid] for pid in player_ids]
        return [_stats(pid, timeframe, points=0.0) for pid in player_ids]

    with (
        patch.object(client, "get_league_settings", AsyncMock(return_value=settings)),
        patch.object(client, "get_matchup_for_period", AsyncMock(return_value=matchup)),
        patch.object(
            client,
            "get_matchup_period_dates",
            AsyncMock(return_value=(TODAY - timedelta(days=3), TODAY + timedelta(days=3))),
        ),
        patch.object(
            client,
            "get_roster_schedule_summary",
            side_effect=lambda team_id, *a: schedules[team_id],
        ),
        patch.object(client, "get_player_stats", side_effect=fake_stats),
    ):
        analysis = await client.analyze_matchup(team_id=1, matchup_period=CURRENT_PERIOD)

    # preconditions: blocks and FG% are close, the other three are lost by a mile
    assert set(analysis.closeCategories) == {"blocks", "fieldGoalPercentage"}
    assert {"points", "assists", "threePointMade"} <= set(analysis.categoriesLosing)
    recs = {r.playerName: r for r in analysis.playerRecommendations}
    rim_runner, scorer = recs["Player 101"], recs["Player 102"]
    assert rim_runner.priority > scorer.priority
    assert set(rim_runner.closeCategoriesHelped) == {"blocks", "fieldGoalPercentage"}
    assert {"points", "assists", "threePointMade"} <= set(rim_runner.categoriesHurt)
    assert rim_runner.closeCategoriesHurt == [], "lost causes are not close categories"
    assert "not penalised" in rim_runner.reasoning and "blocks (2.0/g)" in rim_runner.reasoning
    assert set(scorer.closeCategoriesHurt) == {"blocks", "fieldGoalPercentage"}
    assert analysis.playerRecommendations[0] is rim_runner


# ------------------------------------------------------------------ 10. games gap and method
@pytest.mark.asyncio
async def test_expected_games_gap_is_itemised_and_method_is_stated(client):
    analysis = await client.analyze_matchup(MY_TEAM, matchup_period=3)
    assert analysis.yourGamesRemaining == 11 and analysis.yourExpectedGames == 8.0
    lines = analysis.expectedGamesBreakdown
    assert lines[0].startswith("Jon Collins: 3 scheduled, 0 expected (OUT;")
    assert lines[-1] == "11 scheduled - 3 discounted = 8 expected"
    assert analysis.opponentExpectedGamesBreakdown == [], "nobody discounted, nothing to explain"
    assert "OUT" in analysis.projectionMethod and "no confidence range" in analysis.projectionMethod
    assert analysis.projectionMethod.endswith("noisy.")
    opp = {p.playerName: p for p in analysis.opponentPlayers}
    assert opp["Solid Wing"].gamesRemaining == 4 and opp["Solid Wing"].expectedGames == 4.0
    assert set(opp["Solid Wing"].projectedPerGame) == {
        c.category for c in analysis.categoryProjections
    }


# ------------------------------------------------------------------ 11. compact output
def _has_none(obj) -> bool:
    """True if a null is anywhere in the output, except inside a player's `stats` dict, where
    ft_pct / fg_pct are documented as null exactly when the player has zero attempts."""
    if obj is None:
        return True
    if isinstance(obj, dict):
        return any(_has_none(v) for k, v in obj.items() if k != "stats")
    if isinstance(obj, list):
        return any(_has_none(v) for v in obj)
    return False


@pytest.mark.asyncio
async def test_tool_output_has_no_nulls_and_no_raw_stat_blocks(espn):
    outputs = [
        await get_league_teams_tool(),
        await get_team_roster_tool(),
        await get_my_current_matchup_tool(),
        await analyze_matchup_tool(matchup_period=3),
        await get_matchups_tool(),
    ]
    for output in outputs:
        assert not _has_none(output)
    matchup = outputs[2]
    assert "cumulativeScore" not in matchup["yourTeam"]
    assert (matchup["yourTeam"]["categoryWins"], matchup["yourTeam"]["categoryLosses"]) == (5, 4)
    for side in ("home", "away"):
        assert "cumulativeScore" not in outputs[4]["matchups"][0][side]
    player = matchup["yourRoster"]["entries"][0]["playerPoolEntry"]["player"]
    assert "eligibleSlots" not in player and "eligibleSlotNames" in player
    assert "jersey" not in player and "keeperValue" not in matchup["yourRoster"]["entries"][0]


# ------------------------------------------------------------------ 12. small fixes
@pytest.mark.asyncio
async def test_player_without_stat_line_reports_zero_games(client):
    roster = await client.get_team_roster(MY_TEAM)
    benched = next(e for e in roster.entries if e.playerPoolEntry.player.fullName == "Benched Guy")
    assert benched.playerPoolEntry.player.stats["gamesPlayed"] == 0


def test_lock_type_descriptions():
    describe = ESPNFantasyBasketballClient._describe_lock_type
    assert describe("INDIVIDUAL_GAME").startswith("Daily lineups")
    assert describe("FIRSTGAME_WEEKLY").startswith("Weekly lineups")
    unknown = describe("INDIVIDUAL_FIRSTGAME_WEEKLY")
    assert "not recognised" in unknown and "lineupLocked" in unknown
    assert describe(None) is None


def test_projection_timeframe_prefers_the_requested_season():
    client = ESPNFantasyBasketballClient(LEAGUE, YEAR)
    stats = [
        {"id": "102026", "averageStats": {"0": 5.0, "42": 70}, "stats": {"42": 70}},
        {"id": "102027", "averageStats": {"0": 20.0}, "stats": {"42": 82}},
    ]
    parsed = client._parse_player_stats_for_timeframe(stats, "projections")
    assert parsed["points"] == 20.0 and parsed["gamesPlayed"] == 82

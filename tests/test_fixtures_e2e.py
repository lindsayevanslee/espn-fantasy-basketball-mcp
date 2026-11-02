"""End-to-end tests over recorded-shape ESPN fixtures (tests/fixtures/).

Every ESPN request is answered from a JSON fixture by tests/fixture_espn.py and the clock is
frozen at noon Eastern on Sunday 2026-11-01, the last day of matchup period 2. Each test here
pins one behaviour observed (and misreported) against the live league:

1. analyze_matchup for a matchup that has not started returns projections, not an exception
2. matchup periods are weeks: period 3 is Nov 2-8, and get_matchups takes a matchup period
3. free agents carry real ownership percentages (ownership lives under player.ownership)
4. schedules can be looked up for arbitrary player IDs (streamers), with and without a roster
5. get_my_current_matchup keeps per-game averages when verbose=False; gamesPlayed is derived
6. settings spell out the acquisition limit, period dates and what a team record counts
7. a player ESPN still lists under a team but who was dropped is removed from today's roster
8. injury status comes with ESPN's reason and expected return date
plus: FT% is computed from made/attempted (null only for zero attempts), and the roster says
which scoring period it is for.
"""

from __future__ import annotations

import pytest

from espn_fantasy_basketball import (
    analyze_matchup as analyze_matchup_tool,
)
from espn_fantasy_basketball import (
    get_player_schedule as get_player_schedule_tool,
)
from espn_fantasy_basketball import (
    get_roster_schedule as get_roster_schedule_tool,
)
from espn_fantasy_basketball import (
    get_team_roster as get_team_roster_tool,
)
from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient
from tests.fixture_espn import use_fixtures

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


def _by_name(items, name):
    return next(
        x for x in items if getattr(x, "playerName", None) == name or x.get("playerName") == name
    )


# --------------------------------------------------------------------------- 1. unstarted matchup
@pytest.mark.asyncio
async def test_unstarted_matchup_returns_projections(client):
    """Default analyze_matchup targets the next period (3), whose cumulativeScore is null."""
    analysis = await client.analyze_matchup(MY_TEAM)

    assert analysis.opponentTeamId == 12
    cats = {c.category: c for c in analysis.categoryProjections}
    assert set(cats) == {
        "points",
        "blocks",
        "steals",
        "assists",
        "rebounds",
        "turnovers",
        "threePointMade",
        "fieldGoalPercentage",
        "freeThrowPercentage",
    }
    assert all(c.yourCurrent == 0 and c.opponentCurrent == 0 for c in cats.values())
    # projections come from roster per-game averages x games scheduled Nov 2-8:
    # Ava Guard (BOS, 4 games) + Cason Wallace (OKC, 4 games); Jon Collins is OUT (0 expected)
    # (projection averages are rounded to one decimal: 21.6 and 9.0 points per game)
    assert cats["points"].yourProjected == pytest.approx(21.6 * 4 + 9.0 * 4)
    assert analysis.yourGamesRemaining == 4 + 3 + 4, "scheduled games incl. the OUT player"
    assert analysis.yourExpectedGames == 8.0, "OUT player and unsigned bench player excluded"
    assert cats["freeThrowPercentage"].yourProjected is not None
    assert analysis.projectedCategoryWins + analysis.projectedCategoryLosses >= 7


@pytest.mark.asyncio
async def test_explicit_period_3_also_works(client, espn):
    """Period 3 carries ESPN's live not-started shape: cumulativeScore with scoreByStat: null."""
    raw = next(m for m in espn.load("league_mMatchup.json")["schedule"] if m["id"] == 5)
    assert raw["home"]["cumulativeScore"] == {
        "wins": 0,
        "losses": 0,
        "ties": 0,
        "statBySlot": None,
        "scoreByStat": None,
    }
    analysis = await client.analyze_matchup(MY_TEAM, matchup_period=3)
    assert analysis.matchupId == 5
    assert any(c.yourProjected for c in analysis.categoryProjections)


@pytest.mark.asyncio
async def test_fully_null_cumulative_score_also_works(client):
    """Period 14 carries the other variant, cumulativeScore: null."""
    analysis = await client.analyze_matchup(MY_TEAM, matchup_period=14)
    assert analysis.matchupId == 27 and analysis.opponentTeamId == 5
    assert all(c.yourCurrent == 0 for c in analysis.categoryProjections)


@pytest.mark.asyncio
async def test_analyze_matchup_tool_end_to_end(espn):
    result = await analyze_matchup_tool()
    assert result["opponentTeamId"] == 12
    assert result["categoryProjections"]


# --------------------------------------------------------------------------- 2. matchup periods
@pytest.mark.asyncio
async def test_period_3_resolves_to_nov_2_to_8(client):
    settings = await client.get_league_settings()
    dates = settings.scheduleSettings.matchupPeriodDates
    assert dates["1"] == ["2026-10-20", "2026-10-25"], "six-day opening week"
    assert dates["2"] == ["2026-10-26", "2026-11-01"]
    assert dates["3"] == ["2026-11-02", "2026-11-08"]
    assert dates["14"] == ["2027-01-18", "2027-01-24"], "14 is a January week, not Nov 2"
    assert dates["17"] == ["2027-02-08", "2027-02-21"], "two-week All-Star period"
    assert settings.status.currentMatchupPeriodDates == ["2026-10-26", "2026-11-01"]
    assert settings.status.latestScoringPeriodDate == "2026-11-01"
    assert "NOT a list of scoring periods" in settings.scheduleSettings.matchupPeriodsNote


@pytest.mark.asyncio
async def test_get_matchups_takes_a_matchup_period(client, espn):
    period3 = await client.get_matchups(matchup_period=3, team_id=MY_TEAM)
    assert [m.matchupPeriodId for m in period3] == [3]
    assert period3[0].home.teamId == MY_TEAM and period3[0].away.teamId == 12
    assert period3[0].home.categoryScores is None, "not started: no scores, no crash"

    current = await client.get_matchups(team_id=MY_TEAM)
    assert current[0].matchupPeriodId == 2 and current[0].away.categoryScores["points"] == 612
    # the week number is never sent to ESPN as a scoringPeriodId (day) query parameter
    for _, params, _ in espn.requests_for("league_mMatchup.json"):
        assert "scoringPeriodId" not in params


# --------------------------------------------------------------------------- 3. ownership
@pytest.mark.asyncio
async def test_free_agents_have_ownership_percentages(client):
    free_agents = await client.get_free_agents(size=10, verbose=True)
    owned = {p.fullName: p.ownership.percentOwned for p in free_agents}
    assert owned == {"Drew Wing": 61.2, "Kris Big": 48.9, "Zed Streamer": 5.5}
    assert all(v > 0 for v in owned.values())
    assert free_agents[0].ownership.percentStarted == 40.1
    # verbose stats: games derived when ESPN omits stat 42; shooting splits present
    wing = free_agents[0].stats
    assert wing["games_played"] == 8 and wing["fta"] == 2.2 and wing["ft_pct"] == 81.8


@pytest.mark.asyncio
async def test_search_reports_ownership_and_injury_detail(client):
    [big] = await client.search_players("kris big", limit=1)
    assert big.isFreeAgent is True and big.percentOwned == 48.9
    assert big.injuryStatus == "DAY_TO_DAY"
    assert big.injuryDetails.startswith("Back - Spasms")


# --------------------------------------------------------------------------- 4. player schedules
@pytest.mark.asyncio
async def test_player_schedule_by_id(client):
    summary = await client.get_players_schedule_summary([9001, 9002, 9003, 4242], matchup_period=3)

    assert summary.teamId is None
    assert summary.thisWeek == ["2026-11-02", "2026-11-08"]
    assert summary.nextWeek == ["2026-11-09", "2026-11-15"]
    by_id = {s.playerId: s for s in summary.playerSchedules}
    assert (by_id[9001].teamAbbreviation, by_id[9001].gamesThisWeek, by_id[9001].gamesNextWeek) == (
        "DEN",
        4,
        2,
    )
    assert (by_id[9002].teamAbbreviation, by_id[9002].gamesThisWeek, by_id[9002].gamesNextWeek) == (
        "LAL",
        2,
        3,
    )
    assert by_id[9003].playerName == "List Only", "resolved from the player list fallback"
    assert by_id[9003].gamesThisWeek == 4
    assert by_id[4242].note == "Player ID not recognised by ESPN"
    assert by_id[4242].includedInTotals is False
    assert summary.totalGamesThisWeek == 4 + 2 + 4
    assert by_id[9001].games[0].date == "2026-11-02"
    assert by_id[9001].games[0].datetimeISO == "2026-11-02T19:00:00-05:00"


@pytest.mark.asyncio
async def test_roster_schedule_can_include_streamers(client):
    summary = await client.get_roster_schedule_summary(
        MY_TEAM, matchup_period=3, extra_player_ids=[9001, 1001]
    )

    names = [s.playerName for s in summary.playerSchedules]
    assert names == ["Ava Guard", "Jon Collins", "Cason Wallace", "Benched Guy", "Streamer One"]
    streamer = summary.playerSchedules[-1]
    assert streamer.includedInTotals is False and "excluded from totals" in streamer.note
    assert streamer.gamesThisWeek == 4
    # totals cover rostered players who can play: BOS 4 + DAL 3 + OKC 4; the unsigned player 0
    assert summary.totalGamesThisWeek == 11
    assert summary.averageGamesPerPlayer == round(11 / 3, 2)
    assert summary.playerSchedules[3].note == "Not on an NBA roster; cannot play"


@pytest.mark.asyncio
async def test_schedule_tools_end_to_end(espn):
    standalone = await get_player_schedule_tool(player_ids=["9001"], matchup_period=3)
    assert standalone["playerSchedules"][0]["gamesThisWeek"] == 4
    with_roster = await get_roster_schedule_tool(matchup_period=3, player_ids=[9001])
    assert with_roster["teamId"] == MY_TEAM
    assert with_roster["playerSchedules"][-1]["includedInTotals"] is False
    with pytest.raises(ValueError, match="player_ids is required"):
        await get_player_schedule_tool(player_ids=[])
    with pytest.raises(ValueError, match="must be an integer"):
        await get_player_schedule_tool(player_ids=["abc"])


# --------------------------------------------------------------------------- 5. current matchup
@pytest.mark.asyncio
async def test_current_matchup_keeps_per_game_averages(client, espn):
    matchup = await client.get_my_current_matchup(MY_TEAM)

    assert matchup.opponentTeam.teamId == 3 and matchup.scoringPeriod == 13
    guard = matchup.yourRoster.entries[0].playerPoolEntry.player
    assert guard.fullName == "Ava Guard"
    assert guard.stats["points"] == 22.0 and guard.stats["assists"] == 7.0
    assert guard.stats["gamesPlayed"] == 8, "derived from 272 minutes / 34.0 per game"
    assert "totals" not in guard.stats, "verbose=False drops only the season totals"
    assert matchup.yourRoster.entries[0].todaysGame.opponent == "DAL"

    verbose = await client.get_my_current_matchup(MY_TEAM, verbose=True)
    totals = verbose.yourRoster.entries[0].playerPoolEntry.player.stats["totals"]
    assert totals["freeThrowsAttempted"] == 32 and totals["points"] == 176

    # current week: today's roster is ESPN's default, so no scoringPeriodId is sent
    for _, params, _ in espn.requests_for("league_mRoster.json"):
        assert "scoringPeriodId" not in params


@pytest.mark.asyncio
async def test_past_week_requests_its_final_day(client, espn):
    matchup = await client.get_matchup_for_period(MY_TEAM, 1)
    assert matchup.scoringPeriod == 6, "Oct 25 is scoring period 6"
    sent = {
        params.get("scoringPeriodId") for _, params, _ in espn.requests_for("league_mRoster.json")
    }
    assert sent == {"6"}


# --------------------------------------------------------------------------- shooting splits
@pytest.mark.asyncio
async def test_percentages_from_made_and_attempted(client):
    roster = await client.get_team_roster(MY_TEAM)
    stats = {
        e.playerPoolEntry.player.fullName: e.playerPoolEntry.player.stats for e in roster.entries
    }
    assert stats["Jon Collins"]["ft_pct"] == 80.0, "no FT% key from ESPN; 28 FTM / 35 FTA"
    assert stats["Jon Collins"]["fta"] == 5.0
    assert stats["Cason Wallace"]["ft_pct"] is None and stats["Cason Wallace"]["fta"] == 0.0
    assert stats["Cason Wallace"]["gamesPlayed"] == 9, "stat 42 present"
    assert stats["Ava Guard"]["fg_pct"] == 45.7 and stats["Ava Guard"]["ft_pct"] == 87.5
    assert stats["Benched Guy"] is None


@pytest.mark.asyncio
async def test_player_stats_tool_data_has_games_and_splits(client):
    [proj] = await client.get_player_stats([1001], "projections")
    assert proj.gamesPlayed == 82 and proj.freeThrowsAttempted == pytest.approx(3.88)
    assert proj.freeThrowPercentage == 87.6, "3.4 FTM / 3.88 FTA projected"


# --------------------------------------------------------------------------- 6. settings
@pytest.mark.asyncio
async def test_settings_describe_limits_and_records(client):
    settings = await client.get_league_settings()
    assert settings.acquisitionSettings.acquisitionLimitDescription == (
        "1 acquisition per matchup period; no season-long limit."
    )
    teams = await client.get_league_teams()
    mine = next(t for t in teams if t.id == MY_TEAM)
    assert (mine.record.overall.wins, mine.record.overall.losses, mine.record.overall.ties) == (
        11,
        6,
        1,
    )
    assert mine.recordType == "categories"
    assert "not matchup wins" in mine.recordDescription


@pytest.mark.parametrize(
    ("per_matchup", "per_day", "season", "expected"),
    [
        (1.0, False, -1, "1 acquisition per matchup period; no season-long limit."),
        (1.0, True, -1, "1 acquisition per day (scoring period); no season-long limit."),
        (4.0, False, 60, "4 acquisitions per matchup period; 60 for the whole season."),
        (-1, False, -1, "No limit on acquisitions per matchup period; no season-long limit."),
    ],
)
def test_acquisition_limit_description(per_matchup, per_day, season, expected):
    assert (
        ESPNFantasyBasketballClient._describe_acquisition_limit(per_matchup, per_day, season)
        == expected
    )


def test_record_description_by_scoring_type():
    describe = ESPNFantasyBasketballClient._describe_record
    assert describe("H2H_CATEGORY")[0] == "categories"
    assert describe("H2H_MOST_CATEGORIES")[0] == "matchups"
    assert describe("H2H_POINTS")[0] == "matchups"
    assert describe(None) == (None, None)


# --------------------------------------------------------------------------- 7. stale entries
@pytest.mark.asyncio
async def test_dropped_players_leave_todays_roster(client):
    roster = await client.get_team_roster(12)
    names = [e.playerPoolEntry.player.fullName for e in roster.entries]
    assert names == ["Loyal Forward", "Solid Wing"]
    assert roster.staleEntriesRemoved == ["Stale Center (onTeamId=0)", "Traded Guard (onTeamId=5)"]
    assert roster.scoringPeriodId == 13 and roster.scoringPeriodDate == "2026-11-01"
    assert roster.lineupLocked is True
    assert "pass scoring_period=14" in roster.note

    # a historical day is returned as stored: onTeamId is always the *current* team
    history = await client.get_team_roster(12, scoring_period=10)
    assert len(history.entries) == 4 and history.staleEntriesRemoved is None
    assert history.scoringPeriodId == 10 and history.scoringPeriodDate == "2026-10-29"


@pytest.mark.asyncio
async def test_team_roster_tool_reports_period(espn):
    roster = await get_team_roster_tool()
    assert roster["scoringPeriodId"] == 13 and roster["lineupLocked"] is False
    assert roster["staleEntriesRemoved"] is None and roster["note"] is None


@pytest.mark.asyncio
async def test_analysis_opponent_roster_excludes_dropped_player(client):
    analysis = await client.analyze_matchup(MY_TEAM, matchup_period=3)
    # Stale Center (TOR, 2 games Nov 2-8) must not add to the opponent's games
    assert analysis.opponentGamesRemaining == 3 + 4, "ATL 3 + MIN 4"


# --------------------------------------------------------------------------- 8. injury detail
@pytest.mark.asyncio
async def test_injury_details_surface_everywhere(client):
    roster = await client.get_team_roster(MY_TEAM)
    collins = roster.entries[1].playerPoolEntry.player
    assert collins.injuryStatus == "OUT"
    assert collins.injuryDetails == (
        "Knee - Sprain (left); expected return 2026-11-10. "
        "Collins (knee) is out through at least Nov. 10."
    )
    assert collins.injuryReturnDate == "2026-11-10"
    healthy = roster.entries[0].playerPoolEntry.player
    assert healthy.injuryDetails is None and healthy.injuryReturnDate is None

    free_agents = await client.get_free_agents()
    big = next(p for p in free_agents if p.fullName == "Kris Big")
    assert big.injuryDetails == "Back - Spasms (not specified). Big (back) is probable for Tuesday."
    assert big.injuryReturnDate is None

    analysis = await client.analyze_matchup(MY_TEAM, matchup_period=3)
    assert any(
        "Jon Collins (PF) is OUT (Knee - Sprain (left); expected return 2026-11-10" in w
        for w in analysis.lineupWarnings
    )


def test_injury_details_from_fantasy_player_object_shapes():
    details = ESPNFantasyBasketballClient._injury_details
    assert details({"injuryDetails": "Ankle sprain, out 2 weeks"}) == (
        "Ankle sprain, out 2 weeks",
        None,
    )
    assert details(
        {"injuries": [{"details": {"type": "Hamstring", "returnDate": "2026-12-01T05:00Z"}}]}
    ) == (
        "Hamstring; expected return 2026-12-01",
        "2026-12-01",
    )
    assert details({"injury": {"description": "Rest"}}) == ("Rest", None)
    assert details({}) == (None, None)


def test_injury_report_parsing_is_defensive():
    parse = ESPNFantasyBasketballClient._parse_injury_report
    assert parse(None) == {}
    assert (
        parse({"injuries": [{"injuries": [{"athlete": {}}, {"athlete": {"id": "x"}}, "junk"]}]})
        == {}
    )
    assert list(
        parse({"injuries": [{"injuries": [{"athlete": {"id": "77"}, "status": "Out"}]}]})
    ) == [77]


# --------------------------------------------------------------------------- games played
@pytest.mark.parametrize(
    ("stat_set", "expected"),
    [
        ({"stats": {"42": 12.0}}, 12),
        ({"stats": {"40": 272.0, "0": 176.0}, "averages": {"40": 34.0, "0": 22.0}}, 8),
        ({"stats": {"16": 76.0}, "averages": {"16": 9.5}}, 8),
        ({"stats": {"16": 76.0}}, None),
        ({}, None),
    ],
)
def test_games_played_derivation(stat_set, expected):
    assert ESPNFantasyBasketballClient._games_played(stat_set) == expected

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
    can_add_player as can_add_player_tool,
)
from espn_fantasy_basketball import (
    get_free_agents as get_free_agents_tool,
)
from espn_fantasy_basketball import (
    get_player_schedule as get_player_schedule_tool,
)
from espn_fantasy_basketball import (
    get_player_stats as get_player_stats_tool,
)
from espn_fantasy_basketball import (
    get_roster_schedule as get_roster_schedule_tool,
)
from espn_fantasy_basketball import (
    get_team_roster as get_team_roster_tool,
)
from espn_fantasy_basketball import (
    get_transactions as get_transactions_tool,
)
from espn_fantasy_basketball import (
    simulate_roster_move as simulate_roster_move_tool,
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
    assert (analysis.yourTeamAbbrev, analysis.opponentTeamAbbrev) == ("SA", "WW")
    assert analysis.opponentTeamName == "Waiver Wire Warriors"
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
    assert (period3[0].home.teamAbbrev, period3[0].away.teamAbbrev) == ("SA", "WW")
    assert period3[0].away.teamName == "Waiver Wire Warriors"
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
    # 3. waiver state: Zed Streamer was dropped today and clears Tuesday 08:00 ET
    by_name = {p.fullName: p for p in free_agents}
    assert by_name["Drew Wing"].availabilityStatus == "FREEAGENT"
    assert by_name["Drew Wing"].availabilityNote == "Free agent: can be added now"
    zed = by_name["Zed Streamer"]
    assert zed.availabilityStatus == "WAIVERS"
    assert zed.waiverProcessDateISO == "2026-11-03T03:00:00-05:00"
    assert zed.availabilityNote == "On waivers; claims process 2026-11-03T03:00:00-05:00"
    assert all(v > 0 for v in owned.values())
    assert free_agents[0].ownership.percentStarted == 40.1
    # verbose stats: games derived when ESPN omits stat 42; shooting splits present
    wing = free_agents[0].stats
    assert wing["games_played"] == 8 and wing["fta"] == 2.2 and wing["ft_pct"] == 81.8


@pytest.mark.asyncio
async def test_free_agents_tool_returns_one_object(espn):
    """A bare list would reach Claude as one JSON object per player."""
    result = await get_free_agents_tool(size=10)
    assert isinstance(result, dict)
    assert result["count"] == 3 and [p["fullName"] for p in result["players"]] == [
        "Drew Wing",
        "Kris Big",
        "Zed Streamer",
    ]
    many = await get_player_stats_tool(player_id=[1001, 1003], timeframe="season")
    assert many["count"] == 2 and {p["playerId"] for p in many["players"]} == {1001, 1003}
    one = await get_player_stats_tool(player_id=1001, timeframe="season")
    assert one["playerId"] == 1001 and "count" not in one


@pytest.mark.asyncio
async def test_search_reports_ownership_and_injury_detail(client):
    [zed] = await client.search_players("zed streamer", limit=1)
    assert zed.availabilityStatus == "WAIVERS" and zed.waiverProcessDateISO.startswith("2026-11-03")
    [big] = await client.search_players("kris big", limit=1)
    assert big.isFreeAgent is True and big.percentOwned == 48.9
    assert big.availabilityStatus == "FREEAGENT"
    assert big.injuryStatus == "DAY_TO_DAY"
    assert big.injuryDetails.startswith("Back (not specified)"), "matched by name"


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


@pytest.mark.asyncio
async def test_future_week_requests_its_first_day(client, espn):
    """Period 3 starts Monday Nov 2 = scoring period 14: ESPN returns the lineup set for it."""
    matchup = await client.get_matchup_for_period(MY_TEAM, 3)
    assert matchup.scoringPeriod == 14
    sent = {
        params.get("scoringPeriodId") for _, params, _ in espn.requests_for("league_mRoster.json")
    }
    # players come from today's roster (no scoringPeriodId), slots from the planned day (14)
    assert sent == {None, "14"}
    assert "today's players" in matchup.rosterNote and "scoring period 14" in matchup.rosterNote
    # a future day is still "current": dropped players are filtered out of it
    assert matchup.opponentRoster.staleEntriesRemoved == [
        "Stale Center (onTeamId=0)",
        "Traded Guard (onTeamId=5)",
    ]
    assert matchup.yourRoster.scoringPeriodDate == "2026-11-02"


# --------------------------------------------------------------------------- shooting splits
@pytest.mark.asyncio
async def test_percentages_from_made_and_attempted(client):
    roster = await client.get_team_roster(MY_TEAM)
    stats = {
        e.playerPoolEntry.player.fullName: e.playerPoolEntry.player.stats for e in roster.entries
    }
    assert stats["Jon Collins"]["ft_pct"] == 80.0, "no FT% key from ESPN; 28 FTM / 35 FTA"
    assert stats["Jon Collins"]["fta"] == 5.0
    # ESPN sends FT% 0.0 for Wallace's 0 attempts; that is not a percentage, so null + fta 0
    assert stats["Cason Wallace"]["ft_pct"] is None and stats["Cason Wallace"]["fta"] == 0.0
    assert stats["Cason Wallace"]["gamesPlayed"] == 9, "stat 42 present"
    assert stats["Ava Guard"]["fg_pct"] == 45.7 and stats["Ava Guard"]["ft_pct"] == 87.5
    # a player ESPN sends no stat line for is 0 games played, not "no data"
    assert (
        stats["Benched Guy"]["gamesPlayed"] == 0
        and "no season stat line" in (stats["Benched Guy"]["note"])
    )


@pytest.mark.asyncio
async def test_per_game_numbers_come_from_average_stats(client, espn):
    """ESPN's per-game block is `averageStats`. Ava Guard's fixture has no stat 42, so a parser
    reading the wrong key would have no per-game line at all; she must still show 22.0 points."""
    season = next(
        s
        for s in espn.load("league_mRoster.json")["teams"][0]["roster"]["entries"][0][
            "playerPoolEntry"
        ]["player"]["stats"]
        if s["id"] == "002027"
    )
    assert "averageStats" in season and "averages" not in season and "42" not in season["stats"]
    roster = await client.get_team_roster(MY_TEAM)
    guard = roster.entries[0].playerPoolEntry.player.stats
    assert (guard["points"], guard["minutes"], guard["gamesPlayed"]) == (22.0, 34.0, 8)


@pytest.mark.asyncio
async def test_nba_schedule_requests_the_given_day(client, espn):
    """ESPN's scoreboard reads `dates=YYYYMMDD`; `date=` is ignored and returns today."""
    games = await client.get_nba_schedule("2026-11-01")
    assert games
    sent = [params for _, params, _ in espn.requests_for("nba_scoreboard.json")]
    assert sent == [{"dates": "20261101"}]
    await client.get_nba_schedule()
    assert espn.requests_for("nba_scoreboard.json")[-1][1] == {}


@pytest.mark.asyncio
async def test_player_stats_tool_data_has_games_and_splits(client):
    [proj] = await client.get_player_stats([1001], "projections")
    assert proj.gamesPlayed == 82 and proj.freeThrowsAttempted == pytest.approx(3.88)
    assert proj.freeThrowPercentage == 87.6, "3.4 FTM / 3.88 FTA projected"


# --------------------------------------------------------------------------- 6. settings
@pytest.mark.asyncio
async def test_settings_describe_limits_and_records(client):
    settings = await client.get_league_settings()
    acq = settings.acquisitionSettings
    assert acq.matchupLimitPerScoringPeriod is True
    assert acq.acquisitionLimitDescription == (
        "1 per day (scoring period), so 7 for matchup period 2 (7 days); no season-long limit."
    )
    assert acq.effectiveLimitByMatchupPeriod["1"] == 6, "six-day opening week"
    assert acq.effectiveLimitByMatchupPeriod["3"] == 7
    assert acq.effectiveLimitByMatchupPeriod["17"] == 14, "two-week All-Star period"
    assert acq.effectiveLimitCurrentMatchup == 7
    # waiverProcessHour is UTC (8 -> 03:00 Eastern), matching the players' process dates
    assert (acq.waiverProcessHour, acq.waiverProcessHourTimezone) == (8, "UTC")
    assert acq.waiverProcessTimeLocal == "03:00 America/New_York"
    # 2. waiver order rule
    assert acq.waiverOrderReset is False
    assert "back of the waiver order after each successful claim" in acq.waiverOrderDescription
    teams = await client.get_league_teams()
    mine = next(t for t in teams if t.id == MY_TEAM)
    assert (mine.record.overall.wins, mine.record.overall.losses, mine.record.overall.ties) == (
        6,
        3,
        0,
    ), "one completed period of nine categories"
    assert mine.recordType == "categories"
    assert "not matchup wins" in mine.recordDescription
    # 2./4. waiver rank and acquisitions used vs the effective limit
    assert mine.waiverRank == 12
    assert mine.transactionCounter.acquisitions == 3
    assert mine.transactionCounter.matchupAcquisitionTotals == {"1": 2, "2": 1}
    assert (mine.acquisitionsThisMatchup, mine.acquisitionLimitThisMatchup) == (1, 7)
    assert mine.acquisitionsRemainingThisMatchup == 6
    warriors = next(t for t in teams if t.id == 12)
    assert (warriors.waiverRank, warriors.acquisitionsRemainingThisMatchup) == (5, 4)
    # live key scheme: 1=PG ... 5=C, with an unexplained key 0
    assert settings.rosterSettings.positionLimitNames == {
        "POS_0": 0,
        "PG": -1,
        "SG": -1,
        "SF": -1,
        "PF": -1,
        "C": 4,
    }


@pytest.mark.parametrize(
    ("per_matchup", "per_day", "season", "expected"),
    [
        (1.0, False, -1, "1 acquisition per matchup period; no season-long limit."),
        (1.0, True, -1, "1 per day (scoring period); no season-long limit."),
        (4.0, False, 60, "4 acquisitions per matchup period; 60 for the whole season."),
        (-1, False, -1, "No limit on acquisitions per matchup period; no season-long limit."),
    ],
)
def test_acquisition_limit_description(per_matchup, per_day, season, expected):
    assert (
        ESPNFantasyBasketballClient._describe_acquisition_limit(per_matchup, per_day, season)
        == expected
    )


def test_effective_acquisition_limits():
    f = ESPNFantasyBasketballClient._effective_acquisition_limits
    dates = {"1": ["2026-10-20", "2026-10-25"], "2": ["2026-10-26", "2026-11-01"]}
    assert f(1.0, True, dates) == {"1": 6, "2": 7}
    assert f(2.0, True, dates) == {"1": 12, "2": 14}
    assert f(4.0, False, dates) == {"1": 4, "2": 4}
    assert f(-1, False, dates) is None and f(None, True, dates) is None


def test_per_day_description_includes_the_week_total():
    f = ESPNFantasyBasketballClient._describe_acquisition_limit
    assert f(1.0, True, -1, days_in_current=6, current_period=1) == (
        "1 per day (scoring period), so 6 for matchup period 1 (6 days); no season-long limit."
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
    # the hint names the tool that has the parameter, so it can be followed from any response
    assert "get_team_roster with scoring_period=14" in roster.note

    # a historical day is returned as stored: onTeamId is always the *current* team
    history = await client.get_team_roster(12, scoring_period=10)
    assert len(history.entries) == 4 and history.staleEntriesRemoved is None
    assert history.scoringPeriodId == 10 and history.scoringPeriodDate == "2026-10-29"


@pytest.mark.asyncio
async def test_team_roster_tool_reports_period(espn):
    roster = await get_team_roster_tool()
    assert roster["scoringPeriodId"] == 13 and roster["lineupLocked"] is False
    # null fields are left out of tool output entirely
    assert "staleEntriesRemoved" not in roster and "note" not in roster
    # 7. which starting slots are locked for this scoring period
    assert roster["lockedSlots"] == ["PG: Ava Guard"]
    assert roster["unlockedSlots"] == ["PF: Jon Collins", "SG: Cason Wallace"]
    assert roster["entries"][0]["lineupLocked"] is True
    assert roster["entries"][1]["lineupLocked"] is False
    assert roster["entries"][3]["lineupSlotName"] == "BENCH", "bench is not a starting slot"


@pytest.mark.asyncio
async def test_fully_locked_roster_lists_no_unlocked_slots(client):
    roster = await client.get_team_roster(12)
    assert roster.lineupLocked is True
    assert roster.lockedSlots == ["PF: Loyal Forward", "SF: Solid Wing"]
    assert roster.unlockedSlots == []
    slim = await client.get_my_current_matchup(MY_TEAM)
    assert slim.yourRoster.lockedSlots == ["PG: Ava Guard"], "slim rosters keep lock state"


@pytest.mark.asyncio
async def test_analysis_opponent_roster_excludes_dropped_player(client):
    analysis = await client.analyze_matchup(MY_TEAM, matchup_period=3)
    # Stale Center (TOR, 2 games Nov 2-8) must not add to the opponent's games
    assert analysis.opponentGamesRemaining == 3 + 4, "ATL 3 + MIN 4"


# --------------------------------------------------------------------------- transactions
@pytest.mark.asyncio
async def test_transactions_explain_waiver_state(client):
    log = await client.get_transactions()
    assert [t.id for t in log] == ["t-101", "t-100", "t-98"], "newest first, no lineup saves"
    pending, drop, roster_drop = log
    assert (
        roster_drop.summary == "Waiver Wire Warriors dropped Stale Center (roster move, 2026-11-01)"
    )

    everything = await client.get_transactions(include_lineup_changes=True)
    assert [t.id for t in everything] == ["t-102", "t-101", "t-100", "t-98", "t-99"]
    assert everything[0].summary == (
        "Statistical Anomalies set lineup for scoring period 14 (future lineup change, 2026-11-01)"
    )
    lineup = everything[-1]
    assert pending.type == "WAIVER" and pending.status == "PENDING"
    assert pending.teamName == "Statistical Anomalies"
    assert pending.summary == (
        "Statistical Anomalies added Zed Streamer; dropped Benched Guy "
        "(waiver claim, pending, 2026-11-01)"
    )
    assert drop.summary == (
        "Fifth Team added Drew Wing; dropped Zed Streamer (free-agent move, 2026-11-01)"
    )
    assert drop.processDateISO == "2026-11-01T09:15:00-05:00"
    assert [i.type for i in drop.items] == ["DROP", "ADD"]
    assert drop.items[0].playerName == "Zed Streamer" and drop.items[0].toTeamId == 0
    assert lineup.summary == (
        "Waiver Wire Warriors set lineup for scoring period 12 (lineup change, 2026-10-31)"
    )

    mine = await client.get_transactions(team_id=MY_TEAM)
    assert [t.id for t in mine] == ["t-101"]
    assert [
        t.id for t in await client.get_transactions(team_id=MY_TEAM, include_lineup_changes=True)
    ] == [
        "t-102",
        "t-101",
    ]
    dropped_by_5 = await client.get_transactions(team_id=5, limit=1)
    assert dropped_by_5[0].id == "t-100"


@pytest.mark.asyncio
async def test_transactions_tool_end_to_end(espn):
    result = await get_transactions_tool(limit=2)
    assert result["count"] == 2
    assert result["transactions"][0]["items"][0]["playerName"] == "Zed Streamer"
    sent = [params for _, params, _ in espn.requests_for("league_mTransactions.json")]
    assert sent and all(p["view"] == "mTransactions2" for p in sent)
    with pytest.raises(ValueError, match="Invalid limit"):
        await get_transactions_tool(limit=0)


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
    assert collins.injuryReturnDateType == "reported", "'at least Nov. 10' is a timeline"
    # 5. games missed are visible against the team's games played
    assert collins.stats["teamGamesPlayed"] == 0 and collins.stats["gamesMissed"] == 0
    guard = roster.entries[0].playerPoolEntry.player
    assert (guard.stats["gamesPlayed"], guard.stats["teamGamesPlayed"]) == (8, 1), (
        "BOS played Oct 30 before the frozen clock; Nov 1 tips after it"
    )
    healthy = roster.entries[0].playerPoolEntry.player
    assert healthy.injuryDetails is None and healthy.injuryReturnDate is None

    # Dee Wing's report entry has no athlete.id, only a player-card link carrying the ID
    opponent = await client.get_team_roster(3)
    wing = opponent.entries[1].playerPoolEntry.player
    assert wing.injuryDetails == (
        "Ankle - Sprain (right); expected return 2026-11-03. "
        "Wing (ankle) is questionable for Monday."
    )
    # ESPN lists the next game as a day-to-day player's return date: flagged as a placeholder
    assert wing.injuryReturnDate == "2026-11-03" and wing.injuryReturnDateType == "placeholder"
    assert "next game" in wing.injuryReturnDateNote

    # Kris Big's entry has neither an ID nor a link: matched by name, and no detail key
    free_agents = await client.get_free_agents()
    big = next(p for p in free_agents if p.fullName == "Kris Big")
    assert big.injuryDetails == (
        "Back (not specified); expected return 2026-11-03. Big (back) is probable for Tuesday."
    )
    assert big.injuryReturnDateType == "placeholder"

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
    junk = {"injuries": [{"injuries": [{"athlete": {}}, {"athlete": {"id": "x"}}, "junk"]}]}
    assert parse(junk) == {}
    report = parse({"injuries": [{"injuries": [{"athlete": {"id": "77"}, "status": "Out"}]}]})
    assert list(report) == [77]


def test_injury_lookup_falls_back_from_id_to_link_to_name():
    parse = ESPNFantasyBasketballClient._parse_injury_report
    lookup = ESPNFantasyBasketballClient._injury_for
    report = parse(
        {
            "injuries": [
                {
                    "injuries": [
                        {"athlete": {"id": "1", "displayName": "By Id"}, "status": "Out"},
                        {
                            "athlete": {
                                "firstName": "Link",
                                "lastName": "Only",
                                "displayName": "Link Only",
                                "links": [{"href": "https://www.espn.com/nba/player/_/id/2/x"}],
                            },
                            "status": "Day-To-Day",
                        },
                        {"athlete": {"displayName": "Nikola Jokić"}, "status": "Questionable"},
                    ]
                }
            ]
        }
    )
    assert lookup(report, 1, "Someone Else")["status"] == "Out"
    assert lookup(report, 2, None)["status"] == "Day-To-Day", "ID taken from the link"
    assert lookup(report, 999, "Link Only")["status"] == "Day-To-Day", "name fallback"
    assert lookup(report, 3, "nikola jokic")["status"] == "Questionable", "accents ignored"
    assert lookup(report, 4, "Nobody") is None and lookup({}, 1, "x") is None


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


def test_parse_player_stats_reads_average_stats_without_games_played():
    client = ESPNFantasyBasketballClient(LEAGUE, YEAR)
    stats = client._parse_player_stats(
        [
            {
                "id": f"00{YEAR}",
                "averageStats": {"0": 18.5, "6": 7.0, "40": 31.0, "15": 3.0, "16": 4.0},
                "stats": {"0": 111.0, "6": 42.0, "40": 186.0, "15": 18.0, "16": 24.0},
            }
        ]
    )
    assert stats["points"] == 18.5 and stats["rebounds"] == 7.0
    assert stats["gamesPlayed"] == 6, "186 minutes / 31.0 per game"
    assert stats["ft_pct"] == 75.0
    # the earlier key name still parses, for any payload that uses it
    legacy = client._parse_player_stats(
        [{"id": f"00{YEAR}", "averages": {"0": 10.0}, "stats": {"0": 50.0, "42": 5.0}}]
    )
    assert (legacy["points"], legacy["gamesPlayed"]) == (10.0, 5)


@pytest.mark.parametrize(
    ("averages", "totals", "expected_ft"),
    [
        ({"20": 0.0, "15": 0.0, "16": 0.0}, {}, None),  # no attempts: ESPN's 0.0 is not a pct
        ({"20": 0.0, "15": 0.0, "16": 2.0}, {}, 0.0),  # attempts but none made: a real 0%
        ({"15": 3.0, "16": 4.0}, {}, 75.0),  # no ESPN key: made / attempted
        ({"20": 0.8, "15": 3.0, "16": 4.0}, {}, 80.0),  # ESPN key wins when present
        ({}, {"15": 28.0, "16": 35.0}, 80.0),  # totals only
        ({}, {}, None),
    ],
)
def test_ft_pct_is_null_exactly_when_no_attempts(averages, totals, expected_ft):
    splits = ESPNFantasyBasketballClient._shooting_splits(averages, totals, 7)
    assert splits["ft_pct"] == expected_ft


# --------------------------------------------------------------------------- basis, near band, notes
@pytest.mark.asyncio
async def test_basis_applies_to_both_teams(client):
    proj = await client.analyze_matchup(MY_TEAM, 3)
    season = await client.analyze_matchup(MY_TEAM, 3, basis="season")
    blend = await client.analyze_matchup(MY_TEAM, 3, basis="blend")
    assert (proj.basis, season.basis, blend.basis) == ("projections", "season", "blend")
    assert "same basis" in proj.projectionMethod and "basis='season'" in season.projectionMethod
    by = lambda a: {c.category: c for c in a.categoryProjections}  # noqa: E731
    # season actuals are a touch higher than projections in the fixture, on BOTH sides
    assert by(season)["points"].yourProjected > by(proj)["points"].yourProjected
    assert by(season)["points"].opponentProjected > by(proj)["points"].opponentProjected
    assert (
        by(proj)["points"].yourProjected
        < by(blend)["points"].yourProjected
        < by(season)["points"].yourProjected
    )
    assert season.basisNotes == [], "every player with games has a season line in the fixture"
    with pytest.raises(ValueError, match="Invalid basis"):
        await client.analyze_matchup(MY_TEAM, 3, basis="vibes")


@pytest.mark.asyncio
async def test_recommendations_cover_the_roster_with_side_by_side_lines(client):
    analysis = await client.analyze_matchup(MY_TEAM, 3)
    roster = await client.get_team_roster(MY_TEAM)
    rec_ids = {r.playerId for r in analysis.playerRecommendations}
    active_eligible = {e.playerId for e in roster.entries if e.lineupSlotName != "IR"}
    assert rec_ids == active_eligible, "every non-IR rostered player is listed"
    guard = next(r for r in analysis.playerRecommendations if r.playerName == "Ava Guard")
    assert guard.seasonPerGame["points"] == 22.0 and guard.projectedPerGame["points"] == 21.6
    assert guard.basisPerGame == guard.projectedPerGame and guard.seasonGamesPlayed == 8
    collins = next(r for r in analysis.playerRecommendations if r.playerName == "Jon Collins")
    assert collins.priority == 1 and collins.expectedGames == 0
    assert collins.reasoning.startswith("OUT (")
    assert "today's players" in analysis.rosterSource


@pytest.mark.asyncio
async def test_near_band_and_consistent_strategy_notes(client):
    analysis = await client.analyze_matchup(MY_TEAM, 3)
    by = {c.category: c for c in analysis.categoryProjections}
    # points: margin 24.5 against a close threshold of 20 -> not close, but near (<= 30)
    assert not by["points"].isClose and by["points"].closeness == "near"
    assert by["points"].nearThreshold == pytest.approx(30.0)
    assert by["blocks"].closeness == "close" and by["steals"].closeness == "clear"
    assert analysis.nearCategories == ["points", "threePointMade"]
    notes = "\n".join(analysis.strategyNotes)
    assert "Within reach" in notes
    prioritize = next(n for n in analysis.strategyNotes if n.startswith("Prioritize"))
    assert "close and near categories" in prioritize
    for cat in analysis.closeCategories + analysis.nearCategories:
        assert cat in prioritize
    assert "steals" not in prioritize, "a category safely won is not a priority"


# --------------------------------------------------------------------------- simulation and legality
@pytest.mark.asyncio
async def test_simulate_roster_move_reports_deltas_on_one_basis(client):
    sim = await client.simulate_roster_move(
        MY_TEAM, drop_ids=[1004], add_ids=[9001], matchup_period=3
    )
    assert sim.dropped == ["Benched Guy (1004)"] and sim.added == ["Streamer One (9001)"]
    assert (sim.expectedGamesBefore, sim.expectedGamesAfter) == (8.0, 12.0), "DEN has 4 games"
    assert (sim.projectedRecordBefore, sim.projectedRecordAfter) == ("6-3-0", "8-1-0")
    assert sim.categoriesFlipped == ["blocks: loss -> win", "rebounds: loss -> win"]
    points = next(d for d in sim.categoryDeltas if d.category == "points")
    assert points.delta == pytest.approx(12.9 * 4, abs=0.01), "added player's per-game x games"
    assert points.closenessBefore == "near" and points.closenessAfter == "clear"
    [added] = sim.addedPlayers
    assert added.playerName == "Streamer One" and added.gamesRemaining == 4
    assert sim.legality is not None and sim.legality.canMake
    assert sim.summary[0] == "Projected record 6-3-0 -> 8-1-0 on basis 'projections'"
    assert sim.basis == "projections" and sim.matchupPeriod == 3

    season = await client.simulate_roster_move(MY_TEAM, [1004], [9001], 3, basis="season")
    assert season.basis == "season" and season.projectedRecordBefore == "6-3-0"

    with pytest.raises(ValueError, match="at least one player"):
        await client.simulate_roster_move(MY_TEAM, [], [], 3)


@pytest.mark.asyncio
async def test_simulation_ignores_unknown_ids_and_says_so(client):
    sim = await client.simulate_roster_move(
        MY_TEAM, drop_ids=[424242], add_ids=[9001, 4242], matchup_period=3
    )
    assert sim.unknownDropIds == [424242] and sim.unknownAddIds == [4242]
    assert sim.added == ["Streamer One (9001)"]
    assert any("Unknown player IDs" in line for line in sim.summary)


@pytest.mark.asyncio
async def test_can_add_player_checks_size_positions_waivers_and_budget(client, monkeypatch):
    ok = await client.check_roster_move(MY_TEAM, [7001])
    assert ok.canMake and ok.rosterSizeNow == 4 and ok.rosterSizeAfter == 5 and ok.rosterLimit == 13
    assert ok.positionLimits == {"PG": -1, "SG": -1, "SF": -1, "PF": -1, "C": 4}
    assert ok.acquisitionsRemainingThisMatchup == 6
    assert ok.addedPlayerStatus == {"Drew Wing (7001)": "FREEAGENT: can be added now"}
    assert "default (primary) position" in ok.positionLimitBasis

    # a player on waivers is a claim, not an add; an owned player is not addable at all
    waivers = await client.check_roster_move(MY_TEAM, [7003, 2001])
    assert not waivers.canMake
    assert any("owned by Rim Runners" in r for r in waivers.reasons)
    assert any("on waivers" in w for w in waivers.warnings)
    assert waivers.addedPlayerStatus["Zed Streamer (7003)"].startswith(
        "WAIVERS: claim processes 2026-11-03"
    )

    # position limit: pretend the league allows 2 centers; Benched Guy + Kris Big + Stale Center = 3
    real = client.get_league_settings

    async def two_centers():
        settings = await real()
        settings.rosterSettings.positionLimitNames["C"] = 2
        return settings

    monkeypatch.setattr(client, "get_league_settings", two_centers)
    too_many = await client.check_roster_move(MY_TEAM, [7002, 3001])
    assert not too_many.canMake
    assert any("primary position is C; the limit is 2" in r for r in too_many.reasons)
    assert too_many.positionCountsAfterByDefaultPosition["C"] == 3
    allowed_with_drop = await client.check_roster_move(MY_TEAM, [7002, 3001], drop_ids=[1004])
    assert (
        allowed_with_drop.canMake
        and allowed_with_drop.positionCountsAfterByDefaultPosition["C"] == 2
    )


@pytest.mark.asyncio
async def test_new_tools_end_to_end(espn):
    sim = await simulate_roster_move_tool(drop_ids=["1004"], add_ids=["9001"], matchup_period=3)
    assert sim["projectedRecordAfter"] == "8-1-0" and sim["legality"]["canMake"] is True
    check = await can_add_player_tool(add_ids=[7001])
    assert check["canMake"] is True and check["rosterSizeAfter"] == 5
    with pytest.raises(ValueError, match="add_ids is required"):
        await can_add_player_tool(add_ids=[])


# --------------------------------------------------------------------------- transactions period, bases
@pytest.mark.asyncio
async def test_settings_say_which_matchup_period_an_add_counts_against(client):
    settings = await client.get_league_settings()
    status = settings.status
    assert (status.transactionScoringPeriod, status.transactionScoringPeriodDate) == (
        14,
        "2026-11-02",
    )
    assert status.transactionMatchupPeriod == 3
    assert status.transactionNote.startswith(
        "Adds made now count against matchup period 3 (2026-11-02 to 2026-11-08)"
    )


@pytest.mark.asyncio
async def test_free_agents_carry_actuals_and_projections_side_by_side(client):
    [wing, big, zed] = await client.get_free_agents(size=10, verbose=True)
    assert wing.stats["points"] == 14.5 and wing.projections["points"] == 14.4
    assert wing.projections["games_played"] == 82 and wing.stats["games_played"] == 8
    assert wing.stats["teamGamesPlayed"] == 0, "GSW's first fixture game is Nov 2"
    assert zed.projections is not None and big.projections is not None
    slim = await client.get_free_agents(size=10)
    assert slim[0].stats is None and slim[0].projections is None


@pytest.mark.asyncio
async def test_compare_players_keeps_every_basis_apart(client):
    cmp = await client.compare_players(
        [1001, 7001], ["points", "rebounds"], timeframe="projections"
    )
    assert cmp.basis == "projections" and set(cmp.bases) == {"projections", "season"}
    assert [p.timeframe for p in cmp.players] == ["projections", "projections"]
    assert cmp.winners_by_basis["season"]["points"] == 1001
    assert "compare within one basis only" in cmp.note
    default = await client.compare_players([1001, 7001])
    assert default.basis == "season"


def test_return_date_classification():
    f = ESPNFantasyBasketballClient._return_date_type
    assert f(None, None) == (None, None)
    assert (
        f({"status": "Out", "shortComment": "out at least two weeks"}, "2026-11-20")[0]
        == "reported"
    )
    assert (
        f({"status": "Day-To-Day", "shortComment": "questionable Monday"}, "2026-11-03")[0]
        == "placeholder"
    )
    assert (
        f(
            {"status": "Out", "date": "2026-11-01T17:35Z", "shortComment": "out Monday"},
            "2026-11-03",
        )[0]
        == "placeholder"
    )
    assert (
        f({"status": "Out", "date": "2026-11-01T17:35Z", "shortComment": "out"}, "2026-11-20")[0]
        == "reported"
    )


def test_blend_averages_lines_and_recomputes_percentages():
    from espn_fantasy_basketball_mcp.analysis import _blend
    from espn_fantasy_basketball_mcp.models import PlayerStats

    a = PlayerStats(
        playerId=1,
        playerName="A",
        timeframe="projections",
        points=20.0,
        freeThrowsMade=4.0,
        freeThrowsAttempted=5.0,
        gamesPlayed=82,
    )
    b = PlayerStats(
        playerId=1,
        playerName="A",
        timeframe="season",
        points=10.0,
        freeThrowsMade=2.0,
        freeThrowsAttempted=4.0,
        gamesPlayed=8,
    )
    blended = _blend(a, b)
    assert blended.timeframe == "blend" and blended.points == 15.0
    assert blended.freeThrowsAttempted == 4.5 and blended.freeThrowPercentage == pytest.approx(66.7)


# --------------------------------------------------------------------------- scoring period echo, lock rule
@pytest.mark.asyncio
async def test_requested_scoring_period_is_sent_and_echoed(client, espn):
    today = await client.get_team_roster(MY_TEAM)
    assert today.requestedScoringPeriod is None and today.espnScoringPeriodId == 13
    past = await client.get_team_roster(MY_TEAM, scoring_period=10)
    assert past.requestedScoringPeriod == 10 and past.scoringPeriodId == 10
    sent = [
        params.get("scoringPeriodId") for _, params, _ in espn.requests_for("league_mRoster.json")
    ]
    assert sent == [None, "10"], "each day is its own ESPN request, not a cached copy"
    # and its own cache entry: the key includes the query parameters
    url = f"{client.BASE_URL}/seasons/2027/segments/0/leagues/12345"
    k10 = client._cache_key(url, {"view": ["mRoster", "mTeam"], "scoringPeriodId": "10"}, None)
    k11 = client._cache_key(url, {"view": ["mRoster", "mTeam"], "scoringPeriodId": "11"}, None)
    assert k10 != k11 != client._cache_key(url, {"view": ["mRoster", "mTeam"]}, None)
    # ESPN echoes the requested period (verified live); the fixture does the same
    assert past.espnScoringPeriodId == 10


@pytest.mark.asyncio
async def test_requested_equals_echoed_for_past_current_and_future(client, espn):
    """One run, three days: the period asked for is the period ESPN reports back."""
    for requested in (10, None, 14):
        roster = await client.get_team_roster(MY_TEAM, scoring_period=requested)
        expected = requested if requested is not None else 13
        assert roster.requestedScoringPeriod == requested
        assert roster.espnScoringPeriodId == expected == roster.scoringPeriodId
        assert "echoed" not in (roster.note or "")


@pytest.mark.asyncio
async def test_mismatched_echo_is_called_out(client, espn):
    espn.echo_scoring_period = False  # an ESPN that ignored the parameter
    roster = await client.get_team_roster(MY_TEAM, scoring_period=10)
    assert roster.requestedScoringPeriod == 10 and roster.espnScoringPeriodId == 13
    assert "ESPN echoed scoringPeriodId 13 for a request of 10" in roster.note


@pytest.mark.asyncio
async def test_game_annotations_follow_the_requested_day(client, espn):
    """A roster for Wednesday carries Wednesday's games, not today's (live report 2026-11-10)."""
    for requested, day in ((10, "2026-10-29"), (None, "2026-11-01"), (14, "2026-11-02")):
        roster = await client.get_team_roster(MY_TEAM, scoring_period=requested)
        assert roster.gamesDate == day == roster.scoringPeriodDate
        for entry in roster.entries:
            if entry.todaysGame is not None:
                assert entry.todaysGame.date == day, entry.playerPoolEntry.player.fullName
    by_name = lambda r: {e.playerPoolEntry.player.fullName: e.todaysGame for e in r.entries}  # noqa: E731
    monday = by_name(await client.get_team_roster(MY_TEAM, scoring_period=14))
    assert monday["Ava Guard"].opponent == "CHA" and monday["Ava Guard"].date == "2026-11-02"
    assert monday["Jon Collins"] is None, "DAL plays Tuesday, not Monday"
    today = by_name(await client.get_team_roster(MY_TEAM))
    assert today["Ava Guard"].opponent == "DAL" and today["Jon Collins"].opponent == "BOS"
    sent = [p.get("dates") for _, p, _ in espn.requests_for("nba_scoreboard.json")]
    sent += [p.get("dates") for _, p, _ in espn.requests_for("nba_scoreboard_20261102.json")]
    assert "20261102" in sent and "20261101" in sent, "the scoreboard is asked for by date"


@pytest.mark.asyncio
async def test_daily_lock_note_points_at_tomorrow(client):
    roster = await client.get_team_roster(12)
    assert roster.lineupLockRule == "INDIVIDUAL_GAME"
    assert roster.lineupLockDescription.startswith("Daily lineups")
    assert "daily lock" in roster.note and "scoring_period=14" in roster.note
    analysis = await client.analyze_matchup(MY_TEAM, 3)
    assert analysis.lineupLockRule == "INDIVIDUAL_GAME"
    assert any(
        w.endswith("move to bench and start a healthy player") for w in analysis.lineupWarnings
    )


def _with_lock_rule(client, monkeypatch, rule: str):
    """The same league with a different lineupLocktimeType."""
    real = client.get_league_settings

    async def patched():
        settings = await real()
        settings.rosterSettings.lineupLocktimeType = rule
        settings.rosterSettings.lineupLocktimeDescription = (
            ESPNFantasyBasketballClient._describe_lock_type(rule)
        )
        return settings

    monkeypatch.setattr(client, "get_league_settings", patched)
    return client


@pytest.fixture(params=["FIRSTGAME_WEEKLY", "INDIVIDUAL_FIRSTGAME_WEEKLY"])
def weekly_lock(client, monkeypatch, request):
    return _with_lock_rule(client, monkeypatch, request.param)


def test_every_lock_rule_seen_live_is_described():
    """Fail loudly here when ESPN sends a code the server has not met; the tool output
    already says 'not recognised' for one, but the vocabulary should grow, not the notes."""
    from espn_fantasy_basketball_mcp.constants import LINEUP_LOCK_DESCRIPTIONS, WEEKLY_LOCK_RULES

    seen_live = {"INDIVIDUAL_GAME", "FIRSTGAME_WEEKLY", "INDIVIDUAL_FIRSTGAME_WEEKLY"}
    assert seen_live <= set(LINEUP_LOCK_DESCRIPTIONS)
    assert WEEKLY_LOCK_RULES == {"FIRSTGAME_WEEKLY", "INDIVIDUAL_FIRSTGAME_WEEKLY"}
    assert "his first game" in ESPNFantasyBasketballClient._describe_lock_type(
        "INDIVIDUAL_FIRSTGAME_WEEKLY"
    ).replace("that player's", "his")
    unknown = ESPNFantasyBasketballClient._describe_lock_type("SOMETHING_NEW")
    assert "not recognised" in unknown and "lineupLocked" in unknown


@pytest.mark.asyncio
async def test_unknown_lock_rule_defers_to_the_slot_flags(client, monkeypatch):
    _with_lock_rule(client, monkeypatch, "SOMETHING_NEW")
    roster = await client.get_team_roster(12)
    assert roster.lineupLockRule == "SOMETHING_NEW"
    assert "not recognised" in roster.note and "lineupLocked flags" in roster.note
    assert "scoring_period=" not in roster.note, "no daily-lock advice for an unknown rule"


@pytest.mark.asyncio
async def test_weekly_lock_changes_every_lineup_message(weekly_lock):
    client = weekly_lock
    roster = await client.get_team_roster(12)
    assert roster.lineupLockRule in ("FIRSTGAME_WEEKLY", "INDIVIDUAL_FIRSTGAME_WEEKLY")
    how = (
        "each player's slot locks at his first game of the week"
        if roster.lineupLockRule == "INDIVIDUAL_FIRSTGAME_WEEKLY"
        else "every slot locked at the week's first game"
    )
    assert roster.note == (
        f"Lineup is locked for the rest of matchup period 2 (weekly lock: {how}); lineup "
        "changes apply from matchup period 3 starting 2026-11-02"
    )
    # the week in progress: nothing can be done about an OUT starter
    current = await client.analyze_matchup(MY_TEAM, 2)
    assert current.lineupLockRule == roster.lineupLockRule
    collins = next(w for w in current.lineupWarnings if w.startswith("Jon Collins"))
    assert "locked for the week" in collins and "matchup period 3" in collins
    assert not any("tip-off" in w or "move to bench" in w for w in current.lineupWarnings)
    # next week: act before the first game locks every slot
    upcoming = await client.analyze_matchup(MY_TEAM, 3)
    collins = next(w for w in upcoming.lineupWarnings if w.startswith("Jon Collins"))
    assert collins.endswith("bench or replace him before the week's first game locks every slot")
    # a simulated add this week carries the caveat; next week it does not
    sim_now = await client.simulate_roster_move(MY_TEAM, [1004], [9001], matchup_period=2)
    assert any("Weekly lineup lock" in line for line in sim_now.summary)
    sim_next = await client.simulate_roster_move(MY_TEAM, [1004], [9001], matchup_period=3)
    assert not any("Weekly lineup lock" in line for line in sim_next.summary)

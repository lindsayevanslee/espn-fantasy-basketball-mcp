"""Tests for analyze_matchup projection math.

Everything the method fetches is mocked at the client-method boundary, so these tests
exercise the projection and recommendation logic without any network access.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient
from espn_fantasy_basketball_mcp.models import (
    AcquisitionSettings,
    CurrentMatchup,
    LeagueSettings,
    LeagueStatus,
    MatchupTeam,
    Player,
    PlayerPoolEntry,
    PlayerSchedule,
    PlayerScheduleGame,
    PlayerStats,
    Roster,
    RosterEntry,
    RosterScheduleSummary,
    RosterSettings,
    ScheduleSettings,
    ScoringItem,
    ScoringSettings,
    TradeSettings,
)

# Everything here is pinned to UTC: the client computes "now" in MY_TIMEZONE, so the test
# sets that to UTC too. Using the system-local date would straddle midnight in some zones.
NOW = datetime.now(timezone.utc)
TODAY = NOW.date()
CURRENT_PERIOD = 5


def _day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def _settings(stat_ids: list[int]) -> LeagueSettings:
    return LeagueSettings(
        leagueId=12345,
        leagueName="Test League",
        seasonId=2027,
        size=10,
        scoringSettings=ScoringSettings(
            scoringType="H2H_CATEGORY",
            scoringItems=[ScoringItem(statId=i, points=1.0) for i in stat_ids],
        ),
        scheduleSettings=ScheduleSettings(
            matchupPeriodCount=20,
            matchupPeriodLength=1,
            matchupPeriods={},
            periodTypeId=2,
            playoffTeamCount=4,
            playoffMatchupPeriodLength=1,
        ),
        rosterSettings=RosterSettings(
            lineupSlotCounts={}, positionLimits={}, lineupLocktimeType="INDIVIDUAL_GAME"
        ),
        acquisitionSettings=AcquisitionSettings(
            acquisitionType="WAIVERS_TRADITIONAL",
            waiverHours=24,
            waiverProcessDays=["SUNDAY"],
            waiverProcessHour=3,
            matchupAcquisitionLimit=4.0,
            matchupLimitPerScoringPeriod=False,
        ),
        tradeSettings=TradeSettings(vetoVotesRequired=4, revisionHours=48),
        status=LeagueStatus(
            currentMatchupPeriod=CURRENT_PERIOD,
            latestScoringPeriod=30,
            firstScoringPeriod=1,
            finalScoringPeriod=170,
            isActive=True,
        ),
    )


def _entry(
    pid: int,
    slot: int = 0,
    injury: str | None = None,
    pro_team_id: int | None = 2,
    pro_team_abbrev: str | None = "BOS",
) -> RosterEntry:
    return RosterEntry(
        playerId=pid,
        lineupSlotId=slot,
        lineupSlotName={0: "PG", 1: "SG", 12: "BENCH", 13: "IR"}.get(slot),
        injuryStatus=injury,
        playerPoolEntry=PlayerPoolEntry(
            id=pid,
            player=Player(
                id=pid,
                fullName=f"Player {pid}",
                defaultPositionId=1,
                proTeamId=pro_team_id,
                proTeamAbbrev=pro_team_abbrev,
                injuryStatus=injury,
            ),
        ),
    )


def _roster(team_id: int, player_ids: list[int]) -> Roster:
    return Roster(teamId=team_id, entries=[_entry(pid) for pid in player_ids])


def _schedule(team_id: int, games_by_player: dict[int, list[str]]) -> RosterScheduleSummary:
    schedules = [
        PlayerSchedule(
            playerId=pid,
            playerName=f"Player {pid}",
            teamAbbreviation="BOS",
            games=[PlayerScheduleGame(date=d, opponent="MIA", is_home=True) for d in dates],
            gamesThisWeek=len(dates),
            gamesNextWeek=0,
        )
        for pid, dates in games_by_player.items()
    ]
    total = sum(len(d) for d in games_by_player.values())
    return RosterScheduleSummary(
        teamId=team_id,
        scoringPeriod=CURRENT_PERIOD,
        playerSchedules=schedules,
        totalGamesThisWeek=total,
        averageGamesPerPlayer=total / max(1, len(schedules)),
    )


def _stats(pid: int, timeframe: str, **values) -> PlayerStats:
    return PlayerStats(playerId=pid, playerName=f"Player {pid}", timeframe=timeframe, **values)


@pytest.mark.asyncio
async def test_current_week_projection_only_counts_games_from_today(monkeypatch):
    """Games already played are in the current score; projecting them again double counts."""
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    settings = _settings([0, 20])  # points, FT%

    matchup = CurrentMatchup(
        matchupId=1,
        scoringPeriod=30,
        yourTeam=MatchupTeam(
            teamId=1, teamName="Me", categoryScores={"points": 100.0, "freeThrowPercentage": 0.80}
        ),
        opponentTeam=MatchupTeam(
            teamId=2, teamName="Them", categoryScores={"points": 90.0, "freeThrowPercentage": 0.78}
        ),
        yourRoster=_roster(1, [101, 102]),
        opponentRoster=_roster(2, [201]),
    )

    # Mine: 101 has played 2 of 3 games (1 left); 102 has 1 game left.
    # Theirs: 201 has played 1 of 3 (2 left), plus a game in *next* week's window that the
    # schedule summary includes (for gamesNextWeek) but that must not count for this matchup.
    my_schedule = _schedule(1, {101: [_day(-2), _day(-1), _day(1)], 102: [_day(1)]})
    their_schedule = _schedule(2, {201: [_day(-1), _day(1), _day(2), _day(5)]})

    projections = [
        _stats(101, "projections", points=20.0, freeThrowPercentage=85.0),
        _stats(102, "projections", points=5.0, freeThrowPercentage=60.0),
        _stats(201, "projections", points=10.0, freeThrowPercentage=95.0),
    ]
    recent = [_stats(pid, "last_7", points=0.0) for pid in (101, 102, 201)]

    async def fake_stats(player_ids, timeframe):
        return projections if timeframe == "projections" else recent

    async def fake_schedule(team_id, start, end, period):
        return my_schedule if team_id == 1 else their_schedule

    with (
        patch.object(client, "get_league_settings", AsyncMock(return_value=settings)),
        patch.object(client, "get_matchup_for_period", AsyncMock(return_value=matchup)),
        patch.object(
            client,
            "get_matchup_period_dates",
            AsyncMock(return_value=(TODAY - timedelta(days=3), TODAY + timedelta(days=3))),
        ),
        patch.object(client, "get_roster_schedule_summary", side_effect=fake_schedule),
        patch.object(client, "get_player_stats", side_effect=fake_stats),
    ):
        analysis = await client.analyze_matchup(team_id=1, matchup_period=CURRENT_PERIOD)

    points = next(c for c in analysis.categoryProjections if c.category == "points")
    # 100 current + 20*1 (player 101) + 5*1 (player 102); NOT 100 + 20*3 + 5*1 = 165
    assert points.yourProjected == pytest.approx(125.0)
    # 90 current + 10*2; NOT 90 + 10*3 = 120 (played game) nor 90 + 10*3 (next-week game)
    assert points.opponentProjected == pytest.approx(110.0)
    assert points.projectedResult == "win"

    # Totals and per-player counts are remaining games, not games in the week
    assert analysis.yourGamesRemaining == 2
    assert analysis.opponentGamesRemaining == 2
    by_id = {r.playerId: r for r in analysis.playerRecommendations}
    assert by_id[101].gamesRemaining == 1
    assert by_id[102].gamesRemaining == 1

    # FT% is a losing category (their 95% shooter), so shooting ability is evaluated.
    # PlayerStats percentages are on a 0-100 scale: 85.0 helps, 60.0 hurts.
    assert "freeThrowPercentage" in analysis.categoriesLosing
    assert "freeThrowPercentage" in by_id[101].categoriesHelped
    assert "freeThrowPercentage" in by_id[102].categoriesHurt
    assert "freeThrowPercentage" not in by_id[102].categoriesHelped


def test_games_remaining_by_player_counts_today_and_later_when_only_dates_known():
    schedule = _schedule(1, {7: [_day(-1), _day(0), _day(2)], 8: [_day(-5)], 9: []})
    remaining = ESPNFantasyBasketballClient._games_remaining_by_player(schedule, NOW)
    assert remaining == {7: 2, 8: 0, 9: 0}


def test_games_remaining_by_player_respects_matchup_window():
    schedule = _schedule(1, {7: [_day(0), _day(2), _day(3), _day(6)]})
    remaining = ESPNFantasyBasketballClient._games_remaining_by_player(
        schedule, NOW, window_end=TODAY + timedelta(days=3)
    )
    assert remaining == {7: 3}


def test_games_remaining_by_player_uses_tip_off_time_when_known():
    started = (NOW - timedelta(hours=1)).isoformat()
    upcoming = (NOW + timedelta(hours=3)).isoformat()
    schedule = RosterScheduleSummary(
        teamId=1,
        scoringPeriod=CURRENT_PERIOD,
        playerSchedules=[
            PlayerSchedule(
                playerId=7,
                playerName="Player 7",
                teamAbbreviation="BOS",
                games=[
                    PlayerScheduleGame(
                        date=_day(0), opponent="MIA", is_home=True, datetimeISO=started
                    ),
                    PlayerScheduleGame(
                        date=_day(0), opponent="MIA", is_home=True, datetimeISO=upcoming
                    ),
                    PlayerScheduleGame(date=_day(1), opponent="MIA", is_home=True),  # date only
                ],
                gamesThisWeek=3,
                gamesNextWeek=0,
            )
        ],
        totalGamesThisWeek=3,
        averageGamesPerPlayer=3.0,
    )
    remaining = ESPNFantasyBasketballClient._games_remaining_by_player(schedule, NOW)
    assert remaining == {7: 2}, "a game that has tipped off is no longer remaining"


def test_games_remaining_by_player_skips_unparseable_dates():
    schedule = _schedule(1, {7: ["not-a-date", _day(1)]})
    remaining = ESPNFantasyBasketballClient._games_remaining_by_player(schedule, NOW)
    assert remaining == {7: 1}


@pytest.mark.asyncio
async def test_unavailable_players_do_not_project_and_starters_are_flagged(monkeypatch):
    """OUT / FA / IR players contribute no games; OUT and FA starters produce lineup warnings."""
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    settings = _settings([0])  # points only

    my_roster = Roster(
        teamId=1,
        entries=[
            _entry(101),  # healthy starter, PG
            _entry(102, slot=1, injury="OUT"),  # OUT starter, SG
            _entry(103, slot=0, injury="DAY_TO_DAY"),  # questionable starter
            _entry(104, slot=1, pro_team_id=0, pro_team_abbrev="FA"),  # unsigned starter
            _entry(105, slot=12, injury="OUT"),  # OUT on the bench: no warning
            _entry(106, slot=13),  # IR slot
        ],
    )
    their_roster = Roster(teamId=2, entries=[_entry(201), _entry(202, injury="OUT")])
    matchup = CurrentMatchup(
        matchupId=1,
        scoringPeriod=30,
        yourTeam=MatchupTeam(teamId=1, teamName="Me", categoryScores={"points": 100.0}),
        opponentTeam=MatchupTeam(teamId=2, teamName="Them", categoryScores={"points": 100.0}),
        yourRoster=my_roster,
        opponentRoster=their_roster,
    )
    # everyone has two games left
    two = [_day(1), _day(2)]
    my_schedule = _schedule(1, dict.fromkeys((101, 102, 103, 105, 106), two))  # 104 has no team
    their_schedule = _schedule(2, {201: two, 202: two})

    projections = [
        _stats(pid, "projections", points=10.0) for pid in (101, 102, 103, 104, 105, 106, 201, 202)
    ]
    recent = [_stats(pid, "last_7", points=0.0) for pid in (101, 102, 103, 104, 105, 106, 201, 202)]

    async def fake_stats(player_ids, timeframe):
        return projections if timeframe == "projections" else recent

    async def fake_schedule(team_id, start, end, period):
        return my_schedule if team_id == 1 else their_schedule

    with (
        patch.object(client, "get_league_settings", AsyncMock(return_value=settings)),
        patch.object(client, "get_matchup_for_period", AsyncMock(return_value=matchup)),
        patch.object(
            client,
            "get_matchup_period_dates",
            AsyncMock(return_value=(TODAY - timedelta(days=3), TODAY + timedelta(days=3))),
        ),
        patch.object(client, "get_roster_schedule_summary", side_effect=fake_schedule),
        patch.object(client, "get_player_stats", side_effect=fake_stats),
    ):
        analysis = await client.analyze_matchup(team_id=1, matchup_period=CURRENT_PERIOD)

    points = next(c for c in analysis.categoryProjections if c.category == "points")
    # Only 101 (2 games) and 103 (2 games, day-to-day counts fully) project: 100 + 4*10
    assert points.yourProjected == pytest.approx(140.0)
    # Opponent: only 201 projects: 100 + 2*10
    assert points.opponentProjected == pytest.approx(120.0)

    # Raw remaining counts every scheduled game; expected games discount unavailable players
    assert analysis.yourGamesRemaining == 10
    assert analysis.yourExpectedGames == pytest.approx(4.0)
    assert analysis.opponentGamesRemaining == 4
    assert analysis.opponentExpectedGames == pytest.approx(2.0)

    rec_ids = [r.playerId for r in analysis.playerRecommendations]
    assert 101 in rec_ids and 103 in rec_ids
    assert not {102, 104, 105, 106} & set(rec_ids), "OUT, FA, and IR players are never recommended"
    by_id = {r.playerId: r for r in analysis.playerRecommendations}
    assert by_id[103].availability == "DAY_TO_DAY"
    assert by_id[103].expectedGames == pytest.approx(2.0)
    assert by_id[103].priority < by_id[101].priority, "uncertain status lowers priority"
    assert "DAY_TO_DAY" in by_id[103].reasoning

    warnings = "\n".join(analysis.lineupWarnings)
    assert "Player 102 (SG) is OUT with 2 game(s) left" in warnings
    assert "Player 104 (SG) is not on an NBA roster" in warnings
    assert "Player 103 (PG) is DAY_TO_DAY" in warnings
    assert "Player 105" not in warnings, "a benched OUT player is not a lineup problem"
    assert "Player 106" not in warnings, "IR slot is where an injured player belongs"
    assert any("lineup warning" in n for n in analysis.strategyNotes)


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        (_entry(1), ("ACTIVE", 1.0)),
        (_entry(1, injury="ACTIVE"), ("ACTIVE", 1.0)),
        (_entry(1, injury="DAY_TO_DAY"), ("DAY_TO_DAY", 1.0)),
        (_entry(1, injury="DOUBTFUL"), ("DOUBTFUL", 0.5)),
        (_entry(1, injury="OUT"), ("OUT", 0.0)),
        (_entry(1, injury="SUSPENSION"), ("SUSPENDED", 0.0)),
        (_entry(1, slot=13, injury="ACTIVE"), ("IR", 0.0)),
        (_entry(1, pro_team_id=0, pro_team_abbrev="FA", injury="ACTIVE"), ("FA", 0.0)),
    ],
)
def test_availability_classification(entry, expected):
    assert ESPNFantasyBasketballClient._availability(entry) == expected


@pytest.mark.asyncio
async def test_percentage_projection_uses_made_and_attempted(monkeypatch):
    """FG% projects as (current made + proj made*games) / (current att + proj att*games)."""
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    client = ESPNFantasyBasketballClient(league_id=12345, year=2027)
    settings = _settings([19])  # FG% only

    matchup = CurrentMatchup(
        matchupId=1,
        scoringPeriod=30,
        yourTeam=MatchupTeam(
            teamId=1,
            teamName="Me",
            categoryScores={"fieldGoalPercentage": 0.5},
            componentStats={"fieldGoalsMade": 100.0, "fieldGoalsAttempted": 200.0},
        ),
        opponentTeam=MatchupTeam(
            teamId=2,
            teamName="Them",
            categoryScores={"fieldGoalPercentage": 0.45},
            componentStats={"fieldGoalsMade": 90.0, "fieldGoalsAttempted": 200.0},
        ),
        yourRoster=_roster(1, [101]),
        opponentRoster=_roster(2, [201]),
    )
    my_schedule = _schedule(1, {101: [_day(1)]})  # 1 game left
    their_schedule = _schedule(2, {201: [_day(1), _day(2)]})  # 2 games left

    projections = [
        # 10/20 per game keeps my team at exactly 50%
        _stats(
            101,
            "projections",
            points=25.0,
            fieldGoalPercentage=50.0,
            fieldGoalsMade=10.0,
            fieldGoalsAttempted=20.0,
        ),
        # a 20% shooter with volume drags the opponent down: (90+8)/(200+40)
        _stats(
            201,
            "projections",
            points=10.0,
            fieldGoalPercentage=20.0,
            fieldGoalsMade=4.0,
            fieldGoalsAttempted=20.0,
        ),
    ]
    recent = [_stats(pid, "last_7") for pid in (101, 201)]

    async def fake_stats(player_ids, timeframe):
        return projections if timeframe == "projections" else recent

    async def fake_schedule(team_id, start, end, period):
        return my_schedule if team_id == 1 else their_schedule

    with (
        patch.object(client, "get_league_settings", AsyncMock(return_value=settings)),
        patch.object(client, "get_matchup_for_period", AsyncMock(return_value=matchup)),
        patch.object(
            client,
            "get_matchup_period_dates",
            AsyncMock(return_value=(TODAY - timedelta(days=3), TODAY + timedelta(days=3))),
        ),
        patch.object(client, "get_roster_schedule_summary", side_effect=fake_schedule),
        patch.object(client, "get_player_stats", side_effect=fake_stats),
    ):
        analysis = await client.analyze_matchup(team_id=1, matchup_period=CURRENT_PERIOD)

    fg = next(c for c in analysis.categoryProjections if c.category == "fieldGoalPercentage")
    assert fg.yourCurrent == pytest.approx(0.5)
    assert fg.yourProjected == pytest.approx(110 / 220)
    assert fg.opponentProjected == pytest.approx(98 / 240)
    assert fg.projectedResult == "win"
    # The old points-based estimate (points/2 made, made/pct attempted) would have given
    # player 201 5 made on 25 attempts per game: (90+10)/(200+50) = 0.400, not 0.408.
    assert fg.opponentProjected != pytest.approx(100 / 250)

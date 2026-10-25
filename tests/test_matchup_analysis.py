"""Tests for analyze_matchup projection math.

Everything the method fetches is mocked at the client-method boundary, so these tests
exercise the projection and recommendation logic without any network access.
"""

from datetime import date, timedelta
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

TODAY = date.today()
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


def _roster(team_id: int, player_ids: list[int]) -> Roster:
    return Roster(
        teamId=team_id,
        entries=[
            RosterEntry(
                playerId=pid,
                lineupSlotId=0,
                playerPoolEntry=PlayerPoolEntry(
                    id=pid, player=Player(id=pid, fullName=f"Player {pid}", defaultPositionId=1)
                ),
            )
            for pid in player_ids
        ],
    )


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
    # Theirs: 201 has played 1 of 3 (2 left).
    my_schedule = _schedule(1, {101: [_day(-2), _day(-1), _day(1)], 102: [_day(1)]})
    their_schedule = _schedule(2, {201: [_day(-1), _day(1), _day(2)]})

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
            client, "_get_scoring_period_dates", AsyncMock(return_value=(_day(-3), _day(3)))
        ),
        patch.object(client, "get_roster_schedule_summary", side_effect=fake_schedule),
        patch.object(client, "get_player_stats", side_effect=fake_stats),
    ):
        analysis = await client.analyze_matchup(team_id=1, matchup_period=CURRENT_PERIOD)

    points = next(c for c in analysis.categoryProjections if c.category == "points")
    # 100 current + 20*1 (player 101) + 5*1 (player 102); NOT 100 + 20*3 + 5*1 = 165
    assert points.yourProjected == pytest.approx(125.0)
    # 90 current + 10*2; NOT 90 + 10*3 = 120
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


def test_games_remaining_by_player_counts_today_and_later():
    schedule = _schedule(1, {7: [_day(-1), _day(0), _day(2)], 8: [_day(-5)], 9: []})
    remaining = ESPNFantasyBasketballClient._games_remaining_by_player(schedule, TODAY)
    assert remaining == {7: 2, 8: 0, 9: 0}


def test_games_remaining_by_player_skips_unparseable_dates():
    schedule = _schedule(1, {7: ["not-a-date", _day(1)]})
    remaining = ESPNFantasyBasketballClient._games_remaining_by_player(schedule, TODAY)
    assert remaining == {7: 1}

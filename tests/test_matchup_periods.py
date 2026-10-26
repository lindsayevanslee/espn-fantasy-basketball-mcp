"""Tests for mapping ESPN matchup periods to calendar dates."""

from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pytest

from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient
from espn_fantasy_basketball_mcp.models import (
    AcquisitionSettings,
    LeagueSettings,
    LeagueStatus,
    RosterSettings,
    ScheduleSettings,
    ScoringSettings,
    TradeSettings,
)

# Mirrors a real league. ESPN's matchupPeriods is week-indexed: one element per week a period
# covers (verified live: period 1 was [1] while the daily scoring counter read 6). Period 17 is
# a two-week All-Star stretch. Opening night was Tue Oct 20 2026; Oct 25 was scoring period 6.
MATCHUP_PERIODS = (
    {str(k): [k] for k in range(1, 17)}
    | {"17": [17, 18]}
    | {str(k): [k + 1] for k in range(18, 24)}
)
DAILY_PERIODS = {"1": list(range(1, 7)), "2": list(range(7, 14))}
TODAY = date(2026, 10, 25)  # scoring period 6


def _settings(latest: int = 6, first: int = 1, final: int = 170, periods=None) -> LeagueSettings:
    return LeagueSettings(
        leagueId=1,
        leagueName="L",
        seasonId=2027,
        size=12,
        scoringSettings=ScoringSettings(scoringType="H2H_CATEGORY", scoringItems=[]),
        scheduleSettings=ScheduleSettings(
            matchupPeriodCount=20,
            matchupPeriodLength=1,
            matchupPeriods=MATCHUP_PERIODS if periods is None else periods,
            periodTypeId=2,
            playoffTeamCount=4,
            playoffMatchupPeriodLength=1,
        ),
        rosterSettings=RosterSettings(
            lineupSlotCounts={}, positionLimits={}, lineupLocktimeType="X"
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
            currentMatchupPeriod=1,
            latestScoringPeriod=latest,
            firstScoringPeriod=first,
            finalScoringPeriod=final,
            isActive=True,
        ),
    )


@pytest.fixture
def client():
    return ESPNFantasyBasketballClient(league_id=1, year=2027)


def test_scoring_periods_are_consecutive_days():
    f = ESPNFantasyBasketballClient._date_for_scoring_period
    assert f(6, 6, TODAY) == TODAY
    assert f(1, 6, TODAY) == date(2026, 10, 20)
    assert f(13, 6, TODAY) == date(2026, 11, 1)


@pytest.mark.asyncio
async def test_in_season_anchor_is_today(client):
    assert await client._scoring_period_anchor(_settings(), today=TODAY) == (6, TODAY)


@pytest.mark.asyncio
async def test_matchup_period_dates_from_mapping(client):
    s = _settings()
    assert await client.get_matchup_period_dates(1, s, today=TODAY) == (
        date(2026, 10, 20),
        date(2026, 10, 25),
    ), "opening week is six days, Tuesday to Sunday"
    assert await client.get_matchup_period_dates(2, s, today=TODAY) == (
        date(2026, 10, 26),
        date(2026, 11, 1),
    )
    start, end = await client.get_matchup_period_dates(17, s, today=TODAY)
    assert (end - start).days + 1 == 14, "All-Star period spans two weeks"
    assert start == date(2027, 2, 8)


@pytest.mark.asyncio
async def test_offseason_anchor_uses_opening_night(client):
    """When latestScoringPeriod is pinned to the final period, anchor period 1 to opening night."""
    s = _settings(latest=170, final=170)
    with patch.object(
        client, "_get_season_start_date", AsyncMock(return_value=datetime(2026, 10, 20))
    ):
        assert await client.get_matchup_period_dates(2, s, today=date(2027, 7, 1)) == (
            date(2026, 10, 26),
            date(2026, 11, 1),
        )


@pytest.mark.asyncio
async def test_empty_mapping_assumes_one_week_periods(client):
    s = _settings(periods={})
    assert await client.get_matchup_period_dates(1, s, today=TODAY) == (
        date(2026, 10, 20),
        date(2026, 10, 25),
    )
    assert await client.get_matchup_period_dates(3, s, today=TODAY) == (
        date(2026, 11, 2),
        date(2026, 11, 8),
    )


@pytest.mark.asyncio
async def test_period_beyond_schedule_returns_none(client):
    assert await client.get_matchup_period_dates(99, _settings(), today=TODAY) is None
    assert await client.get_matchup_period_dates(0, _settings(), today=TODAY) is None


@pytest.mark.asyncio
async def test_daily_style_mapping_is_also_understood(client):
    s = _settings(periods=DAILY_PERIODS)
    assert await client.get_matchup_period_dates(1, s, today=TODAY) == (
        date(2026, 10, 20),
        date(2026, 10, 25),
    )
    assert await client.get_matchup_period_dates(2, s, today=TODAY) == (
        date(2026, 10, 26),
        date(2026, 11, 1),
    )


def test_window_when_season_opens_on_a_monday():
    """A Monday opener gives a full seven-day first period."""
    w = ESPNFantasyBasketballClient._matchup_period_window
    assert w(1, date(2026, 10, 19), {"1": [1], "2": [2]}) == (
        date(2026, 10, 19),
        date(2026, 10, 25),
    )
    assert w(2, date(2026, 10, 19), {"1": [1], "2": [2]}) == (date(2026, 10, 26), date(2026, 11, 1))


@pytest.mark.asyncio
async def test_settings_fetch_failure_returns_none(client):
    with patch.object(client, "get_league_settings", AsyncMock(side_effect=RuntimeError("down"))):
        assert await client.get_matchup_period_dates(1, None, today=TODAY) is None


@pytest.mark.asyncio
async def test_player_schedule_counts_games_by_matchup_window(client, monkeypatch):
    """A Monday game before a Tuesday opener is neither 'this week' nor 'next week'."""
    monkeypatch.setenv("MY_TIMEZONE", "UTC")

    def game(day: str):
        return {
            "id": day,
            "date": f"{day}T20:00Z",
            "competitions": [
                {
                    "competitors": [
                        {"homeAway": "home", "team": {"id": "7", "abbreviation": "DEN"}},
                        {"homeAway": "away", "team": {"id": "13", "abbreviation": "LAL"}},
                    ]
                }
            ],
        }

    payload = {
        "team": {"id": "7", "abbreviation": "DEN"},
        "events": [game("2026-10-19"), game("2026-10-21"), game("2026-10-25"), game("2026-10-27")],
    }
    with patch.object(client, "_make_request", AsyncMock(return_value=payload)):
        sched = await client.get_player_schedule(
            101,
            7,
            "2026-10-19",
            "2026-11-01",
            this_window=(date(2026, 10, 20), date(2026, 10, 25)),
            next_window=(date(2026, 10, 26), date(2026, 11, 1)),
        )
    assert [g.date for g in sched.games] == ["2026-10-19", "2026-10-21", "2026-10-25", "2026-10-27"]
    assert sched.gamesThisWeek == 2
    assert sched.gamesNextWeek == 1
    assert sched.games[1].datetimeISO == "2026-10-21T20:00:00+00:00"


@pytest.mark.asyncio
async def test_roster_summary_uses_matchup_windows(client):
    """The summary derives both windows from the mapping and passes them to every player."""
    captured = {}

    async def fake_player_schedule(pid, team, start, end, this_window=None, next_window=None):
        captured.update(start=start, end=end, this_window=this_window, next_window=next_window)
        from espn_fantasy_basketball_mcp.models import PlayerSchedule

        return PlayerSchedule(
            playerId=pid,
            playerName="P",
            teamAbbreviation="DEN",
            games=[],
            gamesThisWeek=3,
            gamesNextWeek=4,
        )

    from espn_fantasy_basketball_mcp.models import Player, PlayerPoolEntry, Roster, RosterEntry

    roster = Roster(
        teamId=8,
        entries=[
            RosterEntry(
                playerId=1,
                lineupSlotId=0,
                playerPoolEntry=PlayerPoolEntry(
                    id=1, player=Player(id=1, fullName="P", defaultPositionId=1, proTeamId=7)
                ),
            )
        ],
    )
    with (
        patch.object(client, "get_league_settings", AsyncMock(return_value=_settings())),
        patch.object(client, "get_team_roster", AsyncMock(return_value=roster)),
        patch.object(client, "get_player_schedule", side_effect=fake_player_schedule),
        patch.object(client, "_scoring_period_anchor", AsyncMock(return_value=(6, TODAY))),
    ):
        summary = await client.get_roster_schedule_summary(8, matchup_period=1)

    assert captured["this_window"] == (date(2026, 10, 20), date(2026, 10, 25))
    assert captured["next_window"] == (date(2026, 10, 26), date(2026, 11, 1))
    assert (captured["start"], captured["end"]) == ("2026-10-20", "2026-11-01")
    assert summary.totalGamesThisWeek == 3 and summary.totalGamesNextWeek == 4
    assert summary.scoringPeriod == 1

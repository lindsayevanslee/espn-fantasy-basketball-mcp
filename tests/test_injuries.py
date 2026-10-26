"""Tests for the ESPN injury report tool."""

from unittest.mock import AsyncMock, patch

import pytest

from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient
from espn_fantasy_basketball_mcp.models import Player, PlayerPoolEntry, Roster, RosterEntry

FEED = {
    "injuries": [
        {
            "id": "28",
            "displayName": "Toronto Raptors",
            "abbreviation": "TOR",
            "injuries": [
                {
                    "id": "1",
                    "status": "Out",
                    "shortComment": "Leonard (knee) will not play Sunday.",
                    "longComment": "Leonard is expected to miss two weeks with a knee sprain.",
                    "date": "2026-10-24T18:00Z",
                    "athlete": {
                        "id": "6450",
                        "displayName": "Kawhi Leonard",
                        "position": {"abbreviation": "SF"},
                    },
                    "details": {
                        "type": "Knee",
                        "location": "Knee",
                        "detail": "Sprain",
                        "side": "Left",
                        "returnDate": "2026-11-08",
                        "fantasyStatus": {"description": "Out", "abbreviation": "O"},
                    },
                }
            ],
        },
        {
            "id": "9",
            "displayName": "Golden State Warriors",
            "abbreviation": "GS",
            "injuries": [
                {
                    "status": "Day-To-Day",
                    "shortComment": "Curry (ankle) is questionable.",
                    "athlete": {"id": "3975", "displayName": "Stephen Curry"},
                    "details": {"type": "Ankle", "fantasyStatus": {"abbreviation": "GTD"}},
                },
                {"status": "Out", "athlete": {"displayName": "Mystery Man"}},  # no id, no details
            ],
        },
    ]
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MY_TIMEZONE", "America/Chicago")
    return ESPNFantasyBasketballClient(league_id=12345, year=2027)


def _roster_entry(pid: int, name: str, slot: int, slot_name: str) -> RosterEntry:
    return RosterEntry(
        playerId=pid,
        lineupSlotId=slot,
        lineupSlotName=slot_name,
        playerPoolEntry=PlayerPoolEntry(
            id=pid, player=Player(id=pid, fullName=name, defaultPositionId=3, proTeamId=28)
        ),
    )


class TestParse:
    def test_flattens_feed_and_normalizes(self, client):
        entries = client._parse_injury_report(FEED)
        assert [e.playerName for e in entries] == ["Kawhi Leonard", "Stephen Curry", "Mystery Man"]
        kawhi = entries[0]
        assert kawhi.playerId == 6450 and kawhi.nbaTeam == "TOR" and kawhi.position == "SF"
        assert kawhi.status == "Out" and kawhi.fantasyStatus == "O"
        assert kawhi.injury == "Left Knee Sprain"
        assert kawhi.returnDate == "2026-11-08"
        assert kawhi.reportedAt == "2026-10-24T13:00:00-05:00"
        assert "two weeks" in kawhi.longComment
        curry = entries[1]
        assert curry.nbaTeam == "GSW", "site-API codes are canonicalized"
        assert curry.fantasyStatus == "GTD" and curry.returnDate is None
        assert entries[2].playerId is None and entries[2].onRoster is None

    def test_tolerates_garbage(self, client):
        assert client._parse_injury_report(None) == []
        assert client._parse_injury_report({"injuries": [None, {"injuries": [None]}]}) == []
        assert client._parse_injury_report([]) == []


class TestRosterJoin:
    @pytest.mark.asyncio
    async def test_league_wide_when_no_team(self, client):
        with patch.object(client, "_make_request", AsyncMock(return_value=FEED)):
            entries = await client.get_injury_report()
        assert len(entries) == 3 and all(e.onRoster is None for e in entries)

    @pytest.mark.asyncio
    async def test_roster_join_by_id_and_by_name(self, client):
        roster = Roster(
            teamId=8,
            entries=[
                _roster_entry(6450, "Kawhi Leonard", 2, "SF"),  # joins by athlete id
                _roster_entry(99, "Mystery Man", 12, "BENCH"),  # feed had no id: joins by name
                _roster_entry(1, "Nikola Jokic", 4, "C"),  # healthy: not in the report
            ],
        )
        with (
            patch.object(client, "_make_request", AsyncMock(return_value=FEED)),
            patch.object(client, "get_team_roster", AsyncMock(return_value=roster)),
        ):
            entries = await client.get_injury_report(team_id=8)
        assert [(e.playerName, e.playerId, e.lineupSlot) for e in entries] == [
            ("Kawhi Leonard", 6450, "SF"),
            ("Mystery Man", 99, "BENCH"),
        ]
        assert all(e.onRoster for e in entries)

    def test_injury_feed_is_cached_for_minutes(self):
        ttl = ESPNFantasyBasketballClient._cache_ttl(
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries", {}
        )
        assert ttl == ESPNFantasyBasketballClient.TTL_INJURIES

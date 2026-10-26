"""Tests for the process-wide ESPN response cache and request de-duplication."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import espn_fantasy_basketball_mcp.client as client_module
from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient
from espn_fantasy_basketball_mcp.models import Player, PlayerPoolEntry, Roster, RosterEntry

LEAGUE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/2027/segments/0/leagues/1"
NBA = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.delenv("ESPN_MCP_DISABLE_CACHE", raising=False)
    ESPNFantasyBasketballClient.clear_cache()
    yield
    ESPNFantasyBasketballClient.clear_cache()


@pytest.fixture
def client():
    return ESPNFantasyBasketballClient(league_id=1, year=2027, espn_s2="s2", swid="{A}")


class TestTTL:
    @pytest.mark.parametrize(
        ("url", "params", "expected"),
        [
            (LEAGUE, {"view": "mSettings"}, ESPNFantasyBasketballClient.TTL_SETTINGS),
            (LEAGUE, {"view": "mTeam"}, ESPNFantasyBasketballClient.TTL_TEAMS),
            (LEAGUE, {"view": ["mRoster", "mTeam"]}, ESPNFantasyBasketballClient.TTL_LIVE),
            (LEAGUE, {"view": "mMatchup"}, ESPNFantasyBasketballClient.TTL_LIVE),
            (LEAGUE, {"view": "kona_player_info"}, ESPNFantasyBasketballClient.TTL_LIVE),
            (f"{NBA}/scoreboard", {}, ESPNFantasyBasketballClient.TTL_SCOREBOARD),
            (
                f"{NBA}/teams/13/schedule",
                {"season": 2027},
                ESPNFantasyBasketballClient.TTL_NBA_TEAM_SCHEDULE,
            ),
        ],
    )
    def test_ttl_by_endpoint(self, url, params, expected):
        assert ESPNFantasyBasketballClient._cache_ttl(url, params) == expected

    def test_slow_changing_data_outlives_live_data(self):
        c = ESPNFantasyBasketballClient
        assert (
            c.TTL_NBA_TEAM_SCHEDULE
            > c.TTL_SETTINGS
            > c.TTL_TEAMS
            > c.TTL_SCOREBOARD
            > c.TTL_LIVE
            > 0
        )


class TestMakeRequestCaching:
    @pytest.mark.asyncio
    async def test_identical_requests_fetch_once(self, client):
        with patch.object(client, "_fetch", new_callable=AsyncMock) as fetch:
            fetch.return_value = {"settings": {}}
            a = await client._make_request(LEAGUE, {"view": "mSettings"})
            b = await client._make_request(LEAGUE, {"view": "mSettings"})
        assert a == b == {"settings": {}}
        assert fetch.await_count == 1
        assert ESPNFantasyBasketballClient.cache_stats() == {"hits": 1, "misses": 1, "entries": 1}

    @pytest.mark.asyncio
    async def test_filter_header_is_part_of_the_key(self, client):
        with patch.object(client, "_fetch", new_callable=AsyncMock) as fetch:
            fetch.return_value = {"players": []}
            await client._make_request(
                LEAGUE, {"view": "kona_player_info"}, {"x-fantasy-filter": '{"a":1}'}
            )
            await client._make_request(
                LEAGUE, {"view": "kona_player_info"}, {"x-fantasy-filter": '{"a":2}'}
            )
            await client._make_request(
                LEAGUE, {"view": "kona_player_info"}, {"X-Fantasy-Filter": '{"a":1}'}
            )
        assert fetch.await_count == 2, (
            "different filters fetch separately; header case does not matter"
        )

    @pytest.mark.asyncio
    async def test_different_accounts_do_not_share_entries(self, client):
        other = ESPNFantasyBasketballClient(league_id=1, year=2027, espn_s2="s2", swid="{B}")
        with (
            patch.object(client, "_fetch", new_callable=AsyncMock) as f1,
            patch.object(other, "_fetch", new_callable=AsyncMock) as f2,
        ):
            f1.return_value = f2.return_value = {}
            await client._make_request(LEAGUE, {"view": "mTeam"})
            await other._make_request(LEAGUE, {"view": "mTeam"})
        assert f1.await_count == 1 and f2.await_count == 1

    @pytest.mark.asyncio
    async def test_entries_expire(self, client, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(client_module.time, "monotonic", lambda: clock[0])
        with patch.object(client, "_fetch", new_callable=AsyncMock) as fetch:
            fetch.return_value = {"events": []}
            await client._make_request(f"{NBA}/scoreboard", {})
            clock[0] += ESPNFantasyBasketballClient.TTL_SCOREBOARD - 1
            await client._make_request(f"{NBA}/scoreboard", {})
            assert fetch.await_count == 1
            clock[0] += 2
            await client._make_request(f"{NBA}/scoreboard", {})
        assert fetch.await_count == 2

    @pytest.mark.asyncio
    async def test_concurrent_identical_requests_share_one_fetch(self, client):
        async def slow_fetch(url, params=None, headers=None):
            await asyncio.sleep(0.01)
            return {"ok": True}

        with patch.object(client, "_fetch", side_effect=slow_fetch) as fetch:
            results = await asyncio.gather(
                *(client._make_request(LEAGUE, {"view": "mSettings"}) for _ in range(5))
            )
        assert all(r == {"ok": True} for r in results)
        assert fetch.await_count == 1

    @pytest.mark.asyncio
    async def test_errors_are_not_cached(self, client):
        with patch.object(client, "_fetch", new_callable=AsyncMock) as fetch:
            fetch.side_effect = [RuntimeError("boom"), {"teams": []}]
            with pytest.raises(RuntimeError):
                await client._make_request(LEAGUE, {"view": "mTeam"})
            assert await client._make_request(LEAGUE, {"view": "mTeam"}) == {"teams": []}
        assert fetch.await_count == 2
        assert ESPNFantasyBasketballClient._inflight == {}

    @pytest.mark.asyncio
    async def test_cache_can_be_disabled(self, client, monkeypatch):
        monkeypatch.setenv("ESPN_MCP_DISABLE_CACHE", "1")
        with patch.object(client, "_fetch", new_callable=AsyncMock) as fetch:
            fetch.return_value = {}
            await client._make_request(LEAGUE, {"view": "mSettings"})
            await client._make_request(LEAGUE, {"view": "mSettings"})
        assert fetch.await_count == 2
        assert ESPNFantasyBasketballClient.cache_stats()["entries"] == 0

    @pytest.mark.asyncio
    async def test_https_is_still_enforced(self, client):
        with pytest.raises(ValueError, match="Only HTTPS"):
            await client._make_request("http://example.com")

    @pytest.mark.asyncio
    async def test_cache_is_bounded(self, client):
        ESPNFantasyBasketballClient._CACHE_MAX_ENTRIES = 3
        try:
            with patch.object(client, "_fetch", new_callable=AsyncMock) as fetch:
                fetch.return_value = {}
                for i in range(10):
                    await client._make_request(
                        LEAGUE, {"view": "mMatchup", "scoringPeriodId": str(i)}
                    )
            assert ESPNFantasyBasketballClient.cache_stats()["entries"] <= 3
        finally:
            ESPNFantasyBasketballClient._CACHE_MAX_ENTRIES = 512


class TestRosterScheduleFanOut:
    @pytest.mark.asyncio
    async def test_teammates_share_one_schedule_request(self, client):
        """Three players on two NBA teams -> two team-schedule fetches, fetched concurrently."""

        def entry(pid: int, pro_team_id: int) -> RosterEntry:
            return RosterEntry(
                playerId=pid,
                lineupSlotId=0,
                playerPoolEntry=PlayerPoolEntry(
                    id=pid,
                    player=Player(
                        id=pid, fullName=f"P{pid}", defaultPositionId=1, proTeamId=pro_team_id
                    ),
                ),
            )

        roster = Roster(teamId=8, entries=[entry(1, 7), entry(2, 7), entry(3, 13), entry(4, 0)])

        def schedule_payload(team_id: str, abbr: str, opp_id: str, opp_abbr: str):
            return {
                "team": {"id": team_id, "abbreviation": abbr},
                "events": [
                    {
                        "id": f"g{team_id}",
                        "date": "2026-10-28T00:00Z",
                        "competitions": [
                            {
                                "competitors": [
                                    {
                                        "homeAway": "home",
                                        "team": {"id": team_id, "abbreviation": abbr},
                                    },
                                    {
                                        "homeAway": "away",
                                        "team": {"id": opp_id, "abbreviation": opp_abbr},
                                    },
                                ]
                            }
                        ],
                    }
                ],
            }

        fetched: list[str] = []

        async def fake_fetch(url, params=None, headers=None):
            fetched.append(url)
            await asyncio.sleep(0.01)
            if url.endswith("/teams/7/schedule"):
                return schedule_payload("7", "DEN", "13", "LAL")
            if url.endswith("/teams/13/schedule"):
                return schedule_payload("13", "LAL", "7", "DEN")
            raise AssertionError(f"unexpected fetch {url}")

        with (
            patch.object(client, "get_team_roster", AsyncMock(return_value=roster)),
            patch.object(client, "get_league_settings", AsyncMock(return_value=None)),
            patch.object(client, "_fetch", side_effect=fake_fetch),
        ):
            summary = await client.get_roster_schedule_summary(8, "2026-10-26", "2026-11-02")

        assert sorted(fetched) == [f"{NBA}/teams/13/schedule", f"{NBA}/teams/7/schedule"]
        assert [ps.playerId for ps in summary.playerSchedules] == [1, 2, 3, 4]
        assert summary.playerSchedules[0].playerName == "P1"
        unsigned = summary.playerSchedules[3]
        assert (unsigned.teamAbbreviation, unsigned.gamesThisWeek) == ("FA", 0)
        assert unsigned.note and "NBA roster" in unsigned.note
        assert summary.totalGamesThisWeek == 3
        assert summary.averageGamesPerPlayer == 1.0, "average excludes players who cannot play"

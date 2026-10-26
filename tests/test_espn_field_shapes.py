"""Regression tests for ESPN field names that were read from the wrong place.

Three live-usage reports traced to the same class of bug:
- get_nba_schedule sent `date=`; ESPN's site API reads `dates=` and silently returned today.
- Ownership % is nested under the player object in kona_player_info, not at the entry level.
- Per-game averages live under `averageStats`, not `averages`, so season totals were returned.
"""

from unittest.mock import AsyncMock, patch

import pytest

from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MY_TIMEZONE", "UTC")
    return ESPNFantasyBasketballClient(league_id=1, year=2027)


class TestScheduleDateParameter:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("given", ["2026-10-28", "20261028"])
    async def test_sends_dates_parameter(self, client, given):
        mock = AsyncMock(return_value={"events": []})
        with patch.object(client, "_make_request", mock):
            await client.get_nba_schedule(given)
        _url, params = mock.call_args.args[:2]
        assert params == {"dates": "20261028"}, "ESPN ignores `date`; only `dates` selects a day"

    @pytest.mark.asyncio
    async def test_no_date_sends_no_parameter(self, client):
        mock = AsyncMock(return_value={"events": []})
        with patch.object(client, "_make_request", mock):
            await client.get_nba_schedule()
        assert mock.call_args.args[1] == {}

    @pytest.mark.asyncio
    async def test_rejects_bad_date(self, client):
        with pytest.raises(ValueError, match="Invalid date format"):
            await client.get_nba_schedule("10/28/2026")


def _fa_entry(pid, name, owned, change, totals, averages=None):
    stat_set = {"id": "002027", "stats": totals}
    if averages is not None:
        stat_set["averageStats"] = averages
    return {
        "id": pid,
        "onTeamId": 0,
        "player": {
            "id": pid,
            "fullName": name,
            "defaultPositionId": 1,
            "proTeamId": 5,
            "ownership": {"percentOwned": owned, "percentChange": change},
            "stats": [stat_set],
        },
    }


class TestOwnershipAndAverages:
    @pytest.mark.asyncio
    async def test_free_agents_read_nested_ownership_and_average_stats(self, client):
        data = {
            "players": [
                _fa_entry(
                    1,
                    "Per Game",
                    43.7,
                    2.5,
                    totals={"0": 60.0, "6": 30.0, "3": 12.0, "42": 3},
                    averages={"0": 20.0, "6": 10.0, "3": 4.0, "19": 0.5},
                ),
                _fa_entry(2, "Totals Only", 12.0, -0.5, totals={"0": 45.0, "6": 9.0, "42": 3}),
            ]
        }
        with (
            patch.object(client, "_make_request", AsyncMock(return_value=data)),
            patch.object(client, "_get_pro_team_id_to_abbrev", return_value={5: "CLE"}),
        ):
            players = await client.get_free_agents(size=5, verbose=True)

        per_game, totals_only = players
        assert per_game.ownership.percentOwned == 43.7
        assert per_game.ownership.percentChange == 2.5
        assert per_game.stats["points"] == 20.0 and per_game.stats["rebounds"] == 10.0
        assert per_game.stats["fg_pct"] == 50.0
        assert per_game.stats["games_played"] == 3
        assert per_game.stats["basis"] == "per_game"

        assert totals_only.ownership.percentOwned == 12.0
        assert totals_only.stats["points"] == 45.0, "falls back to totals when ESPN sends none"
        assert totals_only.stats["basis"] == "season_total"

    @pytest.mark.asyncio
    async def test_trending_reads_nested_ownership(self, client):
        data = {
            "players": [
                {
                    "id": 7,
                    "player": {
                        "id": 7,
                        "fullName": "Hot Pickup",
                        "defaultPositionId": 2,
                        "proTeamId": 5,
                        "ownership": {"percentOwned": 30.0, "percentChange": 9.5},
                    },
                }
            ]
        }
        with (
            patch.object(client, "_make_request", AsyncMock(return_value=data)),
            patch.object(client, "_get_pro_team_id_to_abbrev", return_value={5: "CLE"}),
        ):
            trending = await client.get_trending_players(direction="up", limit=5)
        assert [t.player.fullName for t in trending] == ["Hot Pickup"]
        assert trending[0].add_percentage == 9.5

    @pytest.mark.asyncio
    async def test_search_league_status_reads_nested_ownership(self, client):
        from espn_fantasy_basketball_mcp.models import PlayerSearchResult

        results = [PlayerSearchResult(playerId=7, fullName="Hot Pickup", matchScore=1.0)]
        data = {
            "players": [
                {"id": 7, "onTeamId": 0, "player": {"id": 7, "ownership": {"percentOwned": 30.0}}}
            ]
        }
        with (
            patch.object(client, "_make_request", AsyncMock(return_value=data)),
            patch.object(client, "get_league_teams", AsyncMock(return_value=[])),
        ):
            await client._attach_league_status(results)
        assert results[0].percentOwned == 30.0 and results[0].isFreeAgent is True

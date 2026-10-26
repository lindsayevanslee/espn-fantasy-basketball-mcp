"""Tests for player search by name."""

from unittest.mock import AsyncMock, patch

import pytest

from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient
from espn_fantasy_basketball_mcp.models import Team

PRO_PLAYERS = [
    {
        "id": 1,
        "fullName": "Nikola Jokic",
        "defaultPositionId": 5,
        "proTeamId": 7,
        "injuryStatus": "ACTIVE",
    },
    {"id": 2, "fullName": "Luka Doncic", "defaultPositionId": 1, "proTeamId": 13},
    {"id": 3, "fullName": "Stephen Curry", "defaultPositionId": 1, "proTeamId": 9},
    {"id": 4, "fullName": "Seth Curry", "defaultPositionId": 2, "proTeamId": 30},
    {"id": 5, "fullName": "Michael Porter Jr.", "defaultPositionId": 3, "proTeamId": 17},
    {"id": 6, "fullName": "Kevin Porter Jr.", "defaultPositionId": 2, "proTeamId": 0},
    {"id": 7, "fullName": "Jalen Williams", "defaultPositionId": 3, "proTeamId": 25},
    {"id": 8, "fullName": "Jaylen Williams", "defaultPositionId": 4, "proTeamId": 25},
]


@pytest.fixture
def client():
    return ESPNFantasyBasketballClient(league_id=12345, year=2027)


class TestNameMatching:
    score = ESPNFantasyBasketballClient._name_match_score

    def test_exact_and_case_insensitive(self):
        assert self.score("nikola jokic", "Nikola Jokic") == 1.0

    def test_surname_only(self):
        assert self.score("Jokic", "Nikola Jokic") == 0.95

    def test_accents_are_ignored(self):
        assert self.score("Dončić", "Luka Doncic") == 0.95
        assert self.score("Nikola Jokić", "Nikola Jokic") == 1.0

    def test_token_prefixes_in_order(self):
        assert self.score("steph curry", "Stephen Curry") == 0.9
        assert self.score("mpj", "Michael Porter Jr.") < 0.5, "initials are not prefixes of tokens"

    def test_substring(self):
        assert self.score("porter jr", "Michael Porter Jr.") >= 0.85

    def test_typo_still_scores_but_below_structural_matches(self):
        s = self.score("Nikola Jokich", "Nikola Jokic")
        assert 0.5 <= s <= 0.8

    def test_unrelated_is_low(self):
        assert self.score("LeBron James", "Nikola Jokic") < 0.5


class TestSearchPlayers:
    @pytest.mark.asyncio
    async def test_ranks_best_match_first_and_resolves_fields(self, client):
        with patch.object(client, "get_pro_players", AsyncMock(return_value=PRO_PLAYERS)):
            results = await client.search_players("curry", limit=5, include_league_status=False)
        names = [r.fullName for r in results]
        assert names == ["Seth Curry", "Stephen Curry"], "equal scores sort by name"
        assert all(r.matchScore == 0.95 for r in results)
        steph = next(r for r in results if r.fullName == "Stephen Curry")
        assert steph.playerId == 3
        assert steph.defaultPosition == "PG"
        assert steph.proTeamAbbrev == "GSW"

    @pytest.mark.asyncio
    async def test_unsigned_player_shows_fa(self, client):
        with patch.object(client, "get_pro_players", AsyncMock(return_value=PRO_PLAYERS)):
            results = await client.search_players("kevin porter", include_league_status=False)
        assert results[0].fullName == "Kevin Porter Jr."
        assert results[0].proTeamAbbrev == "FA"

    @pytest.mark.asyncio
    async def test_limit_and_threshold(self, client):
        with patch.object(client, "get_pro_players", AsyncMock(return_value=PRO_PLAYERS)):
            assert (
                len(await client.search_players("williams", limit=1, include_league_status=False))
                == 1
            )
            assert await client.search_players("zzzzzz", include_league_status=False) == []

    @pytest.mark.asyncio
    async def test_invalid_arguments(self, client):
        with pytest.raises(ValueError, match="query"):
            await client.search_players("   ")
        with pytest.raises(ValueError, match="limit"):
            await client.search_players("jokic", limit=0)

    @pytest.mark.asyncio
    async def test_league_status_is_attached(self, client):
        kona = {
            "players": [
                {
                    "id": 1,
                    "onTeamId": 8,
                    "ownership": {"percentOwned": 99.9},
                    "player": {"id": 1, "injuryStatus": "DAY_TO_DAY"},
                },
                {"id": 2, "onTeamId": 0, "ownership": {"percentOwned": 97.0}, "player": {"id": 2}},
            ]
        }
        teams = [Team(id=8, abbrev="SA", name="Statistical Anomalies")]
        with (
            patch.object(client, "get_pro_players", AsyncMock(return_value=PRO_PLAYERS)),
            patch.object(client, "_make_request", AsyncMock(return_value=kona)) as req,
            patch.object(client, "get_league_teams", AsyncMock(return_value=teams)),
        ):
            results = await client.search_players("jokic", limit=1)
            # a second search for a free agent
            results2 = await client.search_players("doncic", limit=1)

        jokic = results[0]
        assert jokic.isFreeAgent is False
        assert jokic.fantasyTeamId == 8 and jokic.fantasyTeamName == "Statistical Anomalies"
        assert jokic.percentOwned == 99.9
        assert jokic.injuryStatus == "DAY_TO_DAY", (
            "league view's status is fresher than the player list"
        )
        doncic = results2[0]
        assert doncic.isFreeAgent is True and doncic.fantasyTeamId is None

        # the league lookup sends the matched ids as a filterIds header
        _, kwargs_or_args = req.await_args_list[0][0][0], req.await_args_list[0][0]
        assert '"filterIds"' in kwargs_or_args[2]["x-fantasy-filter"]

    @pytest.mark.asyncio
    async def test_league_status_failure_is_non_fatal(self, client):
        with (
            patch.object(client, "get_pro_players", AsyncMock(return_value=PRO_PLAYERS)),
            patch.object(client, "_make_request", AsyncMock(side_effect=RuntimeError("espn down"))),
            patch.object(client, "get_league_teams", AsyncMock(return_value=[])),
        ):
            results = await client.search_players("jokic", limit=1)
        assert results[0].fullName == "Nikola Jokic"
        assert results[0].isFreeAgent is None


class TestGetProPlayers:
    @pytest.mark.asyncio
    async def test_uses_players_endpoint_with_active_filter(self, client):
        with patch.object(client, "_make_request", AsyncMock(return_value=PRO_PLAYERS)) as req:
            players = await client.get_pro_players()
        assert len(players) == len(PRO_PLAYERS)
        url, params, headers = req.await_args[0]
        assert url.endswith("/seasons/2027/players")
        assert params == {"view": "players_wl"}
        assert '"filterActive"' in headers["x-fantasy-filter"]

    @pytest.mark.asyncio
    async def test_tolerates_wrapped_response(self, client):
        with patch.object(
            client, "_make_request", AsyncMock(return_value={"players": PRO_PLAYERS[:2]})
        ):
            assert len(await client.get_pro_players()) == 2

    def test_players_list_is_cached_for_hours(self):
        ttl = ESPNFantasyBasketballClient._cache_ttl(
            "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/2027/players",
            {"view": "players_wl"},
        )
        assert ttl == ESPNFantasyBasketballClient.TTL_PRO_PLAYERS

"""Test cases for ESPN Fantasy Basketball draft functionality."""

from unittest.mock import AsyncMock, patch

import pytest

from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient
from espn_fantasy_basketball_mcp.models import (
    DraftPick,
    DraftRecommendation,
    DraftStatus,
    PlayerDraftInfo,
    TeamDraftSummary,
)


class TestDraftModels:
    """Test cases for draft-related data models."""

    def test_draft_pick_creation(self):
        """Test creating a draft pick."""
        pick = DraftPick(
            id=1,
            playerId=12345,
            teamId=1,
            bidAmount=50,
            overallPickNumber=1,
            roundId=1,
            roundPickNumber=1,
            nominatingTeamId=2,
            keeper=False,
        )
        assert pick.id == 1
        assert pick.playerId == 12345
        assert pick.bidAmount == 50
        assert pick.keeper is False

    def test_draft_status_creation(self):
        """Test creating draft status."""
        pick = DraftPick(
            id=1,
            playerId=12345,
            teamId=1,
            bidAmount=50,
            overallPickNumber=1,
            roundId=1,
            roundPickNumber=1,
        )

        status = DraftStatus(
            inProgress=True,
            drafted=False,
            picks=[pick],
            currentPickNumber=2,
            currentNominatingTeam=2,
        )
        assert status.inProgress is True
        assert status.drafted is False
        assert len(status.picks) == 1
        assert status.currentPickNumber == 2

    def test_team_draft_summary_creation(self):
        """Test creating team draft summary."""
        summary = TeamDraftSummary(
            teamId=1,
            teamName="Test Team",
            totalSpent=150,
            playersCount=8,
            remainingBudget=50,
            positionCounts={"PG": 2, "SG": 1},
            categories={"points": 100.5, "rebounds": 75.2},
        )
        assert summary.teamId == 1
        assert summary.totalSpent == 150
        assert summary.remainingBudget == 50
        assert summary.positionCounts["PG"] == 2

    def test_draft_recommendation_creation(self):
        """Test creating draft recommendation."""
        recommendation = DraftRecommendation(
            action="bid",
            playerId=12345,
            playerName="Test Player",
            suggestedBid=25,
            maxBid=30,
            reasoning="Good value at this price",
            priority=8,
            category_impact={"points": "positive", "rebounds": "neutral"},
        )
        assert recommendation.action == "bid"
        assert recommendation.suggestedBid == 25
        assert recommendation.priority == 8
        assert recommendation.category_impact["points"] == "positive"


class TestDraftClient:
    """Test cases for draft-related client methods."""

    @pytest.fixture
    def client(self):
        """Create a test client instance."""
        return ESPNFantasyBasketballClient(
            league_id=12345, year=2025, espn_s2="test_s2", swid="test_swid"
        )

    @pytest.mark.asyncio
    async def test_get_draft_status_success(self, client):
        """Test successful draft status retrieval."""
        mock_response = {
            "draftDetail": {
                "inProgress": True,
                "drafted": False,
                "completeDate": None,
                "picks": [
                    {
                        "id": 1,
                        "playerId": 12345,
                        "teamId": 1,
                        "bidAmount": 50,
                        "overallPickNumber": 1,
                        "roundId": 1,
                        "roundPickNumber": 1,
                        "nominatingTeamId": 2,
                        "keeper": False,
                    }
                ],
            }
        }

        with patch.object(client, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            draft_status = await client.get_draft_status()

            assert draft_status.inProgress is True
            assert draft_status.drafted is False
            assert len(draft_status.picks) == 1
            assert draft_status.picks[0].playerId == 12345
            assert draft_status.picks[0].bidAmount == 50
            assert draft_status.currentPickNumber == 2  # Next pick

    @pytest.mark.asyncio
    async def test_get_available_players_success(self, client):
        """Test successful available players retrieval."""
        mock_draft_response = {
            "draftDetail": {
                "inProgress": True,
                "drafted": False,
                "picks": [
                    {
                        "id": 1,
                        "playerId": 99999,  # This player is drafted
                        "teamId": 1,
                        "bidAmount": 50,
                        "overallPickNumber": 1,
                        "roundId": 1,
                        "roundPickNumber": 1,
                    }
                ],
            }
        }

        mock_players_response = {
            "players": [
                {
                    "draftAuctionValue": 0,
                    "player": {
                        "id": 12345,
                        "fullName": "Available Player",
                        "firstName": "Available",
                        "lastName": "Player",
                        "defaultPositionId": 1,
                        "active": True,
                        "draftRanksByRankType": {"STANDARD": {"auctionValue": 25, "rank": 50}},
                    },
                },
                {
                    "draftAuctionValue": 50,
                    "player": {
                        "id": 99999,  # This player should be filtered out (drafted)
                        "fullName": "Drafted Player",
                        "defaultPositionId": 1,
                        "active": True,
                        "draftRanksByRankType": {"STANDARD": {"auctionValue": 50, "rank": 10}},
                    },
                },
            ]
        }

        with patch.object(client, "_make_request", new_callable=AsyncMock) as mock_request:
            # Mock both API calls - first for draft status, then for players
            mock_request.side_effect = [mock_players_response, mock_draft_response]

            players = await client.get_available_players(10)

            assert len(players) == 1  # Only undrafted player
            assert players[0].playerId == 12345
            assert players[0].player.fullName == "Available Player"
            assert players[0].auctionValue == 25
            assert players[0].rank == 50
            assert players[0].isDrafted is False

    @pytest.mark.asyncio
    async def test_get_team_draft_summary_success(self, client):
        """Test successful team draft summary retrieval."""
        mock_draft_response = {
            "draftDetail": {
                "inProgress": True,
                "drafted": False,
                "picks": [
                    {
                        "id": 1,
                        "playerId": 12345,
                        "teamId": 1,
                        "bidAmount": 50,
                        "overallPickNumber": 1,
                        "roundId": 1,
                        "roundPickNumber": 1,
                    },
                    {
                        "id": 2,
                        "playerId": 54321,
                        "teamId": 1,
                        "bidAmount": 30,
                        "overallPickNumber": 3,
                        "roundId": 1,
                        "roundPickNumber": 3,
                    },
                    {
                        "id": 3,
                        "playerId": 11111,
                        "teamId": 2,  # Different team
                        "bidAmount": 40,
                        "overallPickNumber": 2,
                        "roundId": 1,
                        "roundPickNumber": 2,
                    },
                ],
            }
        }

        with patch.object(client, "_make_request", new_callable=AsyncMock) as mock_request:
            with patch.object(client, "get_league_teams", new_callable=AsyncMock) as mock_teams:
                mock_request.return_value = mock_draft_response
                mock_teams.return_value = [
                    type("Team", (), {"id": 1, "name": "Test Team", "abbrev": "TEST"})()
                ]

                summary = await client.get_team_draft_summary(team_id=1)

                assert summary.teamId == 1
                assert summary.teamName == "Test Team"
                assert summary.totalSpent == 80  # 50 + 30
                assert summary.playersCount == 2
                assert summary.remainingBudget == 120  # 200 - 80

    @pytest.mark.asyncio
    async def test_get_draft_recommendation_bid_scenario(self, client):
        """Test draft recommendation for bidding scenario."""
        # Mock team summary
        mock_team_summary = TeamDraftSummary(
            teamId=1, teamName="Test Team", totalSpent=100, playersCount=5, remainingBudget=100
        )

        # Mock available players
        from espn_fantasy_basketball_mcp.models import Player

        mock_player = Player(id=12345, fullName="Test Player", defaultPositionId=1)
        mock_available_players = [
            PlayerDraftInfo(
                playerId=12345, player=mock_player, auctionValue=30, rank=25, isDrafted=False
            )
        ]

        with patch.object(client, "get_team_draft_summary", new_callable=AsyncMock) as mock_summary:
            with patch.object(
                client, "get_available_players", new_callable=AsyncMock
            ) as mock_players:
                mock_summary.return_value = mock_team_summary
                mock_players.return_value = mock_available_players

                recommendation = await client.get_draft_recommendation(
                    team_id=1, current_player_id=12345
                )

                assert recommendation.action == "bid"
                assert recommendation.playerId == 12345
                assert recommendation.playerName == "Test Player"
                assert recommendation.suggestedBid <= 30
                assert recommendation.priority >= 7

    @pytest.mark.asyncio
    async def test_get_draft_recommendation_nominate_scenario(self, client):
        """Test draft recommendation for nomination scenario."""
        # Mock team summary
        mock_team_summary = TeamDraftSummary(
            teamId=1, teamName="Test Team", totalSpent=50, playersCount=3, remainingBudget=150
        )

        # Mock available players
        from espn_fantasy_basketball_mcp.models import Player

        mock_player = Player(id=54321, fullName="Best Available Player", defaultPositionId=1)
        mock_available_players = [
            PlayerDraftInfo(
                playerId=54321, player=mock_player, auctionValue=40, rank=15, isDrafted=False
            )
        ]

        with patch.object(client, "get_team_draft_summary", new_callable=AsyncMock) as mock_summary:
            with patch.object(
                client, "get_available_players", new_callable=AsyncMock
            ) as mock_players:
                mock_summary.return_value = mock_team_summary
                mock_players.return_value = mock_available_players

                recommendation = await client.get_draft_recommendation(team_id=1)

                assert recommendation.action == "nominate"
                assert recommendation.playerId == 54321
                assert recommendation.playerName == "Best Available Player"
                assert recommendation.priority >= 9

    @pytest.mark.asyncio
    async def test_analyze_punt_strategy(self, client):
        """Test punt strategy analysis."""
        mock_team_summary = TeamDraftSummary(
            teamId=1, teamName="Test Team", totalSpent=120, playersCount=7, remainingBudget=80
        )

        with patch.object(client, "get_team_draft_summary", new_callable=AsyncMock) as mock_summary:
            mock_summary.return_value = mock_team_summary

            analysis = await client.analyze_punt_strategy(team_id=1)

            assert analysis["totalSpent"] == 120
            assert analysis["remainingBudget"] == 80
            assert analysis["playersCount"] == 7
            assert "strategy" in analysis
            assert "recommendation" in analysis

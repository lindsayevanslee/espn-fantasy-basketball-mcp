"""Test cases for ESPN Fantasy Basketball statistical analysis tools."""

from unittest.mock import AsyncMock, patch

import pytest

from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient
from espn_fantasy_basketball_mcp.models import (
    PlayerComparison,
    PlayerStats,
    TradeAnalysis,
    TrendingPlayer,
)


class TestStatisticalAnalysisModels:
    """Test cases for statistical analysis data models."""

    def test_player_stats_creation(self, sample_player_stats_data):
        """Test creating player statistics."""
        stats = PlayerStats(**sample_player_stats_data)
        assert stats.playerId == 12345
        assert stats.playerName == "Test Player"
        assert stats.timeframe == "season"
        assert stats.points == 25.5
        assert stats.rebounds == 8.2
        assert stats.fantasyPoints == 45.8
        assert stats.rank == 15

    def test_player_comparison_creation(self, sample_player_comparison_data):
        """Test creating player comparison."""
        comparison = PlayerComparison(**sample_player_comparison_data)
        assert len(comparison.players) == 2
        assert comparison.categories == ["points", "rebounds", "assists"]
        assert comparison.winner_by_category["points"] == 12345
        assert comparison.winner_by_category["rebounds"] == 54321
        assert "Player A wins 2/3 categories" in comparison.overall_recommendation

    def test_trade_analysis_creation(self, sample_trade_analysis_data):
        """Test creating trade analysis."""
        analysis = TradeAnalysis(**sample_trade_analysis_data)
        assert len(analysis.your_players) == 1
        assert len(analysis.their_players) == 1
        assert analysis.your_total_value == 45.8
        assert analysis.their_total_value == 48.2
        assert analysis.value_difference == 2.4
        assert analysis.recommendation == "slight_accept"
        assert analysis.confidence == 0.8

    def test_trending_player_creation(self, sample_trending_player_data):
        """Test creating trending player."""
        trending = TrendingPlayer(**sample_trending_player_data)
        assert trending.playerId == 12345
        assert trending.trend_direction == "up"
        assert trending.add_percentage == 15.5
        assert trending.net_adds == 1550
        assert "recent performance" in trending.reason


class TestStatisticalAnalysisClient:
    """Test cases for statistical analysis client methods."""

    @pytest.fixture
    def client(self):
        """Create a test client instance."""
        return ESPNFantasyBasketballClient(
            league_id=12345, year=2025, espn_s2="test_s2", swid="test_swid"
        )

    @pytest.mark.asyncio
    async def test_get_player_stats_success(self, client):
        """Test successful player stats retrieval."""
        mock_response = {
            "players": [
                {
                    "player": {
                        "id": 12345,
                        "fullName": "Test Player",
                        "stats": [
                            {
                                "appliedStats": {
                                    "0": 25.5,  # Points
                                    "1": 8.2,  # Rebounds
                                    "2": 6.1,  # Assists
                                    "3": 1.8,  # Steals
                                    "4": 0.9,  # Blocks
                                },
                                "appliedTotal": 45.8,
                            }
                        ],
                    }
                }
            ]
        }

        with patch.object(client, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            stats = await client.get_player_stats(12345, "season")

            assert stats.playerId == 12345
            assert stats.playerName == "Test Player"
            assert stats.timeframe == "season"
            assert stats.points == 25.5
            assert stats.rebounds == 8.2
            assert stats.assists == 6.1
            assert stats.fantasyPoints == 45.8

    @pytest.mark.asyncio
    async def test_get_player_stats_player_not_found(self, client):
        """Test player stats when player not found."""
        mock_response = {"players": []}

        with patch.object(client, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            with pytest.raises(ValueError, match="Player 12345 not found"):
                await client.get_player_stats(12345)

    @pytest.mark.asyncio
    async def test_compare_players_success(self, client):
        """Test successful player comparison."""
        # Mock two different player responses
        mock_player_1 = PlayerStats(
            playerId=12345,
            playerName="Player A",
            timeframe="season",
            points=25.5,
            rebounds=8.2,
            assists=6.1,
            fantasyPoints=45.8,
        )
        mock_player_2 = PlayerStats(
            playerId=54321,
            playerName="Player B",
            timeframe="season",
            points=22.1,
            rebounds=10.5,
            assists=4.8,
            fantasyPoints=42.3,
        )

        with patch.object(client, "get_player_stats", new_callable=AsyncMock) as mock_stats:
            mock_stats.side_effect = [mock_player_1, mock_player_2]

            comparison = await client.compare_players(
                [12345, 54321], ["points", "rebounds", "assists"]
            )

            assert len(comparison.players) == 2
            assert comparison.categories == ["points", "rebounds", "assists"]
            # Player A should win points and assists, Player B should win rebounds
            assert comparison.winner_by_category["points"] == 12345
            assert comparison.winner_by_category["rebounds"] == 54321
            assert comparison.winner_by_category["assists"] == 12345
            assert "Player A wins" in comparison.overall_recommendation

    @pytest.mark.asyncio
    async def test_compare_players_insufficient_players(self, client):
        """Test player comparison with insufficient players."""
        with patch.object(client, "get_player_stats", new_callable=AsyncMock) as mock_stats:
            mock_stats.side_effect = [ValueError("Player not found")]

            with pytest.raises(ValueError, match="Need at least 2 valid players"):
                await client.compare_players([12345])

    @pytest.mark.asyncio
    async def test_analyze_trade_proposal_accept(self, client):
        """Test trade analysis recommending accept."""
        your_player = PlayerStats(
            playerId=12345, playerName="Your Player", timeframe="season", fantasyPoints=40.0
        )
        their_player = PlayerStats(
            playerId=54321, playerName="Their Player", timeframe="season", fantasyPoints=50.0
        )

        with patch.object(client, "get_player_stats", new_callable=AsyncMock) as mock_stats:
            mock_stats.side_effect = [your_player, their_player]

            analysis = await client.analyze_trade_proposal([12345], [54321])

            assert analysis.your_total_value == 40.0
            assert analysis.their_total_value == 50.0
            assert analysis.value_difference == 10.0
            assert analysis.recommendation in ["accept", "slight_accept"]
            assert "gain" in analysis.reasoning.lower()

    @pytest.mark.asyncio
    async def test_analyze_trade_proposal_reject(self, client):
        """Test trade analysis recommending reject."""
        your_player = PlayerStats(
            playerId=12345, playerName="Your Player", timeframe="season", fantasyPoints=50.0
        )
        their_player = PlayerStats(
            playerId=54321, playerName="Their Player", timeframe="season", fantasyPoints=30.0
        )

        with patch.object(client, "get_player_stats", new_callable=AsyncMock) as mock_stats:
            mock_stats.side_effect = [your_player, their_player]

            analysis = await client.analyze_trade_proposal([12345], [54321])

            assert analysis.your_total_value == 50.0
            assert analysis.their_total_value == 30.0
            assert analysis.value_difference == -20.0
            assert analysis.recommendation in ["reject", "negotiate"]
            assert "lose" in analysis.reasoning.lower()

    @pytest.mark.asyncio
    async def test_get_trending_players_up(self, client):
        """Test getting trending up players."""
        mock_response = {
            "players": [
                {
                    "player": {"id": 12345, "fullName": "Trending Player", "defaultPositionId": 1},
                    "ownership": {
                        "percentChange": 5.5  # Trending up
                    },
                },
                {
                    "player": {"id": 54321, "fullName": "Stable Player", "defaultPositionId": 2},
                    "ownership": {
                        "percentChange": 0.2  # Not trending enough
                    },
                },
            ]
        }

        with patch.object(client, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            trending = await client.get_trending_players("up", 10)

            assert len(trending) == 1  # Only the trending up player
            assert trending[0].playerId == 12345
            assert trending[0].trend_direction == "up"
            assert trending[0].add_percentage == 5.5

    @pytest.mark.asyncio
    async def test_get_trending_players_down(self, client):
        """Test getting trending down players."""
        mock_response = {
            "players": [
                {
                    "player": {"id": 12345, "fullName": "Dropping Player", "defaultPositionId": 1},
                    "ownership": {
                        "percentChange": -3.2  # Trending down
                    },
                }
            ]
        }

        with patch.object(client, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            trending = await client.get_trending_players("down", 10)

            assert len(trending) == 1
            assert trending[0].playerId == 12345
            assert trending[0].trend_direction == "down"
            assert trending[0].drop_percentage == 3.2
            assert trending[0].add_percentage == 0.0

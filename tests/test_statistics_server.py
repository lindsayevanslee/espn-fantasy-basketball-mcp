"""Test cases for ESPN Fantasy Basketball statistical analysis MCP server tools."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Add the project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from espn_fantasy_basketball import (
    analyze_trade_proposal,
    compare_players,
    get_player_stats,
    get_trending_players,
)


class TestStatisticalAnalysisMCPTools:
    """Test cases for statistical analysis MCP server tool functions."""

    @pytest.mark.asyncio
    async def test_get_player_stats_tool(self):
        """Test the get_player_stats MCP tool."""
        mock_player_stats = {
            "playerId": 12345,
            "playerName": "Test Player",
            "timeframe": "season",
            "points": 25.5,
            "rebounds": 8.2,
            "assists": 6.1,
            "steals": 1.8,
            "blocks": 0.9,
            "fantasyPoints": 45.8
        }

        with patch('espn_fantasy_basketball.ESPNFantasyBasketballClient') as MockClient:
            mock_client_instance = MockClient.return_value
            mock_stats_obj = type('PlayerStats', (), {"model_dump": lambda self: mock_player_stats})()
            mock_client_instance.get_player_stats = AsyncMock(return_value=mock_stats_obj)

            result = await get_player_stats(
                league_id=12345,
                year=2025,
                player_id=12345,
                timeframe="season",
                espn_s2="test_s2",
                swid="test_swid"
            )

            assert result["playerId"] == 12345
            assert result["playerName"] == "Test Player"
            assert result["points"] == 25.5
            assert result["fantasyPoints"] == 45.8

            # Verify client was initialized correctly
            MockClient.assert_called_once_with(12345, 2025, "test_s2", "test_swid")
            mock_client_instance.get_player_stats.assert_called_once_with(12345, "season")

    @pytest.mark.asyncio
    async def test_compare_players_tool(self):
        """Test the compare_players MCP tool."""
        mock_comparison = {
            "players": [
                {
                    "playerId": 12345,
                    "playerName": "Player A",
                    "points": 25.5,
                    "rebounds": 8.2
                },
                {
                    "playerId": 54321,
                    "playerName": "Player B",
                    "points": 22.1,
                    "rebounds": 10.5
                }
            ],
            "categories": ["points", "rebounds"],
            "winner_by_category": {
                "points": 12345,
                "rebounds": 54321
            },
            "overall_recommendation": "Player A wins 1/2 categories",
            "analysis": "Detailed comparison across 2 statistical categories."
        }

        with patch('espn_fantasy_basketball.ESPNFantasyBasketballClient') as MockClient:
            mock_client_instance = MockClient.return_value
            mock_comparison_obj = type('PlayerComparison', (), {
                "model_dump": lambda self: mock_comparison
            })()
            mock_client_instance.compare_players = AsyncMock(return_value=mock_comparison_obj)

            result = await compare_players(
                league_id=12345,
                year=2025,
                player_ids=[12345, 54321],
                categories=["points", "rebounds"],
                espn_s2="test_s2",
                swid="test_swid"
            )

            assert len(result["players"]) == 2
            assert result["categories"] == ["points", "rebounds"]
            assert result["winner_by_category"]["points"] == 12345
            assert result["winner_by_category"]["rebounds"] == 54321
            assert "Player A wins" in result["overall_recommendation"]

            # Verify client method was called correctly
            mock_client_instance.compare_players.assert_called_once_with([12345, 54321], ["points", "rebounds"])

    @pytest.mark.asyncio
    async def test_analyze_trade_proposal_tool(self):
        """Test the analyze_trade_proposal MCP tool."""
        mock_trade_analysis = {
            "your_players": [
                {
                    "playerId": 12345,
                    "playerName": "Your Player",
                    "fantasyPoints": 40.0
                }
            ],
            "their_players": [
                {
                    "playerId": 54321,
                    "playerName": "Their Player",
                    "fantasyPoints": 45.0
                }
            ],
            "your_total_value": 40.0,
            "their_total_value": 45.0,
            "value_difference": 5.0,
            "recommendation": "slight_accept",
            "reasoning": "You gain moderate value (+5.0 fantasy points)",
            "category_impact": {
                "points": "gain",
                "rebounds": "neutral"
            },
            "confidence": 0.85
        }

        with patch('espn_fantasy_basketball.ESPNFantasyBasketballClient') as MockClient:
            mock_client_instance = MockClient.return_value
            mock_analysis_obj = type('TradeAnalysis', (), {
                "model_dump": lambda self: mock_trade_analysis
            })()
            mock_client_instance.analyze_trade_proposal = AsyncMock(return_value=mock_analysis_obj)

            result = await analyze_trade_proposal(
                league_id=12345,
                year=2025,
                your_player_ids=[12345],
                their_player_ids=[54321],
                espn_s2="test_s2",
                swid="test_swid"
            )

            assert result["your_total_value"] == 40.0
            assert result["their_total_value"] == 45.0
            assert result["value_difference"] == 5.0
            assert result["recommendation"] == "slight_accept"
            assert "gain" in result["reasoning"]
            assert result["confidence"] == 0.85

            # Verify client method was called correctly
            mock_client_instance.analyze_trade_proposal.assert_called_once_with([12345], [54321])

    @pytest.mark.asyncio
    async def test_get_trending_players_tool(self):
        """Test the get_trending_players MCP tool."""
        mock_trending_players = [
            {
                "playerId": 12345,
                "player": {
                    "id": 12345,
                    "fullName": "Trending Player",
                    "defaultPositionId": 1
                },
                "trend_direction": "up",
                "add_percentage": 8.5,
                "drop_percentage": 0.0,
                "net_adds": 850,
                "reason": "Increased add rate due to recent performance"
            },
            {
                "playerId": 54321,
                "player": {
                    "id": 54321,
                    "fullName": "Hot Player",
                    "defaultPositionId": 2
                },
                "trend_direction": "up",
                "add_percentage": 12.2,
                "drop_percentage": 0.0,
                "net_adds": 1220,
                "reason": "Increased add rate due to recent performance"
            }
        ]

        with patch('espn_fantasy_basketball.ESPNFantasyBasketballClient') as MockClient:
            mock_client_instance = MockClient.return_value
            mock_trending_objs = [
                type('TrendingPlayer', (), {"model_dump": lambda self: mock_trending_players[0]})(),
                type('TrendingPlayer', (), {"model_dump": lambda self: mock_trending_players[1]})()
            ]
            mock_client_instance.get_trending_players = AsyncMock(return_value=mock_trending_objs)

            result = await get_trending_players(
                league_id=12345,
                year=2025,
                direction="up",
                limit=20,
                espn_s2="test_s2",
                swid="test_swid"
            )

            assert len(result) == 2
            assert result[0]["playerId"] == 12345
            assert result[0]["trend_direction"] == "up"
            assert result[0]["add_percentage"] == 8.5
            assert result[1]["playerId"] == 54321
            assert result[1]["add_percentage"] == 12.2

            # Verify client method was called correctly
            mock_client_instance.get_trending_players.assert_called_once_with("up", 20)

    @pytest.mark.asyncio
    async def test_tools_with_minimal_params(self):
        """Test statistical analysis tools with minimal required parameters."""
        with patch('espn_fantasy_basketball.ESPNFantasyBasketballClient') as MockClient:
            mock_client_instance = MockClient.return_value

            # Mock returns for all tools
            mock_client_instance.get_player_stats = AsyncMock(return_value=type('PlayerStats', (), {
                "model_dump": lambda self: {"playerId": 12345, "playerName": "Test"}
            })())
            mock_client_instance.compare_players = AsyncMock(return_value=type('PlayerComparison', (), {
                "model_dump": lambda self: {"players": [], "categories": []}
            })())
            mock_client_instance.analyze_trade_proposal = AsyncMock(return_value=type('TradeAnalysis', (), {
                "model_dump": lambda self: {"recommendation": "neutral"}
            })())
            mock_client_instance.get_trending_players = AsyncMock(return_value=[])

            # Test with minimal parameters (no auth cookies, default values)
            await get_player_stats(league_id=12345, year=2025, player_id=12345)
            MockClient.assert_called_with(12345, 2025, None, None)
            mock_client_instance.get_player_stats.assert_called_with(12345, "season")

            await compare_players(league_id=12345, year=2025, player_ids=[12345, 54321])
            mock_client_instance.compare_players.assert_called_with([12345, 54321], None)

            await analyze_trade_proposal(
                league_id=12345,
                year=2025,
                your_player_ids=[12345],
                their_player_ids=[54321]
            )
            mock_client_instance.analyze_trade_proposal.assert_called_with([12345], [54321])

            await get_trending_players(league_id=12345, year=2025)
            mock_client_instance.get_trending_players.assert_called_with("up", 20)  # Default values

    @pytest.mark.asyncio
    async def test_get_player_stats_different_timeframes(self):
        """Test get_player_stats with different timeframes."""
        mock_stats = {
            "playerId": 12345,
            "playerName": "Test Player",
            "timeframe": "projections",
            "fantasyPoints": 48.2
        }

        with patch('espn_fantasy_basketball.ESPNFantasyBasketballClient') as MockClient:
            mock_client_instance = MockClient.return_value
            mock_stats_obj = type('PlayerStats', (), {"model_dump": lambda self: mock_stats})()
            mock_client_instance.get_player_stats = AsyncMock(return_value=mock_stats_obj)

            # Test projections timeframe
            result = await get_player_stats(
                league_id=12345,
                year=2025,
                player_id=12345,
                timeframe="projections"
            )

            assert result["timeframe"] == "projections"
            mock_client_instance.get_player_stats.assert_called_with(12345, "projections")

            # Test last_7 timeframe
            await get_player_stats(
                league_id=12345,
                year=2025,
                player_id=12345,
                timeframe="last_7"
            )

            mock_client_instance.get_player_stats.assert_called_with(12345, "last_7")

"""Test cases for ESPN Fantasy Basketball draft MCP server tools."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Add the project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from espn_fantasy_basketball import (
    analyze_my_draft_strategy,
    get_available_players,
    get_draft_status,
    should_i_bid,
    who_should_i_target_next,
)


class TestDraftMCPTools:
    """Test cases for draft MCP server tool functions."""

    @pytest.mark.asyncio
    async def test_get_draft_status_tool(self):
        """Test the get_draft_status MCP tool."""
        mock_draft_status = {
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
                    "roundPickNumber": 1
                }
            ],
            "currentPickNumber": 2,
            "currentNominatingTeam": 2
        }

        with patch('espn_fantasy_basketball.ESPNFantasyBasketballClient') as MockClient:
            mock_client_instance = MockClient.return_value
            mock_status_obj = type('DraftStatus', (), {"model_dump": lambda self: mock_draft_status})()
            mock_client_instance.get_draft_status = AsyncMock(return_value=mock_status_obj)

            result = await get_draft_status(
                league_id=12345,
                year=2025,
                espn_s2="test_s2",
                swid="test_swid"
            )

            assert result["inProgress"] is True
            assert result["drafted"] is False
            assert len(result["picks"]) == 1
            assert result["currentPickNumber"] == 2

            # Verify client was initialized correctly
            MockClient.assert_called_once_with(12345, 2025, "test_s2", "test_swid")

    @pytest.mark.asyncio
    async def test_should_i_bid_tool(self):
        """Test the should_i_bid MCP tool."""
        mock_recommendation = {
            "action": "bid",
            "playerId": 12345,
            "playerName": "Test Player",
            "suggestedBid": 25,
            "maxBid": 30,
            "reasoning": "Good value player at this price",
            "priority": 8,
            "category_impact": {"points": "positive"}
        }

        with patch('espn_fantasy_basketball.ESPNFantasyBasketballClient') as MockClient:
            mock_client_instance = MockClient.return_value
            mock_recommendation_obj = type('DraftRecommendation', (), {
                "model_dump": lambda self: mock_recommendation
            })()
            mock_client_instance.get_draft_recommendation = AsyncMock(return_value=mock_recommendation_obj)

            result = await should_i_bid(
                league_id=12345,
                year=2025,
                team_id=1,
                current_player_id=12345,
                espn_s2="test_s2",
                swid="test_swid"
            )

            assert result["action"] == "bid"
            assert result["playerId"] == 12345
            assert result["suggestedBid"] == 25
            assert result["priority"] == 8

            # Verify client method was called correctly
            mock_client_instance.get_draft_recommendation.assert_called_once_with(1, 12345)

    @pytest.mark.asyncio
    async def test_who_should_i_target_next_tool(self):
        """Test the who_should_i_target_next MCP tool."""
        mock_recommendation = {
            "action": "nominate",
            "playerId": 54321,
            "playerName": "Target Player",
            "suggestedBid": 40,
            "reasoning": "Best available player for your needs",
            "priority": 9,
            "category_impact": {"overall": "strong positive"}
        }

        with patch('espn_fantasy_basketball.ESPNFantasyBasketballClient') as MockClient:
            mock_client_instance = MockClient.return_value
            mock_recommendation_obj = type('DraftRecommendation', (), {
                "model_dump": lambda self: mock_recommendation
            })()
            mock_client_instance.get_draft_recommendation = AsyncMock(return_value=mock_recommendation_obj)

            result = await who_should_i_target_next(
                league_id=12345,
                year=2025,
                team_id=1
            )

            assert result["action"] == "nominate"
            assert result["playerId"] == 54321
            assert result["playerName"] == "Target Player"
            assert result["priority"] == 9

            # Verify client method was called with None for current_player_id
            mock_client_instance.get_draft_recommendation.assert_called_once_with(1, None)

    @pytest.mark.asyncio
    async def test_analyze_my_draft_strategy_tool(self):
        """Test the analyze_my_draft_strategy MCP tool."""
        mock_team_summary = {
            "teamId": 1,
            "teamName": "Test Team",
            "totalSpent": 150,
            "playersCount": 8,
            "remainingBudget": 50
        }

        mock_punt_analysis = {
            "totalSpent": 150,
            "remainingBudget": 50,
            "playersCount": 8,
            "strategy": "punt_detection_needed",
            "recommendation": "You have $50 for 5 more players"
        }

        with patch('espn_fantasy_basketball.ESPNFantasyBasketballClient') as MockClient:
            mock_client_instance = MockClient.return_value
            mock_team_summary_obj = type('TeamDraftSummary', (), {
                "model_dump": lambda self: mock_team_summary,
                "remainingBudget": 50,
                "playersCount": 8
            })()
            mock_client_instance.get_team_draft_summary = AsyncMock(return_value=mock_team_summary_obj)
            mock_client_instance.analyze_punt_strategy = AsyncMock(return_value=mock_punt_analysis)

            result = await analyze_my_draft_strategy(
                league_id=12345,
                year=2025,
                team_id=1
            )

            assert result["team_summary"]["teamName"] == "Test Team"
            assert result["punt_analysis"]["strategy"] == "punt_detection_needed"
            assert result["budget_per_remaining_player"] == 10.0  # 50 / 5 remaining

            # Verify both client methods were called
            mock_client_instance.get_team_draft_summary.assert_called_once_with(1)
            mock_client_instance.analyze_punt_strategy.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_get_available_players_tool(self):
        """Test the get_available_players MCP tool."""
        mock_players = [
            {
                "playerId": 12345,
                "player": {
                    "id": 12345,
                    "fullName": "Available Player 1",
                    "defaultPositionId": 1
                },
                "auctionValue": 30,
                "rank": 25,
                "isDrafted": False
            },
            {
                "playerId": 54321,
                "player": {
                    "id": 54321,
                    "fullName": "Available Player 2",
                    "defaultPositionId": 2
                },
                "auctionValue": 25,
                "rank": 35,
                "isDrafted": False
            }
        ]

        with patch('espn_fantasy_basketball.ESPNFantasyBasketballClient') as MockClient:
            mock_client_instance = MockClient.return_value
            mock_player_objs = [
                type('PlayerDraftInfo', (), {"model_dump": lambda self: mock_players[0]})(),
                type('PlayerDraftInfo', (), {"model_dump": lambda self: mock_players[1]})()
            ]
            mock_client_instance.get_available_players = AsyncMock(return_value=mock_player_objs)

            result = await get_available_players(
                league_id=12345,
                year=2025,
                limit=25
            )

            assert len(result) == 2
            assert result[0]["playerId"] == 12345
            assert result[0]["player"]["fullName"] == "Available Player 1"
            assert result[1]["playerId"] == 54321
            assert result[1]["auctionValue"] == 25

            # Verify client method was called with correct limit
            mock_client_instance.get_available_players.assert_called_once_with(25)

    @pytest.mark.asyncio
    async def test_tools_with_minimal_params(self):
        """Test draft tools with minimal required parameters."""
        with patch('espn_fantasy_basketball.ESPNFantasyBasketballClient') as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.get_draft_status = AsyncMock(return_value=type('DraftStatus', (), {
                "model_dump": lambda self: {"inProgress": False, "drafted": True, "picks": []}
            })())
            mock_client_instance.get_draft_recommendation = AsyncMock(return_value=type('DraftRecommendation', (), {
                "model_dump": lambda self: {"action": "pass", "reasoning": "No good options", "priority": 1}
            })())
            mock_client_instance.get_available_players = AsyncMock(return_value=[])

            # Test with minimal parameters (no auth cookies)
            await get_draft_status(league_id=12345, year=2025)
            MockClient.assert_called_with(12345, 2025, None, None)

            await should_i_bid(league_id=12345, year=2025, team_id=1, current_player_id=12345)
            mock_client_instance.get_draft_recommendation.assert_called_with(1, 12345)

            await get_available_players(league_id=12345, year=2025)
            mock_client_instance.get_available_players.assert_called_with(50)  # Default limit

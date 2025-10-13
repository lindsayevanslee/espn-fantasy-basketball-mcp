"""Test cases for ESPN Fantasy Basketball MCP server."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Add the project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from espn_fantasy_basketball import (
    _get_team_id,
    get_free_agents,
    get_league_teams,
    get_matchups,
    get_nba_schedule,
    get_team_roster,
)


class TestMCPServerTools:
    """Test cases for MCP server tool functions."""

    @pytest.mark.asyncio
    async def test_get_league_teams_tool(self):
        """Test the get_league_teams MCP tool."""
        mock_teams = [
            {
                "id": 1,
                "abbrev": "TEST",
                "name": "Test Team",
                "location": None,
                "logo": None,
                "owners": ["owner1"],
                "record": None,
            }
        ]

        with patch("espn_fantasy_basketball.ESPNFantasyBasketballClient") as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.get_league_teams = AsyncMock(
                return_value=[type("Team", (), mock_teams[0])()]
            )
            mock_client_instance.get_league_teams.return_value[0].model_dump = lambda: mock_teams[0]

            result = await get_league_teams(
                league_id=12345, year=2025, espn_s2="test_s2", swid="test_swid"
            )

            assert len(result) == 1
            assert result[0]["id"] == 1
            assert result[0]["name"] == "Test Team"

            # Verify client was initialized correctly
            MockClient.assert_called_once_with(12345, 2025, "test_s2", "test_swid")

    @pytest.mark.asyncio
    async def test_get_team_roster_tool(self):
        """Test the get_team_roster MCP tool."""
        mock_roster = {
            "teamId": 1,
            "entries": [
                {
                    "playerId": 12345,
                    "lineupSlotId": 0,
                    "playerPoolEntry": {
                        "id": 12345,
                        "player": {"id": 12345, "fullName": "Test Player", "defaultPositionId": 1},
                    },
                }
            ],
        }

        with patch("espn_fantasy_basketball.ESPNFantasyBasketballClient") as MockClient:
            mock_client_instance = MockClient.return_value
            mock_roster_obj = type("Roster", (), {"model_dump": lambda self: mock_roster})()
            mock_client_instance.get_team_roster = AsyncMock(return_value=mock_roster_obj)

            result = await get_team_roster(
                league_id=12345, year=2025, team_id=1, espn_s2="test_s2", swid="test_swid"
            )

            assert result["teamId"] == 1
            assert len(result["entries"]) == 1
            assert result["entries"][0]["playerId"] == 12345

            # Verify client method was called correctly
            mock_client_instance.get_team_roster.assert_called_once_with(1, None)

    @pytest.mark.asyncio
    async def test_get_free_agents_tool(self):
        """Test the get_free_agents MCP tool."""
        mock_players = [
            {
                "id": 12345,
                "fullName": "Free Agent",
                "defaultPositionId": 1,
                "ownership": {"percentOwned": 5.2},
            }
        ]

        with patch("espn_fantasy_basketball.ESPNFantasyBasketballClient") as MockClient:
            mock_client_instance = MockClient.return_value
            mock_player_objs = [type("Player", (), {"model_dump": lambda self: mock_players[0]})()]
            mock_client_instance.get_free_agents = AsyncMock(return_value=mock_player_objs)

            result = await get_free_agents(league_id=12345, year=2025, size=10, position_id=1)

            assert len(result) == 1
            assert result[0]["fullName"] == "Free Agent"

            # Verify client method was called correctly
            mock_client_instance.get_free_agents.assert_called_once_with(10, 1)

    @pytest.mark.asyncio
    async def test_get_matchups_tool(self):
        """Test the get_matchups MCP tool."""
        mock_matchups = [
            {
                "id": 1,
                "matchupPeriodId": 1,
                "home": {"teamId": 1, "totalPoints": 100.5},
                "away": {"teamId": 2, "totalPoints": 95.0},
                "winner": "HOME",
                "playoff": False,
            }
        ]

        with patch("espn_fantasy_basketball.ESPNFantasyBasketballClient") as MockClient:
            mock_client_instance = MockClient.return_value
            mock_matchup_objs = [
                type("Matchup", (), {"model_dump": lambda self: mock_matchups[0]})()
            ]
            mock_client_instance.get_matchups = AsyncMock(return_value=mock_matchup_objs)

            result = await get_matchups(league_id=12345, year=2025, scoring_period=1)

            assert len(result) == 1
            assert result[0]["id"] == 1
            assert result[0]["winner"] == "HOME"

            # Verify client method was called correctly
            mock_client_instance.get_matchups.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_get_nba_schedule_tool(self):
        """Test the get_nba_schedule MCP tool."""
        mock_games = [
            {
                "id": "12345",
                "date": "2025-01-15T20:00:00Z",
                "competitions": [
                    {
                        "competitors": [
                            {"team": {"id": "1", "displayName": "Lakers", "abbreviation": "LAL"}},
                            {"team": {"id": "2", "displayName": "Warriors", "abbreviation": "GSW"}},
                        ]
                    }
                ],
            }
        ]

        with patch("espn_fantasy_basketball.ESPNFantasyBasketballClient") as MockClient:
            mock_client_instance = MockClient.return_value
            mock_game_objs = [type("Game", (), {"model_dump": lambda self: mock_games[0]})()]
            mock_client_instance.get_nba_schedule = AsyncMock(return_value=mock_game_objs)

            result = await get_nba_schedule(date="2025-01-15")

            assert len(result) == 1
            assert result[0]["id"] == "12345"
            assert result[0]["date"] == "2025-01-15T20:00:00Z"

            # Verify client method was called correctly
            mock_client_instance.get_nba_schedule.assert_called_once_with("2025-01-15")

    @pytest.mark.asyncio
    async def test_tools_with_minimal_params(self):
        """Test tools with minimal required parameters."""
        with patch("espn_fantasy_basketball.ESPNFantasyBasketballClient") as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.get_league_teams = AsyncMock(return_value=[])
            mock_client_instance.get_free_agents = AsyncMock(return_value=[])
            mock_client_instance.get_matchups = AsyncMock(return_value=[])
            mock_client_instance.get_nba_schedule = AsyncMock(return_value=[])

            # Test with minimal parameters
            await get_league_teams(league_id=12345, year=2025)
            MockClient.assert_called_with(12345, 2025, None, None)

            await get_free_agents(league_id=12345, year=2025)
            mock_client_instance.get_free_agents.assert_called_with(50, None)

            await get_matchups(league_id=12345, year=2025)
            mock_client_instance.get_matchups.assert_called_with(None)

            await get_nba_schedule()
            mock_client_instance.get_nba_schedule.assert_called_with(None)


class TestTeamIdEnvVariable:
    """Test cases for ESPN_TEAM_ID environment variable functionality."""

    def test_get_team_id_with_parameter(self):
        """Test _get_team_id returns provided parameter."""
        result = _get_team_id(team_id=5)
        assert result == 5

    def test_get_team_id_with_env_variable(self, monkeypatch):
        """Test _get_team_id falls back to ESPN_TEAM_ID env var."""
        monkeypatch.setenv("ESPN_TEAM_ID", "10")
        result = _get_team_id(team_id=None)
        assert result == 10

    def test_get_team_id_parameter_overrides_env(self, monkeypatch):
        """Test _get_team_id prefers parameter over env var."""
        monkeypatch.setenv("ESPN_TEAM_ID", "10")
        result = _get_team_id(team_id=5)
        assert result == 5

    def test_get_team_id_returns_none_when_not_configured(self, monkeypatch):
        """Test _get_team_id returns None when neither parameter nor env var is set."""
        monkeypatch.delenv("ESPN_TEAM_ID", raising=False)
        result = _get_team_id(team_id=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_team_roster_with_env_team_id(self, monkeypatch):
        """Test get_team_roster uses ESPN_TEAM_ID env var when team_id not provided."""
        monkeypatch.setenv("ESPN_TEAM_ID", "7")

        mock_roster = {"teamId": 7, "entries": []}

        with patch("espn_fantasy_basketball.ESPNFantasyBasketballClient") as MockClient:
            mock_client_instance = MockClient.return_value
            mock_roster_obj = type("Roster", (), {"model_dump": lambda self: mock_roster})()
            mock_client_instance.get_team_roster = AsyncMock(return_value=mock_roster_obj)

            result = await get_team_roster(league_id=12345, year=2025)

            assert result["teamId"] == 7
            # Verify the client was called with team_id from env var
            mock_client_instance.get_team_roster.assert_called_once_with(7, None)

    @pytest.mark.asyncio
    async def test_get_team_roster_parameter_overrides_env(self, monkeypatch):
        """Test get_team_roster parameter overrides ESPN_TEAM_ID env var."""
        monkeypatch.setenv("ESPN_TEAM_ID", "7")

        mock_roster = {"teamId": 3, "entries": []}

        with patch("espn_fantasy_basketball.ESPNFantasyBasketballClient") as MockClient:
            mock_client_instance = MockClient.return_value
            mock_roster_obj = type("Roster", (), {"model_dump": lambda self: mock_roster})()
            mock_client_instance.get_team_roster = AsyncMock(return_value=mock_roster_obj)

            result = await get_team_roster(league_id=12345, year=2025, team_id=3)

            assert result["teamId"] == 3
            # Verify the client was called with explicit team_id, not env var
            mock_client_instance.get_team_roster.assert_called_once_with(3, None)

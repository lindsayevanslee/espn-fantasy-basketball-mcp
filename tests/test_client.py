"""Test cases for ESPN Fantasy Basketball API client."""

from unittest.mock import AsyncMock, patch

import pytest

from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient


class TestESPNFantasyBasketballClient:
    """Test cases for ESPN Fantasy Basketball client."""

    @pytest.fixture
    def client(self):
        """Create a test client instance."""
        return ESPNFantasyBasketballClient(
            league_id=12345,
            year=2025,
            espn_s2="test_s2",
            swid="test_swid"
        )

    def test_client_initialization(self, client):
        """Test client initialization."""
        assert client.league_id == 12345
        assert client.year == 2025
        assert client.cookies["espn_s2"] == "test_s2"
        assert client.cookies["SWID"] == "test_swid"

    def test_client_initialization_no_auth(self):
        """Test client initialization without authentication."""
        client = ESPNFantasyBasketballClient(league_id=12345, year=2025)
        assert client.league_id == 12345
        assert client.year == 2025
        assert client.cookies == {}

    @pytest.mark.asyncio
    async def test_get_league_teams_success(self, client):
        """Test successful league teams retrieval."""
        mock_response = {
            "teams": [
                {
                    "id": 1,
                    "abbrev": "TEST1",
                    "name": "Test Team 1",
                    "owners": ["owner1"]
                },
                {
                    "id": 2,
                    "abbrev": "TEST2",
                    "name": "Test Team 2",
                    "owners": ["owner2"]
                }
            ]
        }

        with patch.object(client, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            teams = await client.get_league_teams()

            assert len(teams) == 2
            assert teams[0].id == 1
            assert teams[0].name == "Test Team 1"
            assert teams[1].id == 2
            assert teams[1].name == "Test Team 2"

            # Verify the request was made correctly
            mock_request.assert_called_once()
            args, kwargs = mock_request.call_args
            params = args[1] if len(args) > 1 else kwargs.get("params", {})
            assert params.get("view") == "mTeam"

    @pytest.mark.asyncio
    async def test_get_team_roster_success(self, client):
        """Test successful team roster retrieval."""
        mock_response = {
            "teams": [
                {
                    "id": 1,
                    "roster": {
                        "entries": [
                            {
                                "playerId": 12345,
                                "lineupSlotId": 0,
                                "playerPoolEntry": {
                                    "id": 12345,
                                    "player": {
                                        "id": 12345,
                                        "fullName": "Test Player",
                                        "firstName": "Test",
                                        "lastName": "Player",
                                        "defaultPositionId": 1,
                                        "active": True,
                                        "droppable": True
                                    }
                                }
                            }
                        ]
                    }
                }
            ]
        }

        with patch.object(client, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            roster = await client.get_team_roster(team_id=1)

            assert roster.teamId == 1
            assert len(roster.entries) == 1
            assert roster.entries[0].playerId == 12345
            assert roster.entries[0].playerPoolEntry.player.fullName == "Test Player"

    @pytest.mark.asyncio
    async def test_get_team_roster_team_not_found(self, client):
        """Test team roster retrieval when team is not found."""
        mock_response = {"teams": []}

        with patch.object(client, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            with pytest.raises(ValueError, match="Team 999 not found"):
                await client.get_team_roster(team_id=999)

    @pytest.mark.asyncio
    async def test_get_free_agents_success(self, client):
        """Test successful free agents retrieval."""
        mock_response = {
            "players": [
                {
                    "onTeamId": None,  # This indicates a free agent
                    "player": {
                        "id": 12345,
                        "fullName": "Free Agent",
                        "firstName": "Free",
                        "lastName": "Agent",
                        "defaultPositionId": 1,
                        "active": True,
                        "droppable": True
                    },
                    "ownership": {
                        "percentOwned": 5.2
                    }
                }
            ]
        }

        with patch.object(client, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            players = await client.get_free_agents(size=10)

            assert len(players) == 1
            assert players[0].fullName == "Free Agent"

    @pytest.mark.asyncio
    async def test_get_matchups_success(self, client):
        """Test successful matchups retrieval."""
        mock_response = {
            "schedule": [
                {
                    "id": 1,
                    "matchupPeriodId": 1,
                    "home": {
                        "teamId": 1,
                        "totalPoints": 100.5
                    },
                    "away": {
                        "teamId": 2,
                        "totalPoints": 95.0
                    },
                    "winner": "HOME"
                }
            ]
        }

        with patch.object(client, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            matchups = await client.get_matchups()

            assert len(matchups) == 1
            assert matchups[0].id == 1
            assert matchups[0].home.teamId == 1
            assert matchups[0].away.teamId == 2
            assert matchups[0].winner == "HOME"

    @pytest.mark.asyncio
    async def test_get_nba_schedule_success(self, client):
        """Test successful NBA schedule retrieval."""
        mock_response = {
            "events": [
                {
                    "id": "12345",
                    "date": "2025-01-15T20:00:00Z",
                    "competitions": [
                        {
                            "competitors": [
                                {
                                    "team": {
                                        "id": "1",
                                        "displayName": "Lakers",
                                        "abbreviation": "LAL"
                                    }
                                },
                                {
                                    "team": {
                                        "id": "2",
                                        "displayName": "Warriors",
                                        "abbreviation": "GSW"
                                    }
                                }
                            ]
                        }
                    ]
                }
            ]
        }

        with patch.object(client, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            games = await client.get_nba_schedule()

            assert len(games) == 1
            assert games[0].id == "12345"
            assert len(games[0].competitions) == 1

    @pytest.mark.asyncio
    async def test_get_nba_schedule_api_failure(self, client):
        """Test NBA schedule retrieval when API fails."""
        with patch.object(client, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = Exception("API Error")
            games = await client.get_nba_schedule()

            # Should return empty list on failure
            assert games == []

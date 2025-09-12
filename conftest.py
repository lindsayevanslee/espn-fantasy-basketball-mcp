"""Pytest configuration file for ESPN Fantasy Basketball MCP server."""

import pytest
import asyncio


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_team_data():
    """Sample team data for testing."""
    return {
        "id": 1,
        "abbrev": "TEST",
        "name": "Test Team",
        "location": "Test City",
        "logo": "https://example.com/logo.png",
        "owners": ["owner1", "owner2"],
        "record": {
            "overall": {
                "wins": 5,
                "losses": 3,
                "percentage": 0.625
            }
        }
    }


@pytest.fixture
def sample_player_data():
    """Sample player data for testing."""
    return {
        "id": 12345,
        "fullName": "John Doe",
        "firstName": "John",
        "lastName": "Doe",
        "jersey": "23",
        "proTeamId": 1,
        "defaultPositionId": 1,
        "eligibleSlots": [0, 1, 5],
        "injured": False,
        "injuryStatus": "NORMAL",
        "active": True,
        "droppable": True,
        "ownership": {
            "percentOwned": 85.5,
            "percentStarted": 82.1
        }
    }


@pytest.fixture
def sample_roster_data():
    """Sample roster data for testing."""
    return {
        "teamId": 1,
        "entries": [
            {
                "playerId": 12345,
                "lineupSlotId": 0,
                "acquisitionDate": 1729567797137,
                "acquisitionType": "DRAFT",
                "injuryStatus": "NORMAL",
                "playerPoolEntry": {
                    "id": 12345,
                    "onTeamId": 1,
                    "keeperValue": 37,
                    "lineupLocked": False,
                    "player": {
                        "id": 12345,
                        "fullName": "John Doe",
                        "firstName": "John",
                        "lastName": "Doe",
                        "defaultPositionId": 1,
                        "active": True,
                        "droppable": True
                    }
                }
            }
        ]
    }


@pytest.fixture
def sample_matchup_data():
    """Sample matchup data for testing."""
    return {
        "id": 1,
        "matchupPeriodId": 1,
        "home": {
            "teamId": 1,
            "totalPoints": 100.5,
            "totalProjectedPoints": 105.2,
            "gamesPlayed": 10,
            "cumulativeScore": {
                "wins": 6,
                "losses": 3
            }
        },
        "away": {
            "teamId": 2,
            "totalPoints": 95.0,
            "totalProjectedPoints": 98.7,
            "gamesPlayed": 10,
            "cumulativeScore": {
                "wins": 3,
                "losses": 6
            }
        },
        "winner": "HOME",
        "playoff": False
    }


@pytest.fixture
def sample_nba_game_data():
    """Sample NBA game data for testing."""
    return {
        "id": "12345",
        "date": "2025-01-15T20:00:00Z",
        "competitions": [
            {
                "competitors": [
                    {
                        "team": {
                            "id": "1",
                            "displayName": "Los Angeles Lakers",
                            "abbreviation": "LAL"
                        }
                    },
                    {
                        "team": {
                            "id": "2",
                            "displayName": "Golden State Warriors", 
                            "abbreviation": "GSW"
                        }
                    }
                ]
            }
        ]
    }
"""Pytest configuration file for ESPN Fantasy Basketball MCP server."""

import asyncio

import pytest


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


@pytest.fixture
def sample_draft_pick_data():
    """Sample draft pick data for testing."""
    return {
        "id": 1,
        "playerId": 12345,
        "teamId": 1,
        "bidAmount": 50,
        "overallPickNumber": 1,
        "roundId": 1,
        "roundPickNumber": 1,
        "nominatingTeamId": 2,
        "keeper": False
    }


@pytest.fixture
def sample_draft_status_data():
    """Sample draft status data for testing."""
    return {
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


@pytest.fixture
def sample_player_draft_info_data():
    """Sample player draft info data for testing."""
    return {
        "playerId": 12345,
        "player": {
            "id": 12345,
            "fullName": "Test Player",
            "firstName": "Test",
            "lastName": "Player",
            "defaultPositionId": 1,
            "active": True
        },
        "draftAuctionValue": 0,
        "auctionValue": 30,
        "rank": 25,
        "isDrafted": False
    }


@pytest.fixture
def sample_team_draft_summary_data():
    """Sample team draft summary data for testing."""
    return {
        "teamId": 1,
        "teamName": "Test Team",
        "totalSpent": 150,
        "playersCount": 8,
        "remainingBudget": 50,
        "positionCounts": {"PG": 2, "SG": 1, "SF": 2, "PF": 2, "C": 1},
        "categories": {"points": 100.5, "rebounds": 75.2, "assists": 65.8}
    }


@pytest.fixture
def sample_draft_recommendation_data():
    """Sample draft recommendation data for testing."""
    return {
        "action": "bid",
        "playerId": 12345,
        "playerName": "Test Player",
        "suggestedBid": 25,
        "maxBid": 30,
        "reasoning": "Good value player at this price point",
        "priority": 8,
        "category_impact": {
            "points": "positive",
            "rebounds": "neutral",
            "assists": "slight_positive"
        }
    }

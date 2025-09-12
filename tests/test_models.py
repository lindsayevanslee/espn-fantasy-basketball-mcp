"""Test cases for ESPN Fantasy Basketball data models."""

import pytest
from espn_fantasy_basketball_mcp.models import (
    Team, Player, PlayerPoolEntry, RosterEntry, Roster,
    MatchupTeam, Matchup, NBATeam, NBAGame
)


class TestTeamModel:
    """Test cases for Team model."""
    
    def test_team_creation_minimal(self):
        """Test creating a team with minimal required fields."""
        team = Team(id=1, abbrev="TEST", name="Test Team")
        assert team.id == 1
        assert team.abbrev == "TEST"
        assert team.name == "Test Team"
        assert team.location is None
        assert team.logo is None
        assert team.owners is None
        assert team.record is None
    
    def test_team_creation_full(self):
        """Test creating a team with all fields."""
        team = Team(
            id=1,
            abbrev="TEST",
            name="Test Team",
            location="Test City",
            logo="https://example.com/logo.png",
            owners=["owner1", "owner2"],
        )
        assert team.id == 1
        assert team.abbrev == "TEST"
        assert team.name == "Test Team"
        assert team.location == "Test City"
        assert team.logo == "https://example.com/logo.png"
        assert team.owners == ["owner1", "owner2"]


class TestPlayerModel:
    """Test cases for Player model."""
    
    def test_player_creation_minimal(self):
        """Test creating a player with minimal required fields."""
        player = Player(
            id=12345,
            fullName="Test Player",
            defaultPositionId=1
        )
        assert player.id == 12345
        assert player.fullName == "Test Player"
        assert player.defaultPositionId == 1
        assert player.firstName is None
        assert player.lastName is None
        assert player.injured is None
    
    def test_player_creation_full(self):
        """Test creating a player with all fields."""
        player = Player(
            id=12345,
            fullName="John Doe",
            firstName="John",
            lastName="Doe",
            jersey="23",
            proTeamId=1,
            defaultPositionId=1,
            eligibleSlots=[0, 1, 5],
            injured=False,
            injuryStatus="NORMAL",
            active=True,
            droppable=True
        )
        assert player.id == 12345
        assert player.fullName == "John Doe"
        assert player.firstName == "John"
        assert player.lastName == "Doe"
        assert player.jersey == "23"
        assert player.proTeamId == 1
        assert player.defaultPositionId == 1
        assert player.eligibleSlots == [0, 1, 5]
        assert player.injured is False
        assert player.injuryStatus == "NORMAL"
        assert player.active is True
        assert player.droppable is True


class TestRosterModel:
    """Test cases for Roster-related models."""
    
    def test_roster_entry_creation(self):
        """Test creating a roster entry."""
        player = Player(id=12345, fullName="Test Player", defaultPositionId=1)
        player_pool_entry = PlayerPoolEntry(id=12345, player=player)
        roster_entry = RosterEntry(
            playerId=12345,
            playerPoolEntry=player_pool_entry,
            lineupSlotId=0,
            acquisitionType="DRAFT"
        )
        assert roster_entry.playerId == 12345
        assert roster_entry.playerPoolEntry.id == 12345
        assert roster_entry.lineupSlotId == 0
        assert roster_entry.acquisitionType == "DRAFT"
    
    def test_roster_creation(self):
        """Test creating a complete roster."""
        player = Player(id=12345, fullName="Test Player", defaultPositionId=1)
        player_pool_entry = PlayerPoolEntry(id=12345, player=player)
        roster_entry = RosterEntry(
            playerId=12345,
            playerPoolEntry=player_pool_entry,
            lineupSlotId=0
        )
        roster = Roster(teamId=1, entries=[roster_entry])
        assert roster.teamId == 1
        assert len(roster.entries) == 1
        assert roster.entries[0].playerId == 12345


class TestMatchupModel:
    """Test cases for Matchup model."""
    
    def test_matchup_team_creation(self):
        """Test creating a matchup team."""
        matchup_team = MatchupTeam(
            teamId=1,
            totalPoints=100.5,
            totalProjectedPoints=95.0,
            gamesPlayed=10
        )
        assert matchup_team.teamId == 1
        assert matchup_team.totalPoints == 100.5
        assert matchup_team.totalProjectedPoints == 95.0
        assert matchup_team.gamesPlayed == 10
    
    def test_matchup_creation(self):
        """Test creating a matchup."""
        home_team = MatchupTeam(teamId=1, totalPoints=100.5)
        away_team = MatchupTeam(teamId=2, totalPoints=95.0)
        matchup = Matchup(
            id=1,
            matchupPeriodId=1,
            home=home_team,
            away=away_team,
            winner="HOME"
        )
        assert matchup.id == 1
        assert matchup.matchupPeriodId == 1
        assert matchup.home.teamId == 1
        assert matchup.away.teamId == 2
        assert matchup.winner == "HOME"


class TestNBAModel:
    """Test cases for NBA-related models."""
    
    def test_nba_game_creation(self):
        """Test creating an NBA game."""
        nba_team1 = {"id": "1", "displayName": "Lakers", "abbreviation": "LAL"}
        nba_team2 = {"id": "2", "displayName": "Warriors", "abbreviation": "GSW"}
        
        competition = {
            "competitors": [
                {"team": nba_team1},
                {"team": nba_team2}
            ]
        }
        
        nba_game = NBAGame(
            id="12345",
            date="2025-01-15T20:00:00Z",
            competitions=[competition]
        )
        assert nba_game.id == "12345"
        assert nba_game.date == "2025-01-15T20:00:00Z"
        assert len(nba_game.competitions) == 1
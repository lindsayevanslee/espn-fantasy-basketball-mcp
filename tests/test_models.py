"""Test cases for ESPN Fantasy Basketball data models."""

from espn_fantasy_basketball_mcp.models import (
    DraftPick,
    DraftRecommendation,
    DraftStatus,
    Matchup,
    MatchupTeam,
    NBAGame,
    Player,
    PlayerComparison,
    PlayerDraftInfo,
    PlayerPoolEntry,
    PlayerStats,
    Roster,
    RosterEntry,
    Team,
    TeamDraftSummary,
    TradeAnalysis,
    TrendingPlayer,
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
        player = Player(id=12345, fullName="Test Player", defaultPositionId=1)
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
            droppable=True,
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
            acquisitionType="DRAFT",
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
            playerId=12345, playerPoolEntry=player_pool_entry, lineupSlotId=0
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
            teamId=1, totalPoints=100.5, totalProjectedPoints=95.0, gamesPlayed=10
        )
        assert matchup_team.teamId == 1
        assert matchup_team.totalPoints == 100.5
        assert matchup_team.totalProjectedPoints == 95.0
        assert matchup_team.gamesPlayed == 10

    def test_matchup_creation(self):
        """Test creating a matchup."""
        home_team = MatchupTeam(teamId=1, totalPoints=100.5)
        away_team = MatchupTeam(teamId=2, totalPoints=95.0)
        matchup = Matchup(id=1, matchupPeriodId=1, home=home_team, away=away_team, winner="HOME")
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

        competition = {"competitors": [{"team": nba_team1}, {"team": nba_team2}]}

        nba_game = NBAGame(id="12345", date="2025-01-15T20:00:00Z", competitions=[competition])
        assert nba_game.id == "12345"
        assert nba_game.date == "2025-01-15T20:00:00Z"
        assert len(nba_game.competitions) == 1


class TestDraftModels:
    """Test cases for draft-related models."""

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
        assert pick.teamId == 1
        assert pick.bidAmount == 50
        assert pick.overallPickNumber == 1
        assert pick.roundId == 1
        assert pick.roundPickNumber == 1
        assert pick.nominatingTeamId == 2
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
        assert status.currentNominatingTeam == 2

    def test_player_draft_info_creation(self):
        """Test creating player draft info."""
        player = Player(id=12345, fullName="Test Player", defaultPositionId=1)
        draft_info = PlayerDraftInfo(
            playerId=12345, player=player, auctionValue=30, rank=25, isDrafted=False
        )
        assert draft_info.playerId == 12345
        assert draft_info.player.fullName == "Test Player"
        assert draft_info.auctionValue == 30
        assert draft_info.rank == 25
        assert draft_info.isDrafted is False

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
        assert summary.teamName == "Test Team"
        assert summary.totalSpent == 150
        assert summary.playersCount == 8
        assert summary.remainingBudget == 50
        assert summary.positionCounts["PG"] == 2
        assert summary.categories["points"] == 100.5

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
        assert recommendation.playerId == 12345
        assert recommendation.playerName == "Test Player"
        assert recommendation.suggestedBid == 25
        assert recommendation.maxBid == 30
        assert recommendation.reasoning == "Good value at this price"
        assert recommendation.priority == 8
        assert recommendation.category_impact["points"] == "positive"


class TestStatisticalAnalysisModels:
    """Test cases for statistical analysis models."""

    def test_player_stats_creation(self):
        """Test creating player statistics."""
        stats = PlayerStats(
            playerId=12345,
            playerName="Test Player",
            timeframe="season",
            gamesPlayed=50,
            points=25.5,
            rebounds=8.2,
            assists=6.1,
            steals=1.8,
            blocks=0.9,
            threePointMade=2.1,
            fieldGoalPercentage=0.485,
            freeThrowPercentage=0.825,
            turnovers=3.2,
            minutes=34.5,
            fantasyPoints=45.8,
            rank=15,
        )
        assert stats.playerId == 12345
        assert stats.playerName == "Test Player"
        assert stats.timeframe == "season"
        assert stats.points == 25.5
        assert stats.rebounds == 8.2
        assert stats.assists == 6.1
        assert stats.fantasyPoints == 45.8
        assert stats.rank == 15

    def test_player_stats_minimal(self):
        """Test creating player statistics with minimal fields."""
        stats = PlayerStats(playerId=12345, playerName="Test Player", timeframe="season")
        assert stats.playerId == 12345
        assert stats.playerName == "Test Player"
        assert stats.timeframe == "season"
        assert stats.points is None
        assert stats.fantasyPoints is None

    def test_player_comparison_creation(self):
        """Test creating player comparison."""
        player_a = PlayerStats(
            playerId=12345, playerName="Player A", timeframe="season", points=25.5, rebounds=8.2
        )
        player_b = PlayerStats(
            playerId=54321, playerName="Player B", timeframe="season", points=22.1, rebounds=10.5
        )

        comparison = PlayerComparison(
            players=[player_a, player_b],
            categories=["points", "rebounds"],
            winner_by_category={"points": 12345, "rebounds": 54321},
            overall_recommendation="Player A wins 1/2 categories",
            analysis="Balanced comparison",
        )

        assert len(comparison.players) == 2
        assert comparison.categories == ["points", "rebounds"]
        assert comparison.winner_by_category["points"] == 12345
        assert comparison.winner_by_category["rebounds"] == 54321
        assert "Player A wins" in comparison.overall_recommendation

    def test_trade_analysis_creation(self):
        """Test creating trade analysis."""
        your_player = PlayerStats(
            playerId=12345, playerName="Your Player", timeframe="season", fantasyPoints=45.8
        )
        their_player = PlayerStats(
            playerId=54321, playerName="Their Player", timeframe="season", fantasyPoints=48.2
        )

        analysis = TradeAnalysis(
            your_players=[your_player],
            their_players=[their_player],
            your_total_value=45.8,
            their_total_value=48.2,
            value_difference=2.4,
            recommendation="slight_accept",
            reasoning="You gain moderate value",
            category_impact={"points": "gain", "rebounds": "loss"},
            confidence=0.8,
        )

        assert len(analysis.your_players) == 1
        assert len(analysis.their_players) == 1
        assert analysis.your_total_value == 45.8
        assert analysis.their_total_value == 48.2
        assert analysis.value_difference == 2.4
        assert analysis.recommendation == "slight_accept"
        assert analysis.confidence == 0.8
        assert analysis.category_impact["points"] == "gain"

    def test_trending_player_creation(self):
        """Test creating trending player."""
        player = Player(id=12345, fullName="Trending Player", defaultPositionId=1)

        trending = TrendingPlayer(
            playerId=12345,
            player=player,
            trend_direction="up",
            add_percentage=15.5,
            drop_percentage=0.0,
            net_adds=1550,
            reason="Increased add rate due to recent performance",
        )

        assert trending.playerId == 12345
        assert trending.player.fullName == "Trending Player"
        assert trending.trend_direction == "up"
        assert trending.add_percentage == 15.5
        assert trending.drop_percentage == 0.0
        assert trending.net_adds == 1550
        assert "recent performance" in trending.reason

"""Data models for ESPN Fantasy Basketball API responses."""

from typing import Any

from pydantic import BaseModel


class PlayerStats(BaseModel):
    """Player statistics for a given timeframe."""

    playerId: int
    playerName: str
    timeframe: str  # "season", "last_7", "last_30", "projections"
    gamesPlayed: int | None = None
    points: float | None = None
    rebounds: float | None = None
    assists: float | None = None
    steals: float | None = None
    blocks: float | None = None
    threePointMade: float | None = None
    fieldGoalPercentage: float | None = None
    freeThrowPercentage: float | None = None
    turnovers: float | None = None
    minutes: float | None = None
    fantasyPoints: float | None = None
    rank: int | None = None


class PlayerComparison(BaseModel):
    """Comparison between multiple players."""

    players: list[PlayerStats]
    categories: list[str]
    winner_by_category: dict[str, int]  # category -> player_id
    overall_recommendation: str
    analysis: str


class TradeAnalysis(BaseModel):
    """Analysis of a trade proposal."""

    your_players: list[PlayerStats]
    their_players: list[PlayerStats]
    your_total_value: float
    their_total_value: float
    value_difference: float
    recommendation: str  # "accept", "reject", "negotiate"
    reasoning: str
    category_impact: dict[str, str]  # category -> "gain", "loss", "neutral"
    confidence: float  # 0-1 confidence in recommendation


class TrendingPlayer(BaseModel):
    """Player trending information."""

    playerId: int
    player: "Player"
    trend_direction: str  # "up", "down", "hot", "cold"
    add_percentage: float
    drop_percentage: float
    net_adds: int
    reason: str


class Owner(BaseModel):
    firstName: str
    lastName: str
    displayName: str | None = None


class OverallRecord(BaseModel):
    wins: int
    losses: int
    percentage: float | None = None


class TeamRecord(BaseModel):
    overall: OverallRecord | None = None


class Team(BaseModel):
    id: int
    abbrev: str
    name: str
    location: str | None = None  # Make location optional since ESPN doesn't always provide it
    logo: str | None = None
    owners: list[str] | None = None  # ESPN returns owner IDs as strings
    record: TeamRecord | None = None


class PlayerOwnership(BaseModel):
    percentOwned: float | None = None
    percentChange: float | None = None
    percentStarted: float | None = None


class Player(BaseModel):
    id: int
    fullName: str
    firstName: str | None = None
    lastName: str | None = None
    jersey: str | None = None
    proTeamId: int | None = None
    defaultPositionId: int
    eligibleSlots: list[int] | None = None
    injured: bool | None = None
    injuryStatus: str | None = None
    stats: dict[str, Any] | None = None
    ownership: PlayerOwnership | None = None
    active: bool | None = None
    droppable: bool | None = None


class PlayerPoolEntry(BaseModel):
    id: int
    player: Player
    onTeamId: int | None = None
    keeperValue: int | None = None
    keeperValueFuture: int | None = None
    lineupLocked: bool | None = None


class RosterEntry(BaseModel):
    playerId: int
    playerPoolEntry: PlayerPoolEntry
    lineupSlotId: int
    acquisitionDate: int | None = None
    acquisitionType: str | None = None
    injuryStatus: str | None = None


class Roster(BaseModel):
    teamId: int
    entries: list[RosterEntry]


class MatchupTeam(BaseModel):
    teamId: int | None = None
    totalPoints: float | None = None
    totalProjectedPoints: float | None = None
    gamesPlayed: int | None = None
    cumulativeScore: dict[str, Any] | None = None


class Matchup(BaseModel):
    id: int
    matchupPeriodId: int
    home: MatchupTeam | None = None
    away: MatchupTeam | None = None
    winner: str | None = None
    playoff: bool | None = None


class NBATeam(BaseModel):
    id: str
    displayName: str
    abbreviation: str


class NBACompetitor(BaseModel):
    team: NBATeam


class NBACompetition(BaseModel):
    competitors: list[NBACompetitor]


class NBAGame(BaseModel):
    id: str
    date: str
    competitions: list[NBACompetition]


class PlayerScheduleGame(BaseModel):
    """A single game in a player's schedule."""

    date: str  # YYYY-MM-DD format
    opponent: str  # Opponent team abbreviation
    is_home: bool  # True if home game, False if away
    game_id: str | None = None


class PlayerSchedule(BaseModel):
    """Schedule information for a player."""

    playerId: int
    playerName: str
    teamAbbreviation: str  # NBA team abbreviation
    games: list[PlayerScheduleGame]
    gamesThisWeek: int  # Number of games in current scoring period
    gamesNextWeek: int  # Number of games in next scoring period


class RosterScheduleSummary(BaseModel):
    """Schedule summary for an entire fantasy roster."""

    teamId: int
    scoringPeriod: int
    playerSchedules: list[PlayerSchedule]
    totalGamesThisWeek: int
    averageGamesPerPlayer: float


# Draft-related models
class DraftPick(BaseModel):
    id: int
    playerId: int
    teamId: int
    bidAmount: int
    overallPickNumber: int
    roundId: int
    roundPickNumber: int
    nominatingTeamId: int | None = None
    memberId: str | None = None
    lineupSlotId: int | None = None
    keeper: bool = False


class DraftStatus(BaseModel):
    inProgress: bool
    drafted: bool
    completeDate: int | None = None
    picks: list[DraftPick]
    currentPickNumber: int | None = None
    currentNominatingTeam: int | None = None


class PlayerDraftInfo(BaseModel):
    playerId: int
    player: Player
    draftAuctionValue: int | None = None
    auctionValue: int | None = None  # ESPN's projected value
    rank: int | None = None
    isDrafted: bool = False
    draftedByTeam: int | None = None
    bidAmount: int | None = None


class TeamDraftSummary(BaseModel):
    teamId: int
    teamName: str
    totalSpent: int
    playersCount: int
    remainingBudget: int
    positionCounts: dict[str, int] = {}
    categories: dict[str, float] = {}  # Projected category totals


class DraftRecommendation(BaseModel):
    action: str  # "bid", "pass", "nominate"
    playerId: int | None = None
    playerName: str | None = None
    suggestedBid: int | None = None
    maxBid: int | None = None
    reasoning: str
    priority: int  # 1-10, 10 being highest
    category_impact: dict[str, str] = {}  # How this player affects your categories


# League Settings Models
class ScoringItem(BaseModel):
    """A single scoring category."""
    statId: int
    points: float
    isReverseItem: bool = False
    pointsOverrides: dict[str, Any] = {}


class ScoringSettings(BaseModel):
    """League scoring configuration."""
    scoringType: str  # "H2H_CATEGORY", "H2H_POINTS", "ROTO"
    scoringItems: list[ScoringItem]
    playerRankType: str | None = None
    matchupTieRule: str | None = None
    allowOutOfPositionScoring: bool = False


class ScheduleSettings(BaseModel):
    """League schedule configuration."""
    matchupPeriodCount: int
    matchupPeriodLength: int
    matchupPeriods: dict[str, list[int]]  # Maps matchup period to scoring periods
    periodTypeId: int
    playoffTeamCount: int
    playoffMatchupPeriodLength: int
    playoffSeedingRule: str | None = None


class RosterSettings(BaseModel):
    """League roster configuration."""
    lineupSlotCounts: dict[str, int]  # Maps slot ID to count
    positionLimits: dict[str, int]  # Maps position ID to max count (-1 = unlimited)
    lineupLocktimeType: str  # When lineups lock
    rosterLocktimeType: str | None = None
    isBenchUnlimited: bool = False
    moveLimit: int = -1  # -1 = unlimited


class AcquisitionSettings(BaseModel):
    """League acquisition/waiver configuration."""
    acquisitionType: str  # "WAIVERS_TRADITIONAL", "FREE_AGENT", etc.
    waiverHours: int
    waiverProcessDays: list[str]  # Days waivers process (e.g., ["SUNDAY"])
    waiverProcessHour: int  # Hour (0-23) waivers process
    matchupAcquisitionLimit: float  # Max acquisitions per matchup
    matchupLimitPerScoringPeriod: bool
    acquisitionLimit: int = -1  # Season limit (-1 = unlimited)
    minimumBid: int = 0


class TradeSettings(BaseModel):
    """League trade configuration."""
    deadlineDate: int | None = None  # Timestamp
    vetoVotesRequired: int
    revisionHours: int  # Hours to revise trade
    max: int = -1  # Max trades per season (-1 = unlimited)
    allowOutOfUniverse: bool = False


class LeagueStatus(BaseModel):
    """Current league status."""
    currentMatchupPeriod: int
    latestScoringPeriod: int
    firstScoringPeriod: int
    finalScoringPeriod: int
    isActive: bool
    transactionScoringPeriod: int | None = None


class LeagueSettings(BaseModel):
    """Complete league settings."""
    leagueId: int
    leagueName: str
    seasonId: int
    size: int  # Number of teams
    scoringSettings: ScoringSettings
    scheduleSettings: ScheduleSettings
    rosterSettings: RosterSettings
    acquisitionSettings: AcquisitionSettings
    tradeSettings: TradeSettings
    status: LeagueStatus

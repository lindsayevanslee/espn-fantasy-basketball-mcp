"""Data models for ESPN Fantasy Basketball API responses."""

from __future__ import annotations

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
    fieldGoalPercentage: float | None = None  # 0-100 scale (e.g. 47.8)
    freeThrowPercentage: float | None = None  # 0-100 scale
    fieldGoalsMade: float | None = None  # per game; lets FG% be projected as made/attempted
    fieldGoalsAttempted: float | None = None
    freeThrowsMade: float | None = None
    freeThrowsAttempted: float | None = None
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
    player: Player
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


class TeamSeasonStats(BaseModel):
    """Team statistics aggregated across the entire season."""

    teamId: int
    teamName: str | None = None
    categoryScores: dict[str, float]  # Season totals for each scoring category
    componentStats: dict[str, float] | None = None  # Component stats (FGM, FGA, FTM, FTA) totals
    totalGamesPlayed: int | None = None  # Total games played across all matchups
    matchupWins: int | None = None  # Number of matchup wins
    matchupLosses: int | None = None  # Number of matchup losses
    matchupTies: int | None = None  # Number of matchup ties
    winPercentage: float | None = None  # Win percentage (wins / (wins + losses), excludes ties)
    gamesBack: float | None = None  # Games behind the league leader


class CategoryProjection(BaseModel):
    """Projection for a single category in the matchup."""

    category: str  # Category name (e.g., "points", "rebounds")
    yourCurrent: float  # Your current total
    opponentCurrent: float  # Opponent's current total
    yourProjected: float | None = None  # Your projected total
    opponentProjected: float | None = None  # Opponent's projected total
    currentLead: float  # Your current lead (positive = winning, negative = losing)
    projectedLead: float | None = None  # Projected lead
    projectedResult: str | None = None  # "win", "loss", "tie", or "close"
    margin: float | None = None  # Projected margin (absolute value)
    isClose: bool = False  # Whether this category is close (within threshold)


class PlayerRecommendation(BaseModel):
    """Recommendation for a specific player."""

    playerId: int
    playerName: str
    position: str | None = None
    lineupSlotId: int | None = None
    lineupSlotName: str | None = None
    gamesRemaining: int | None = None  # Scheduled games not yet played this matchup
    availability: str | None = (
        None  # ACTIVE, DAY_TO_DAY, QUESTIONABLE, DOUBTFUL, OUT, SUSPENDED, IR, FA
    )
    expectedGames: float | None = None  # gamesRemaining discounted by availability
    priority: int  # Priority score (1-10, higher = more important to start)
    reasoning: str
    categoriesHelped: list[str]  # Categories this player helps with
    categoriesHurt: list[str] = []  # Categories this player hurts (e.g., turnovers, low FT%)
    injuryStatus: str | None = None
    todaysGame: TodaysGame | None = None


class MatchupAnalysis(BaseModel):
    """Comprehensive analysis of the current matchup."""

    matchupId: int
    scoringPeriod: int
    yourTeamId: int
    opponentTeamId: int
    yourTeamName: str | None = None
    opponentTeamName: str | None = None

    # Category analysis
    categoryProjections: list[CategoryProjection]  # Projections for each category
    categoriesWinning: list[str]  # Categories you're projected to win
    categoriesLosing: list[str]  # Categories you're projected to lose
    categoriesTied: list[str]  # Categories projected to tie
    closeCategories: list[str]  # Categories that are close (within threshold)

    # Player recommendations
    playerRecommendations: list[PlayerRecommendation]  # Prioritized player recommendations

    # Additional context
    yourGamesRemaining: int | None = None  # Scheduled games not yet played, all rostered players
    opponentGamesRemaining: int | None = None
    yourExpectedGames: float | None = (
        None  # Games remaining discounted by availability (OUT, IR, FA...)
    )
    opponentExpectedGames: float | None = None
    currentCategoryWins: int | None = None  # Current category wins
    currentCategoryLosses: int | None = None  # Current category losses
    currentCategoryTies: int | None = None  # Current category ties
    projectedCategoryWins: int | None = None  # Projected category wins
    projectedCategoryLosses: int | None = None  # Projected category losses

    # Strategy recommendations
    strategyNotes: list[str]  # Strategic notes and recommendations
    lineupWarnings: list[str] = []  # Starters who cannot play (OUT, suspended, unsigned, on IR)


class PlayerSearchResult(BaseModel):
    """A player matched by name, with their status in this league when known."""

    playerId: int
    fullName: str
    matchScore: float  # 1.0 = exact name match
    defaultPosition: str | None = None
    proTeamAbbrev: str | None = None  # "FA" if not on an NBA roster
    injuryStatus: str | None = None
    isFreeAgent: bool | None = None  # True if no fantasy team owns the player (None if unknown)
    fantasyTeamId: int | None = None
    fantasyTeamName: str | None = None
    percentOwned: float | None = None


class InjuryReport(BaseModel):
    """One entry from ESPN's NBA injury report, joined to a fantasy roster when possible."""

    playerId: int | None = None  # ESPN athlete ID (same ID space as fantasy playerId)
    playerName: str
    nbaTeam: str | None = None  # Canonical abbreviation
    position: str | None = None
    status: str | None = None  # e.g. "Out", "Day-To-Day", "Questionable"
    fantasyStatus: str | None = None  # ESPN's fantasy code, e.g. "O", "DTD", "GTD"
    injury: str | None = None  # e.g. "Knee" / "Left knee soreness"
    comment: str | None = None  # Short note
    longComment: str | None = None  # Full note, often with the expected timeline
    returnDate: str | None = None  # ESPN's estimated return date (YYYY-MM-DD) when given
    reportedAt: str | None = None  # ISO 8601 in MY_TIMEZONE
    onRoster: bool | None = None  # True if on the requested fantasy team
    lineupSlot: str | None = None  # Slot on that team, e.g. "SF", "BENCH", "IR"


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
    proTeamAbbrev: str | None = None  # NBA team abbreviation (e.g., "MIN", "LAL"); "FA" if unsigned
    proTeamName: str | None = None  # NBA team full name (e.g., "Timberwolves", "Lakers")
    defaultPositionId: int
    defaultPosition: str | None = None  # Human-readable position name (e.g., "PG", "SG")
    eligibleSlots: list[int] | None = None
    eligibleSlotNames: list[str] | None = (
        None  # Human-readable slot names (e.g., ["PG", "SG", "G"])
    )
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


class TodaysGame(BaseModel):
    """Information about a player's game today."""

    opponent: str | None = None  # Opponent team abbreviation (e.g., "DET")
    time: str | None = None  # Game time (e.g., "6:00 PM")
    timeISO: str | None = (
        None  # ISO 8601 formatted datetime with timezone (e.g., "2026-02-28T18:00:00-05:00")
    )
    home: bool | None = None  # True if home game, False if away


class RosterEntry(BaseModel):
    playerId: int
    playerPoolEntry: PlayerPoolEntry
    lineupSlotId: int
    lineupSlotName: str | None = None  # Human-readable slot name (e.g., "PG", "BENCH", "IR")
    acquisitionDate: int | None = None  # Epoch timestamp in milliseconds
    acquisitionDateISO: str | None = (
        None  # ISO 8601 formatted datetime with timezone (e.g., "2026-02-28T23:00:00-05:00")
    )
    acquisitionType: str | None = None
    injuryStatus: str | None = None
    todaysGame: TodaysGame | None = None  # Today's game info if player has a game


class Roster(BaseModel):
    teamId: int
    entries: list[RosterEntry]


class MatchupTeam(BaseModel):
    teamId: int | None = None
    teamName: str | None = None  # Fantasy team name (e.g., "John's Squad")
    totalPoints: float | None = None
    totalProjectedPoints: float | None = None
    gamesPlayed: int | None = None
    cumulativeScore: dict[str, Any] | None = (
        None  # Original stat IDs (deprecated, use categoryScores instead)
    )
    categoryScores: dict[str, float] | None = None  # Scoring categories only (human-readable names)
    componentStats: dict[str, float] | None = (
        None  # Component stats (FGM, FGA, FTM, FTA) that aren't scoring categories
    )


class Matchup(BaseModel):
    id: int
    matchupPeriodId: int
    home: MatchupTeam | None = None
    away: MatchupTeam | None = None
    winner: str | None = None
    playoff: bool | None = None


class CurrentMatchup(BaseModel):
    """Complete current matchup information including rosters and scores."""

    matchupId: int
    scoringPeriod: int
    yourTeam: MatchupTeam
    opponentTeam: MatchupTeam
    yourRoster: Roster
    opponentRoster: Roster
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

    date: str  # YYYY-MM-DD format, in the MY_TIMEZONE timezone
    opponent: str  # Opponent team abbreviation
    is_home: bool  # True if home game, False if away
    game_id: str | None = None
    datetimeISO: str | None = None  # Tip-off as ISO 8601 with offset, in MY_TIMEZONE (when known)


class PlayerSchedule(BaseModel):
    """Schedule information for a player."""

    playerId: int
    playerName: str
    teamAbbreviation: str  # NBA team abbreviation
    games: list[PlayerScheduleGame]
    gamesThisWeek: int  # Games in this matchup period (or week)
    gamesNextWeek: int  # Games in the next matchup period (or week)
    note: str | None = None  # e.g. "Not on an NBA roster; cannot play"


class RosterScheduleSummary(BaseModel):
    """Schedule summary for an entire fantasy roster."""

    teamId: int
    scoringPeriod: int
    playerSchedules: list[PlayerSchedule]
    totalGamesThisWeek: int
    totalGamesNextWeek: int = 0
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
    currentNominatingTeam: int | None = None  # From the league's pickOrder (None if unknown)
    draftType: str | None = None  # "AUCTION" or "SNAKE"


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
    budget: int = 200  # League auction budget (from draftSettings.auctionBudget)
    rosterSize: int = 13  # Roster spots excluding IR (from rosterSettings.lineupSlotCounts)
    remainingSlots: int | None = None  # rosterSize - playersCount
    draftType: str | None = None  # "AUCTION" or "SNAKE"
    positionCounts: dict[str, int] = {}  # Drafted players by default position
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
    categoryName: str | None = (
        None  # Human-readable category name (e.g., "points", "rebounds", "assists")
    )
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
    # ESPN's raw mapping of matchup period -> week number(s). It is week-indexed, NOT a list of
    # daily scoring periods: a normal period has one entry, a two-week period two. Use
    # matchupPeriodDates for calendar dates.
    matchupPeriods: dict[str, list[int]]
    matchupPeriodDates: dict[str, list[str]] | None = None  # period -> [first_day, last_day]
    periodTypeId: int
    playoffTeamCount: int
    playoffMatchupPeriodLength: int
    playoffSeedingRule: str | None = None


class RosterSettings(BaseModel):
    """League roster configuration."""

    lineupSlotCounts: dict[str, int]  # Maps slot ID to count
    lineupSlotNames: dict[str, str] | None = (
        None  # Maps slot ID to human-readable slot name (e.g., "0" -> "PG", "12" -> "BENCH")
    )
    positionLimits: dict[str, int]  # Maps position ID to max count (-1 = unlimited)
    positionLimitNames: dict[str, int] | None = None  # Same limits keyed by position name
    lineupLocktimeType: str  # When lineups lock
    rosterSize: int | None = None  # Total roster spots excluding IR (sum of lineupSlotCounts)
    rosterLocktimeType: str | None = None
    isBenchUnlimited: bool = False
    moveLimit: int = -1  # -1 = unlimited


class AcquisitionSettings(BaseModel):
    """League acquisition/waiver configuration."""

    acquisitionType: str  # "WAIVERS_TRADITIONAL", "FREE_AGENT", etc.
    waiverHours: int
    waiverProcessDays: list[str]  # Days waivers process (e.g., ["SUNDAY"])
    waiverProcessHour: int  # Hour (0-23) waivers process, in ESPN's Eastern time
    waiverProcessHourTimezone: str = "America/New_York"  # ESPN's canonical timezone
    waiverProcessTimeLocal: str | None = (
        None  # Same time in MY_TIMEZONE, e.g. "07:00 America/Chicago"
    )
    matchupAcquisitionLimit: float  # Max acquisitions per matchup
    matchupLimitPerScoringPeriod: bool
    acquisitionLimit: int = -1  # Season limit (-1 = unlimited)
    minimumBid: int = 0


class TradeSettings(BaseModel):
    """League trade configuration."""

    deadlineDate: int | None = None  # Epoch timestamp in milliseconds
    deadlineDateISO: str | None = (
        None  # ISO 8601 formatted datetime with timezone (e.g., "2026-02-28T23:00:00-05:00")
    )
    vetoVotesRequired: int
    revisionHours: int  # Hours to revise trade
    max: int = -1  # Max trades per season (-1 = unlimited)
    allowOutOfUniverse: bool = False


class DraftSettings(BaseModel):
    """League draft configuration."""

    type: str | None = None  # "AUCTION" or "SNAKE"
    auctionBudget: int | None = None
    pickOrder: list[int] = []  # Team IDs in draft (and auction nomination) order
    keeperCount: int = 0
    date: int | None = None  # Epoch ms
    dateISO: str | None = None  # Draft date in MY_TIMEZONE


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
    draftSettings: DraftSettings = DraftSettings()
    status: LeagueStatus

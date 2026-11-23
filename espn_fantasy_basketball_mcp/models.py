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

    players: list[PlayerStats]  # on `basis`
    basis: str = "season"  # timeframe `players` and `winner_by_category` are on
    categories: list[str]
    winner_by_category: dict[str, int]  # category -> player_id, on `basis`
    overall_recommendation: str
    analysis: str
    # The same players on every basis, side by side, so actuals and projections are never
    # compared across players by accident: {"season": [...], "projections": [...], ...}
    bases: dict[str, list[PlayerStats]] = {}
    winners_by_basis: dict[str, dict[str, int]] = {}  # basis -> category -> player_id
    note: str | None = None


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
    ties: int | None = None
    percentage: float | None = None


class TeamRecord(BaseModel):
    overall: OverallRecord | None = None


class TransactionCounter(BaseModel):
    """ESPN's per-team transaction tallies (mTeam view)."""

    acquisitions: int | None = None  # Season adds (free agent + waiver)
    drops: int | None = None
    trades: int | None = None
    moveToIR: int | None = None
    matchupAcquisitionTotals: dict[str, int] = {}  # matchup period -> adds in that period


class MatchupRecord(BaseModel):
    """Matchup-level wins, losses and ties from completed matchup periods (one result per
    period), computed from the league schedule's winner field."""

    wins: int = 0
    losses: int = 0
    ties: int = 0
    completedMatchupPeriods: int = 0  # periods with a decided winner that this record covers


class Team(BaseModel):
    id: int
    abbrev: str
    name: str
    location: str | None = None  # Make location optional since ESPN doesn't always provide it
    logo: str | None = None
    owners: list[str] | None = None  # ESPN returns owner IDs as strings
    record: TeamRecord | None = None
    waiverRank: int | None = None  # 1 = first claim on waivers
    transactionCounter: TransactionCounter | None = None
    # Adds used in the current matchup period against the effective limit (per-day limits are
    # multiplied by the days in the period). Limit None = no limit.
    acquisitionsThisMatchup: int | None = None
    acquisitionLimitThisMatchup: int | None = None
    acquisitionsRemainingThisMatchup: int | None = None
    # What one win/loss in `record` means: "categories" in an H2H Each Category league (one
    # result per scoring category per matchup), "matchups" in Most Categories or Points leagues.
    recordType: str | None = None
    recordDescription: str | None = None
    # One result per completed matchup period, derived from the schedule. In an H2H Each
    # Category league this is NOT what ESPN ranks the standings by (that is `record`), but it is
    # the only place a matchup W-L-T is available.
    matchupRecord: MatchupRecord | None = None
    # Place in the standings, 1 = first: ESPN's playoffSeed when it provides one, otherwise the
    # order of `record` (percentage, then wins). get_league_teams returns teams in this order.
    standingsRank: int | None = None
    playoffSeed: int | None = None  # ESPN's own current seed, as sent (mTeam.playoffSeed)
    isMyTeam: bool | None = None  # True for the team ESPN_TEAM_ID (or team_id) points at
    # transactionCounter.matchupAcquisitionTotals can carry a key for a matchup period that has
    # not started yet (ESPN books a move under the period it takes effect in). Reported as sent.
    matchupAcquisitionTotalsNote: str | None = None


class TeamSeasonStats(BaseModel):
    """Team statistics aggregated across the entire season."""

    teamId: int
    teamName: str | None = None
    categoryScores: dict[str, float]  # Season totals for each scoring category
    componentStats: dict[str, float] | None = None  # Component stats (FGM, FGA, FTM, FTA) totals
    # Matchup results from completed matchup periods, one per period, derived from the
    # schedule's winner field. These are never category tallies.
    matchupWins: int | None = None
    matchupLosses: int | None = None
    matchupTies: int | None = None
    completedMatchupPeriods: int | None = None  # periods the matchup record covers
    winPercentage: float | None = None  # matchupWins / (matchupWins + matchupLosses)
    # ESPN's own record for the team (mTeam record.overall). In an H2H Each Category league it
    # counts categories (every category in every matchup is one W/L/T) and is what ESPN's
    # standings use; in Most Categories and Points leagues it equals the matchup record.
    espnRecord: OverallRecord | None = None
    espnRecordType: str | None = None  # "categories" or "matchups"
    espnRecordDescription: str | None = None
    gamesBack: float | None = None  # Games behind the leader, on the matchup record
    gamesBackDescription: str | None = None


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
    isClose: bool = False  # margin <= closeThreshold
    # "close" (margin <= closeThreshold), "near" (<= nearThreshold, 1.5x close: effectively
    # in play, e.g. steals at 2.2 against a threshold of 2.0) or "clear"
    closeness: str | None = None
    nearThreshold: float | None = None
    # The closeness threshold used for this category and how it was chosen. Counting
    # categories use a per-category margin (roughly what two good player-games swing);
    # percentages use the lead expressed in made shots over the projected attempts.
    closeThreshold: float | None = None
    closenessRule: str | None = None
    # Percentage categories only: the made/attempted behind the current and projected values,
    # so yourProjected == yourProjectedMade / yourProjectedAttempted can be checked
    yourCurrentMade: float | None = None
    yourCurrentAttempted: float | None = None
    yourProjectedMade: float | None = None
    yourProjectedAttempted: float | None = None
    opponentCurrentMade: float | None = None
    opponentCurrentAttempted: float | None = None
    opponentProjectedMade: float | None = None
    opponentProjectedAttempted: float | None = None
    # The same category on the alternate basis (season actuals when the projection used ESPN
    # projections, and the other way round), so the two can be compared. basesAgree is False
    # when they give a different result or one calls the category close and the other clear.
    alternateBasis: str | None = None
    alternateProjectedLead: float | None = None
    alternateResult: str | None = None
    alternateCloseness: str | None = None
    basesAgree: bool | None = None
    # True for turnovers (and any category the league scores in reverse): the lower total
    # wins, and currentLead / projectedLead are flipped so that positive is still good
    lowerIsBetter: bool = False
    # Range of outcomes (see MatchupAnalysis.outcomeRange for the method). The ranges are
    # [low, high] central 80% intervals for each team's final value; leadStdDev is the
    # standard deviation of projectedLead; the three probabilities sum to 1.
    yourRange: list[float] | None = None
    opponentRange: list[float] | None = None
    leadStdDev: float | None = None
    winProbability: float | None = None
    tieProbability: float | None = None
    lossProbability: float | None = None


class RecordProbability(BaseModel):
    """One possible category record and how likely it is."""

    record: str  # "W-L-T"
    probability: float


class OutcomeRange(BaseModel):
    """How uncertain the matchup projection is: odds for the matchup and the spread behind
    the per-category ranges. Probabilities are estimates from a normal approximation."""

    confidenceLevel: float  # the ranges on each categoryProjection are this central interval
    # Sum of the category win / loss / tie probabilities: the record to expect on average
    expectedCategoryWins: float
    expectedCategoryLosses: float
    expectedCategoryTies: float
    # More category wins than losses. Categories are treated as independent, so these are
    # somewhat overconfident (see method)
    matchupWinProbability: float
    matchupTieProbability: float
    matchupLossProbability: float
    mostLikelyRecords: list[RecordProbability] = []  # the five most likely "W-L-T" records
    tossUpCategories: list[str] = []  # win probability between 35% and 65%
    # How many players' spreads came from their own game logs rather than league-typical values
    varianceSource: str | None = None
    method: str


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
    # gamesRemaining discounted by availability: the games this player is expected to PLAY,
    # whatever slot he is in. An OUT player with a reported return date inside the window
    # keeps the games on and after that date.
    expectedGames: float | None = None
    # The games the projection actually counted for him. Equal to expectedGames when his slot
    # scores; 0 for a bench player in a weekly-lock league, whose games never reach the score.
    gamesInProjection: float | None = None
    countsInProjection: bool = True
    availabilityNote: str | None = None  # why expectedGames or gamesInProjection is discounted
    priority: int  # Priority score (1-10, higher = more important to start)
    reasoning: str
    categoriesHelped: list[str]  # Close or losing categories this player helps in
    categoriesHurt: list[str] = []  # Close or losing categories this player hurts in
    closeCategoriesHelped: list[str] = []  # Subset of categoriesHelped that are close
    closeCategoriesHurt: list[str] = []  # Subset of categoriesHurt that are close
    injuryStatus: str | None = None
    injuryDetails: str | None = None
    todaysGame: TodaysGame | None = None
    # Per-game lines side by side (scoring categories only): the basis the projection used,
    # this season's actuals, and ESPN's projections. Compare players on one of these.
    basisPerGame: dict[str, float] | None = None
    seasonPerGame: dict[str, float] | None = None
    projectedPerGame: dict[str, float] | None = None
    # What he adds to the team's projected totals: basisPerGame x gamesInProjection for each
    # counting category plus made/attempted shots, so FG% and FT% effects can be checked
    projectedTotals: dict[str, float] | None = None
    seasonGamesPlayed: int | None = None


class OpponentPlayerSummary(BaseModel):
    """What the opponent's projection is built from, one line per rostered player."""

    playerId: int
    playerName: str
    lineupSlotName: str | None = None
    gamesRemaining: int = 0
    availability: str | None = None
    expectedGames: float = 0.0  # games he is expected to play (availability-discounted)
    gamesInProjection: float = 0.0  # games the projection counted (0 for a locked-out bench)
    countsInProjection: bool = True
    availabilityNote: str | None = None
    injuryStatus: str | None = None
    injuryDetails: str | None = None
    projectedPerGame: dict[str, float] | None = None  # scoring categories (+ made/attempted)
    basisPerGame: dict[str, float] | None = None  # the line the projection actually used
    seasonPerGame: dict[str, float] | None = None
    projectedTotals: dict[str, float] | None = None  # basisPerGame x gamesInProjection


class MatchupAnalysis(BaseModel):
    """Comprehensive analysis of the current matchup."""

    matchupId: int
    scoringPeriod: int
    yourTeamId: int
    opponentTeamId: int
    yourTeamName: str | None = None
    opponentTeamName: str | None = None
    yourTeamAbbrev: str | None = None
    opponentTeamAbbrev: str | None = None
    matchupPeriod: int | None = None

    # Which per-game numbers built the projection, for BOTH teams: projections (default),
    # season, last_7, last_15, last_30 or blend. basisNotes lists players who had no line on
    # that basis and fell back to projections. rosterSource says where the rosters came from.
    basis: str = "projections"
    basisDescription: str | None = None
    basisNotes: list[str] = []
    rosterSource: str | None = None
    # The league's lineup lock rule, which the lineup warnings are written for
    lineupLockRule: str | None = None
    lineupLockDescription: str | None = None

    # Category analysis
    categoryProjections: list[CategoryProjection]  # Projections for each category
    categoriesWinning: list[str]  # Categories you're projected to win
    categoriesLosing: list[str]  # Categories you're projected to lose
    categoriesTied: list[str]  # Categories projected to tie
    closeCategories: list[str]  # Categories that are close (within threshold)
    nearCategories: list[str] = []  # Just outside the threshold but still in play

    # Player recommendations
    playerRecommendations: list[PlayerRecommendation]  # Prioritized player recommendations

    # How the numbers were produced, so a reader can judge them
    projectionMethod: str | None = None

    # Additional context
    yourGamesRemaining: int | None = None  # Scheduled games not yet played, all rostered players
    opponentGamesRemaining: int | None = None
    # Games remaining discounted by availability (OUT, IR, FA...) and, in a weekly-lock
    # league, by slot: bench players' games never reach the score, so they are not counted.
    yourExpectedGames: float | None = None
    opponentExpectedGames: float | None = None
    # Why expected games are below games remaining: one line per discounted player
    expectedGamesBreakdown: list[str] = []
    opponentExpectedGamesBreakdown: list[str] = []
    # Weekly-lock leagues only: your bench players with games left that the projection does
    # not count ("Name: 3 playable game(s)"), so a swap can be weighed before the lock.
    benchPlayersNotCounted: list[str] = []
    # The projection re-run on the alternate basis (projections <-> season) and where the two
    # disagree, one line per category ("steals: projections say win (close, lead 1.2); season
    # says loss (clear, lead -3.4)"). An empty list with alternateBasis set means they agree.
    alternateBasis: str | None = None
    alternateProjectedRecord: str | None = None  # "W-L-T"
    basisDisagreements: list[str] = []
    # Range of outcomes: matchup win probability, expected category record and the method
    # behind the per-category ranges and win probabilities
    outcomeRange: OutcomeRange | None = None
    # The opponent's roster as the projection sees it
    opponentPlayers: list[OpponentPlayerSummary] = []
    currentCategoryWins: int | None = None  # Current category wins
    currentCategoryLosses: int | None = None  # Current category losses
    currentCategoryTies: int | None = None  # Current category ties
    projectedCategoryWins: int | None = None  # Projected category wins
    projectedCategoryLosses: int | None = None  # Projected category losses

    # Strategy recommendations
    strategyNotes: list[str]  # Strategic notes and recommendations
    lineupWarnings: list[str] = []  # Starters who cannot play (OUT, suspended, unsigned, on IR)


class CategoryDelta(BaseModel):
    """One category before and after a simulated roster move."""

    category: str
    before: float | None = None  # your projected total before the move
    after: float | None = None
    delta: float | None = None  # after - before (percentages as fractions)
    opponentProjected: float | None = None
    resultBefore: str | None = None  # win / loss / tie
    resultAfter: str | None = None
    closenessBefore: str | None = None  # close / near / clear
    closenessAfter: str | None = None
    changed: bool = False  # result or closeness changed
    winProbabilityBefore: float | None = None  # see CategoryProjection.winProbability
    winProbabilityAfter: float | None = None
    # Percentage categories only: your projected [made, attempted] before and after
    yourMadeAttemptedBefore: list[float] | None = None
    yourMadeAttemptedAfter: list[float] | None = None


class RosterLegality(BaseModel):
    """Whether a roster move is allowed under the league's roster rules."""

    teamId: int
    canMake: bool
    reasons: list[str] = []  # why not (empty when canMake)
    warnings: list[str] = []  # allowed, but worth knowing
    rosterSizeNow: int  # non-IR players
    rosterSizeAfter: int
    rosterLimit: int | None = None  # non-IR roster spots from league settings
    positionLimits: dict[str, int] = {}  # position -> max (-1 = no limit)
    positionCountsNowByDefaultPosition: dict[str, int] = {}  # current non-IR roster
    positionCountsNowByEligibility: dict[str, int] = {}
    positionCountsAfterByDefaultPosition: dict[str, int] = {}
    positionCountsAfterByEligibility: dict[str, int] = {}
    # "primary" (default) or "eligibility": which count decides the verdict. Set with the
    # ESPN_POSITION_LIMIT_BASIS environment variable once ESPN has shown which it enforces.
    positionLimitBasisSetting: str = "primary"
    positionLimitBasis: str | None = None  # which count the verdict used, and why
    # What this league's own roster says about the rule, e.g. the current roster already
    # exceeds a limit by eligibility and ESPN accepted it.
    positionLimitEvidence: list[str] = []
    # Which roster the counts come from: the roster for the scoring period an add made now
    # takes effect (status.transactionScoringPeriod), which includes pending adds
    rosterScoringPeriod: int | None = None
    rosterNote: str | None = None
    acquisitionsRemainingThisMatchup: int | None = None
    addedPlayerStatus: dict[str, str] = {}  # "Name (id)" -> FREEAGENT / WAIVERS ... / ONTEAM ...


class RosterMoveSimulation(BaseModel):
    """analyze_matchup run twice, before and after hypothetical drops/adds, on one basis."""

    teamId: int
    matchupPeriod: int
    basis: str
    dropped: list[str]  # "Name (id)"
    added: list[str]
    unknownDropIds: list[int] = []
    unknownAddIds: list[int] = []
    # Which slot each added player was given: a dropped starter's slot when it can still be
    # filled, else the bench (which does not score under a weekly lock)
    placements: list[str] = []
    # Lineup changes simulated: who moved into a starting slot, who went to the bench, and
    # anything that could not be done as asked (ineligible slot, no open slot, locked slot)
    started: list[str] = []
    benched: list[str] = []
    lineupChanges: list[str] = []
    lineupWarnings: list[str] = []
    # "What if he does not play": players simulated as missing all or some of their games
    absences: list[str] = []
    gamesRemainingBefore: int | None = None
    gamesRemainingAfter: int | None = None
    expectedGamesBefore: float | None = None
    expectedGamesAfter: float | None = None
    projectedRecordBefore: str  # "W-L-T"
    projectedRecordAfter: str
    # Range of outcomes before and after (see MatchupAnalysis.outcomeRange): a move that
    # leaves the projected record unchanged can still shift the odds
    matchupWinProbabilityBefore: float | None = None
    matchupWinProbabilityAfter: float | None = None
    expectedCategoryWinsBefore: float | None = None
    expectedCategoryWinsAfter: float | None = None
    categoryDeltas: list[CategoryDelta]
    categoriesFlipped: list[str] = []  # "rebounds: loss -> win"
    addedPlayers: list[PlayerRecommendation] = []  # how the added players project
    legality: RosterLegality | None = None
    summary: list[str]
    projectionMethod: str | None = None


class LineupOption(BaseModel):
    """One candidate lineup from optimize_lineup."""

    rank: int
    projectedRecord: str  # "W-L-T"
    projectedCategoryWins: int
    projectedCategoryLosses: int
    projectedCategoryTies: int
    score: float  # wins, then ties, then clipped margins: see LineupOptimization.scoring
    # Range of outcomes for this lineup (not used for ranking): see MatchupAnalysis.outcomeRange
    matchupWinProbability: float | None = None
    expectedCategoryWins: float | None = None
    categoriesWon: list[str] = []
    categoriesLost: list[str] = []
    closeCategories: list[str] = []
    expectedGames: float
    lineup: dict[str, str] = {}  # "PG" -> "Player name", one key per starting slot (UTIL1..)
    bench: list[str] = []
    changes: list[str] = []  # vs the current lineup: "start X (3 games) for Y (1 game)"
    isCurrent: bool = False


class LineupOptimization(BaseModel):
    """Every valid starting lineup evaluated with the matchup projection, best first."""

    teamId: int
    matchupPeriod: int
    basis: str
    lineupLockRule: str | None = None
    currentProjectedRecord: str
    currentLineup: dict[str, str] = {}
    currentIsBest: bool
    options: list[LineupOption] = []
    lineupsEvaluated: int
    fixedPlayers: list[str] = []  # locked in (or out of) the lineup for this period
    scoring: str
    searchNote: str | None = None
    notes: list[str] = []
    projectionMethod: str | None = None


class PlayerSearchResult(BaseModel):
    """A player matched by name, with their status in this league when known."""

    playerId: int
    fullName: str
    matchScore: float  # 1.0 = exact name match
    defaultPosition: str | None = None
    proTeamAbbrev: str | None = None  # "FA" if not on an NBA roster
    injuryStatus: str | None = None
    injuryDetails: str | None = None  # Reason / timeline when ESPN publishes one
    isFreeAgent: bool | None = None  # True if no fantasy team owns the player (None if unknown)
    availabilityStatus: str | None = None  # FREEAGENT (addable now), WAIVERS, ONTEAM
    waiverProcessDateISO: str | None = None  # When waiver claims for this player process
    availabilityNote: str | None = None  # e.g. "On waivers; claims process 2026-11-03T08:00-05:00"
    fantasyTeamId: int | None = None
    fantasyTeamName: str | None = None
    percentOwned: float | None = None


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
    # Human-readable reason/timeline behind injuryStatus when ESPN publishes one, e.g.
    # "Knee - Sprain (left); expected return 2026-11-10. Williams (knee) is out Tuesday."
    injuryDetails: str | None = None
    injuryReturnDate: str | None = None  # YYYY-MM-DD when ESPN lists an expected return
    # "reported": ESPN's note gives a timeline (weeks, re-evaluation, surgery, season).
    # "placeholder": ESPN lists the team's next game for a day-to-day player, which says
    # nothing about how long he is actually out. None when there is no return date.
    injuryReturnDateType: str | None = None
    injuryReturnDateNote: str | None = None
    # Set when injuryStatus (ESPN fantasy's code) and injuryDetails (ESPN's NBA injury report)
    # disagree, e.g. fantasy says OUT while the report says probable. Says which is which.
    injuryStatusNote: str | None = None
    # Free-agent pool state (kona_player_info): FREEAGENT = can be added now, WAIVERS = claims
    # process at waiverProcessDateISO (ESPN's "WA (Tue)" flag), ONTEAM = rostered.
    availabilityStatus: str | None = None
    waiverProcessDateISO: str | None = None
    availabilityNote: str | None = None
    stats: dict[str, Any] | None = None  # this season's per-game actuals (+ totals)
    projections: dict[str, Any] | None = None  # ESPN's rest-of-season per-game projections
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
    """A player's game on the roster's scoring-period date (today by default)."""

    date: str | None = None  # YYYY-MM-DD of the game, in MY_TIMEZONE
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
    lineupLocked: bool | None = None  # This slot is locked for the roster's scoring period


class PendingAdd(BaseModel):
    """A player ESPN lists on this team's roster for a later scoring period but not today's:
    an add made after today's games started, which ESPN applies from
    status.transactionScoringPeriod. He cannot score before that day."""

    playerId: int
    playerName: str
    effectiveScoringPeriod: int | None = None
    effectiveDate: str | None = None  # YYYY-MM-DD
    lineupSlotName: str | None = None


class Roster(BaseModel):
    teamId: int
    entries: list[RosterEntry]
    # Players present only on a later day's roster (see PendingAdd); included in `entries`
    pendingAdds: list[PendingAdd] | None = None
    # Players on today's roster that a later day's roster does not list (ESPN's future roster
    # can lag an add made today); kept in `entries` and named here so the reader can check
    missingFromLaterRoster: list[str] | None = None
    # Which day this roster is for. ESPN's scoring periods are days (1 = opening night); the
    # default is today's. requestedScoringPeriod is what the caller asked for (None = today),
    # espnScoringPeriodId is what ESPN echoed back, so a mismatch is visible.
    scoringPeriodId: int | None = None
    scoringPeriodDate: str | None = None  # YYYY-MM-DD when it can be determined
    requestedScoringPeriod: int | None = None
    espnScoringPeriodId: int | None = None
    # The date every entry's todaysGame refers to: the roster's scoring-period date, so a
    # roster requested for Wednesday carries Wednesday's games, not today's.
    gamesDate: str | None = None
    # The league's lineup lock rule: INDIVIDUAL_GAME (daily changes; a locked slot frees up the
    # next day) or FIRSTGAME_WEEKLY (every slot locks at the week's first game and stays locked).
    # `note` is written for the rule in force.
    lineupLockRule: str | None = None
    lineupLockDescription: str | None = None
    lineupLocked: bool | None = None  # True if every non-bench, non-IR slot is locked
    lockedSlots: list[str] | None = None  # "SLOT: player" for starting slots already locked
    unlockedSlots: list[str] | None = None  # "SLOT: player" for starting slots still editable
    note: str | None = None
    # Players ESPN listed under this team whose playerPoolEntry.onTeamId says they now belong to
    # another team or the free-agent pool (a dropped player whose lineup slot was locked). They
    # are removed from `entries` so projections never count them.
    staleEntriesRemoved: list[str] | None = None


class MatchupTeam(BaseModel):
    teamId: int | None = None
    teamName: str | None = None  # Fantasy team name (e.g., "John's Squad")
    teamAbbrev: str | None = None  # Stable even when an owner renames the team mid-week
    totalPoints: float | None = None
    totalProjectedPoints: float | None = None
    gamesPlayed: int | None = None
    # ESPN's raw cumulativeScore (stat IDs). Kept on the model for the percentage math in
    # analyze_matchup; the tools leave it out of their output because categoryScores,
    # componentStats and categoryWins/Losses/Ties carry everything in it.
    cumulativeScore: dict[str, Any] | None = None
    categoryWins: int | None = None  # Categories this side leads in this matchup so far
    categoryLosses: int | None = None
    categoryTies: int | None = None
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
    rosterNote: str | None = None  # Where the rosters came from (today's, planned, historical)
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
    includedInTotals: bool = True  # False for extras (player_ids), unsigned or failed lookups
    note: str | None = None  # e.g. "Not on an NBA roster; cannot play"


class RosterScheduleSummary(BaseModel):
    """Schedule summary for a fantasy roster, or for an arbitrary list of players."""

    teamId: int | None = None  # None when built from player IDs rather than a roster
    scoringPeriod: int  # The matchup period "this week" refers to (0 if unknown)
    thisWeek: list[str] | None = None  # [first_day, last_day] counted as gamesThisWeek
    nextWeek: list[str] | None = None  # [first_day, last_day] counted as gamesNextWeek
    playerSchedules: list[PlayerSchedule]
    # Totals and the average cover players with includedInTotals=True: rostered players who can
    # play. Extras passed via player_ids and unsigned players are listed but excluded.
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
    matchupPeriodsNote: str = (
        "matchupPeriods maps each matchup period to the week number(s) it covers; it is NOT a "
        "list of scoring periods (days). Use matchupPeriodDates for calendar dates. "
        "status.latestScoringPeriod is a daily counter where 1 is opening night."
    )
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
    lineupLocktimeType: str  # When lineups lock (ESPN's code)
    lineupLocktimeDescription: str | None = None  # The code in plain English, when known
    rosterSize: int | None = None  # Total roster spots excluding IR (sum of lineupSlotCounts)
    rosterLocktimeType: str | None = None
    isBenchUnlimited: bool = False
    moveLimit: int = -1  # -1 = unlimited


class AcquisitionSettings(BaseModel):
    """League acquisition/waiver configuration."""

    acquisitionType: str  # "WAIVERS_TRADITIONAL", "FREE_AGENT", etc.
    waiverHours: int
    waiverProcessDays: list[str]  # Days waivers process (e.g., ["SUNDAY"])
    # Hour (0-23) waivers process, in UTC: a league with waiverProcessHour 8 had every player's
    # waiverProcessDate at 08:00Z (recorded live). Per-player waiverProcessDateISO on free
    # agents is the authoritative time.
    waiverProcessHour: int
    waiverProcessHourTimezone: str = "UTC"
    waiverProcessTimeLocal: str | None = (
        None  # Same time in MY_TIMEZONE, e.g. "02:00 America/Chicago"
    )
    matchupAcquisitionLimit: float  # Max acquisitions per matchup (or per day, see below)
    matchupLimitPerScoringPeriod: bool  # True: the limit above applies per day, not per matchup
    acquisitionLimit: int = -1  # Season limit (-1 = unlimited)
    acquisitionLimitDescription: str | None = None  # e.g. "1 per day, so 7 for matchup period 2"
    # Adds allowed per matchup period after applying a per-day limit to the period's length
    # (a 6-day opening week allows 6, a 7-day week 7). None = no limit.
    effectiveLimitByMatchupPeriod: dict[str, int] | None = None
    effectiveLimitCurrentMatchup: int | None = None
    waiverOrderReset: bool | None = None  # ESPN's raw flag
    waiverOrderDescription: str | None = None  # What happens to your waiver rank after a claim
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
    currentMatchupPeriodDates: list[str] | None = None  # [first_day, last_day]
    latestScoringPeriodDate: str | None = None  # Calendar day latestScoringPeriod refers to
    # The scoring period a transaction made now is charged to, its date, the matchup period
    # that contains it, and a sentence saying so ("Adds made now count against matchup
    # period 3 (2026-11-02 to 2026-11-08)").
    transactionScoringPeriodDate: str | None = None
    transactionMatchupPeriod: int | None = None
    transactionNote: str | None = None


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


class TransactionItem(BaseModel):
    """One player movement inside a transaction."""

    playerId: int | None = None
    playerName: str | None = None
    type: str | None = None  # ADD, DROP, LINEUP, ...
    fromTeamId: int | None = None  # 0 = free-agent pool
    toTeamId: int | None = None


class Transaction(BaseModel):
    """A league transaction (mTransactions2 view): add/drop, waiver claim, trade, lineup move."""

    id: str | None = None
    type: str | None = None  # FREEAGENT, WAIVER, TRADE_ACCEPT, ROSTER, DRAFT, ...
    status: str | None = None  # EXECUTED, PENDING, FAILED_*, ...
    teamId: int | None = None
    teamName: str | None = None
    scoringPeriodId: int | None = None
    proposedDateISO: str | None = None
    processDateISO: str | None = None
    bidAmount: int | None = None
    items: list[TransactionItem] = []
    summary: str  # e.g. "Fifth Team dropped Zed Streamer (free-agent move, 2026-11-01)"

"""Data models for ESPN Fantasy Basketball API responses."""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class Owner(BaseModel):
    firstName: str
    lastName: str
    displayName: Optional[str] = None


class OverallRecord(BaseModel):
    wins: int
    losses: int
    percentage: Optional[float] = None


class TeamRecord(BaseModel):
    overall: Optional[OverallRecord] = None


class Team(BaseModel):
    id: int
    abbrev: str
    name: str
    location: Optional[str] = None  # Make location optional since ESPN doesn't always provide it
    logo: Optional[str] = None
    owners: Optional[List[str]] = None  # ESPN returns owner IDs as strings
    record: Optional[TeamRecord] = None


class PlayerOwnership(BaseModel):
    percentOwned: Optional[float] = None
    percentChange: Optional[float] = None
    percentStarted: Optional[float] = None


class Player(BaseModel):
    id: int
    fullName: str
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    jersey: Optional[str] = None
    proTeamId: Optional[int] = None
    defaultPositionId: int
    eligibleSlots: Optional[List[int]] = None
    injured: Optional[bool] = None
    injuryStatus: Optional[str] = None
    stats: Optional[Dict[str, Any]] = None
    ownership: Optional[PlayerOwnership] = None
    active: Optional[bool] = None
    droppable: Optional[bool] = None


class PlayerPoolEntry(BaseModel):
    id: int
    player: Player
    onTeamId: Optional[int] = None
    keeperValue: Optional[int] = None
    keeperValueFuture: Optional[int] = None
    lineupLocked: Optional[bool] = None


class RosterEntry(BaseModel):
    playerId: int
    playerPoolEntry: PlayerPoolEntry
    lineupSlotId: int
    acquisitionDate: Optional[int] = None
    acquisitionType: Optional[str] = None
    injuryStatus: Optional[str] = None


class Roster(BaseModel):
    teamId: int
    entries: List[RosterEntry]


class MatchupTeam(BaseModel):
    teamId: Optional[int] = None
    totalPoints: Optional[float] = None
    totalProjectedPoints: Optional[float] = None
    gamesPlayed: Optional[int] = None
    cumulativeScore: Optional[Dict[str, Any]] = None


class Matchup(BaseModel):
    id: int
    matchupPeriodId: int
    home: Optional[MatchupTeam] = None
    away: Optional[MatchupTeam] = None
    winner: Optional[str] = None
    playoff: Optional[bool] = None


class NBATeam(BaseModel):
    id: str
    displayName: str
    abbreviation: str


class NBACompetitor(BaseModel):
    team: NBATeam


class NBACompetition(BaseModel):
    competitors: List[NBACompetitor]


class NBAGame(BaseModel):
    id: str
    date: str
    competitions: List[NBACompetition]


# Draft-related models
class DraftPick(BaseModel):
    id: int
    playerId: int
    teamId: int
    bidAmount: int
    overallPickNumber: int
    roundId: int
    roundPickNumber: int
    nominatingTeamId: Optional[int] = None
    memberId: Optional[str] = None
    lineupSlotId: Optional[int] = None
    keeper: bool = False


class DraftStatus(BaseModel):
    inProgress: bool
    drafted: bool
    completeDate: Optional[int] = None
    picks: List[DraftPick]
    currentPickNumber: Optional[int] = None
    currentNominatingTeam: Optional[int] = None


class PlayerDraftInfo(BaseModel):
    playerId: int
    player: Player
    draftAuctionValue: Optional[int] = None
    auctionValue: Optional[int] = None  # ESPN's projected value
    rank: Optional[int] = None
    isDrafted: bool = False
    draftedByTeam: Optional[int] = None
    bidAmount: Optional[int] = None


class TeamDraftSummary(BaseModel):
    teamId: int
    teamName: str
    totalSpent: int
    playersCount: int
    remainingBudget: int
    positionCounts: Dict[str, int] = {}
    categories: Dict[str, float] = {}  # Projected category totals


class DraftRecommendation(BaseModel):
    action: str  # "bid", "pass", "nominate"
    playerId: Optional[int] = None
    playerName: Optional[str] = None
    suggestedBid: Optional[int] = None
    maxBid: Optional[int] = None
    reasoning: str
    priority: int  # 1-10, 10 being highest
    category_impact: Dict[str, str] = {}  # How this player affects your categories
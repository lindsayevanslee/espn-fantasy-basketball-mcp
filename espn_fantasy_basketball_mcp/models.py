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
    location: str
    logo: Optional[str] = None
    owners: Optional[List[Owner]] = None
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


class PlayerPoolEntry(BaseModel):
    player: Player


class RosterEntry(BaseModel):
    playerId: int
    playerPoolEntry: PlayerPoolEntry
    lineupSlotId: int


class Roster(BaseModel):
    teamId: int
    entries: List[RosterEntry]


class MatchupTeam(BaseModel):
    teamId: int
    totalPoints: Optional[float] = None
    totalProjectedPoints: Optional[float] = None


class Matchup(BaseModel):
    id: int
    matchupPeriodId: int
    home: MatchupTeam
    away: MatchupTeam


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
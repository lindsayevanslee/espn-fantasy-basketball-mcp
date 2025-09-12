"""ESPN Fantasy Basketball API client."""

import httpx
from typing import List, Dict, Any, Optional
from .models import Team, Player, Roster, Matchup, NBAGame, PlayerPoolEntry, RosterEntry, MatchupTeam


class ESPNFantasyBasketballClient:
    """Client for ESPN Fantasy Basketball API."""
    
    BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba"
    NBA_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
    
    def __init__(self, league_id: int, year: int, espn_s2: Optional[str] = None, swid: Optional[str] = None):
        """Initialize the client.
        
        Args:
            league_id: ESPN Fantasy Basketball league ID
            year: Season year
            espn_s2: ESPN authentication cookie (for private leagues)
            swid: ESPN SWID cookie (for private leagues)
        """
        self.league_id = league_id
        self.year = year
        self.cookies = {}
        
        if espn_s2:
            self.cookies["espn_s2"] = espn_s2
        if swid:
            self.cookies["SWID"] = swid
    
    async def _make_request(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make HTTP request to ESPN API."""
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, cookies=self.cookies)
            response.raise_for_status()
            return response.json()
    
    async def get_league_teams(self) -> List[Team]:
        """Get all teams in the league."""
        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        params = {"view": "mTeam"}
        
        data = await self._make_request(url, params)
        teams = []
        
        for team_data in data.get("teams", []):
            team = Team(
                id=team_data["id"],
                abbrev=team_data.get("abbrev", ""),
                name=team_data.get("name", ""),
                location=team_data.get("location"),  # Keep as None if not present
                logo=team_data.get("logo"),
                owners=team_data.get("owners"),  # ESPN provides owner IDs as strings
                record=team_data.get("record")
            )
            teams.append(team)
        
        return teams
    
    async def get_team_roster(self, team_id: int, scoring_period: Optional[int] = None) -> Roster:
        """Get roster for a specific team."""
        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        params = {"view": "mRoster"}
        
        if scoring_period:
            params["scoringPeriodId"] = scoring_period
        
        data = await self._make_request(url, params)
        
        for team_data in data.get("teams", []):
            if team_data["id"] == team_id:
                roster_entries = []
                for entry in team_data.get("roster", {}).get("entries", []):
                    # Build player data from the nested structure
                    player_data = entry["playerPoolEntry"]["player"]
                    player = Player(
                        id=player_data["id"],
                        fullName=player_data.get("fullName", ""),
                        firstName=player_data.get("firstName", ""),
                        lastName=player_data.get("lastName", ""),
                        jersey=player_data.get("jersey"),
                        proTeamId=player_data.get("proTeamId"),
                        defaultPositionId=player_data["defaultPositionId"],
                        eligibleSlots=player_data.get("eligibleSlots"),
                        injured=player_data.get("injured"),
                        injuryStatus=entry.get("injuryStatus"),
                        active=player_data.get("active"),
                        droppable=player_data.get("droppable")
                    )
                    
                    player_pool_entry = PlayerPoolEntry(
                        id=entry["playerPoolEntry"]["id"],
                        player=player,
                        onTeamId=entry["playerPoolEntry"].get("onTeamId"),
                        keeperValue=entry["playerPoolEntry"].get("keeperValue"),
                        keeperValueFuture=entry["playerPoolEntry"].get("keeperValueFuture"),
                        lineupLocked=entry["playerPoolEntry"].get("lineupLocked")
                    )
                    
                    roster_entry = RosterEntry(
                        playerId=entry["playerId"],
                        playerPoolEntry=player_pool_entry,
                        lineupSlotId=entry["lineupSlotId"],
                        acquisitionDate=entry.get("acquisitionDate"),
                        acquisitionType=entry.get("acquisitionType"),
                        injuryStatus=entry.get("injuryStatus")
                    )
                    
                    roster_entries.append(roster_entry)
                
                return Roster(teamId=team_id, entries=roster_entries)
        
        raise ValueError(f"Team {team_id} not found")
    
    async def get_free_agents(self, size: int = 50, position_id: Optional[int] = None) -> List[Player]:
        """Get free agents/waiver wire players.
        
        Args:
            size: Number of players to return (max 50)
            position_id: Filter by position ID (optional)
        """
        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        filter_json = f'{{"players":{{"limit":{size},"sortPercOwned":{{"sortAsc":false,"sortPriority":1}}}}}}'
        params = {
            "view": "kona_player_info",
            "X-Fantasy-Filter": filter_json
        }
        
        if position_id:
            filter_dict = {
                "players": {
                    "limit": size,
                    "sortPercOwned": {"sortAsc": False, "sortPriority": 1},
                    "filterSlotIds": {"value": [position_id]}
                }
            }
            params["X-Fantasy-Filter"] = str(filter_dict).replace("'", '"')
        
        data = await self._make_request(url, params)
        
        players = []
        for player_data in data.get("players", []):
            if player_data.get("onTeamId") is None:  # Free agent
                player_info = player_data["player"]
                player = Player(
                    id=player_info["id"],
                    fullName=player_info["fullName"],
                    firstName=player_info.get("firstName"),
                    lastName=player_info.get("lastName"),
                    jersey=player_info.get("jersey"),
                    proTeamId=player_info.get("proTeamId"),
                    defaultPositionId=player_info["defaultPositionId"],
                    eligibleSlots=player_info.get("eligibleSlots"),
                    injured=player_info.get("injured", False),
                    injuryStatus=player_info.get("injuryStatus"),
                    ownership=player_data.get("ownership")
                )
                players.append(player)
        
        return players
    
    async def get_matchups(self, scoring_period: Optional[int] = None) -> List[Matchup]:
        """Get matchups for the league."""
        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        params = {"view": "mMatchup"}
        
        if scoring_period:
            params["scoringPeriodId"] = scoring_period
        
        data = await self._make_request(url, params)
        
        matchups = []
        for schedule_item in data.get("schedule", []):
            if scoring_period is None or schedule_item.get("matchupPeriodId") == scoring_period:
                # Extract team info from home/away data
                home_team = None
                if schedule_item.get("home"):
                    home_data = schedule_item["home"]
                    home_team = MatchupTeam(
                        teamId=home_data.get("teamId"),
                        totalPoints=home_data.get("totalPoints"),
                        totalProjectedPoints=home_data.get("totalProjectedPoints"),
                        gamesPlayed=home_data.get("gamesPlayed"),
                        cumulativeScore=home_data.get("cumulativeScore")
                    )
                
                away_team = None
                if schedule_item.get("away"):
                    away_data = schedule_item["away"]
                    away_team = MatchupTeam(
                        teamId=away_data.get("teamId"),
                        totalPoints=away_data.get("totalPoints"),
                        totalProjectedPoints=away_data.get("totalProjectedPoints"),
                        gamesPlayed=away_data.get("gamesPlayed"),
                        cumulativeScore=away_data.get("cumulativeScore")
                    )
                
                matchup = Matchup(
                    id=schedule_item["id"],
                    matchupPeriodId=schedule_item["matchupPeriodId"],
                    home=home_team,
                    away=away_team,
                    winner=schedule_item.get("winner"),
                    playoff=schedule_item.get("playoff")
                )
                matchups.append(matchup)
        
        return matchups
    
    async def get_nba_schedule(self, date: Optional[str] = None) -> List[NBAGame]:
        """Get NBA schedule.
        
        Args:
            date: Date in YYYY-MM-DD format (optional, defaults to today)
        """
        url = f"{self.NBA_BASE_URL}/scoreboard"
        params = {}
        
        if date:
            params["dates"] = date
        
        try:
            data = await self._make_request(url, params)
            
            games = []
            for event in data.get("events", []):
                game = NBAGame(
                    id=event["id"],
                    date=event["date"],
                    competitions=event["competitions"]
                )
                games.append(game)
            
            return games
        except Exception:
            # If NBA API fails, return empty list
            return []
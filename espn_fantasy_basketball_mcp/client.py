"""ESPN Fantasy Basketball API client."""

import logging
from typing import Any

import httpx

from .models import (
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
    PlayerSchedule,
    PlayerScheduleGame,
    PlayerStats,
    Roster,
    RosterEntry,
    RosterScheduleSummary,
    Team,
    TeamDraftSummary,
    TradeAnalysis,
    TrendingPlayer,
)

logger = logging.getLogger(__name__)


class ESPNFantasyBasketballClient:
    """Client for ESPN Fantasy Basketball API."""

    BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba"
    NBA_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"

    def __init__(
        self, league_id: int, year: int, espn_s2: str | None = None, swid: str | None = None
    ):
        """Initialize the client.

        Args:
            league_id: ESPN Fantasy Basketball league ID
            year: Season year
            espn_s2: ESPN authentication cookie (for private leagues)
            swid: ESPN SWID cookie (for private leagues)

        Raises:
            ValueError: If league_id or year is invalid
        """
        # Validate league_id
        if not isinstance(league_id, int) or league_id <= 0:
            raise ValueError(f"Invalid league_id: {league_id}. Must be a positive integer.")

        # Validate year
        if not isinstance(year, int) or year < 2000 or year > 2100:
            raise ValueError(f"Invalid year: {year}. Must be between 2000 and 2100.")

        self.league_id = league_id
        self.year = year
        self.cookies = {}

        if espn_s2:
            self.cookies["espn_s2"] = espn_s2
        if swid:
            self.cookies["SWID"] = swid

    @staticmethod
    def _validate_positive_int(value: int | None, name: str) -> None:
        """Validate that a value is a positive integer.

        Args:
            value: Value to validate
            name: Parameter name for error message

        Raises:
            ValueError: If value is not a positive integer
        """
        if value is not None and (not isinstance(value, int) or value <= 0):
            raise ValueError(f"Invalid {name}: {value}. Must be a positive integer.")

    async def _make_request(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        """Make HTTP request to ESPN API.

        Args:
            url: Full URL to request
            params: Query parameters
            headers: HTTP headers

        Returns:
            JSON response data

        Raises:
            ValueError: If URL is not HTTPS
            httpx.HTTPError: For HTTP-related errors
        """
        # Enforce HTTPS
        if not url.startswith("https://"):
            raise ValueError(f"Only HTTPS URLs are allowed. Got: {url}")

        try:
            # Set a reasonable timeout (30 seconds)
            timeout = httpx.Timeout(30.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                logger.debug(f"Making request to {url}")
                response = await client.get(url, params=params, headers=headers, cookies=self.cookies)
                response.raise_for_status()
                return response.json()  # type: ignore[no-any-return]
        except httpx.TimeoutException as e:
            logger.error(f"Request timeout for {url}: {e}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code} for {url}: {e}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error for {url}: {e}")
            raise

    async def get_league_teams(self) -> list[Team]:
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
                record=team_data.get("record"),
            )
            teams.append(team)

        return teams

    async def get_team_roster(self, team_id: int, scoring_period: int | None = None) -> Roster:
        """Get roster for a specific team with player stats included.

        Args:
            team_id: Team ID to get roster for
            scoring_period: Specific scoring period (optional)

        Returns:
            Roster object with team roster data

        Raises:
            ValueError: If team_id or scoring_period is invalid, or team not found
        """
        # Validate inputs
        self._validate_positive_int(team_id, "team_id")
        self._validate_positive_int(scoring_period, "scoring_period")

        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        
        # Build filter to include stats for rostered players
        filter_dict = {
            "players": {
                "filterStatsForTopScoringPeriodIds": {
                    "value": 5,
                    "additionalValue": [
                        f"00{self.year}",   # Current season actuals
                        f"10{self.year}",   # Projections
                    ]
                }
            }
        }
        
        import json
        headers = {"x-fantasy-filter": json.dumps(filter_dict)}
        params = {"view": ["mRoster", "mTeam"]}

        if scoring_period:
            params["scoringPeriodId"] = str(scoring_period)

        data = await self._make_request(url, params, headers)

        for team_data in data.get("teams", []):
            if team_data["id"] == team_id:
                roster_entries = []
                for entry in team_data.get("roster", {}).get("entries", []):
                    # Build player data from the nested structure
                    player_data = entry["playerPoolEntry"]["player"]
                    
                    # Get injury status - check multiple locations
                    # ESPN may return various status values: "ACTIVE", "NORMAL", "DTD", "DAY_TO_DAY", 
                    # "QUESTIONABLE", "OUT", "FUTURE_TO_IR", etc.
                    # IMPORTANT: Player-level injuryStatus is more accurate than entry-level
                    # Entry-level often shows "NORMAL" even when player-level shows "DAY_TO_DAY"
                    # So we prioritize player-level status first
                    injury_status = (
                        player_data.get("injuryStatus")
                        or entry.get("playerPoolEntry", {}).get("player", {}).get("injuryStatus")
                        or entry.get("injuryStatus")  # Fall back to entry level if player level not available
                    )
                    # ESPN might return null/empty for DTD players - check if there's an injury object
                    if not injury_status:
                        injury_info = player_data.get("injury") or entry.get("injury")
                        if injury_info:
                            # ESPN might have injury details in an object
                            injury_status = injury_info.get("status") or injury_info.get("injuryStatus")
                    # If still no status, preserve None rather than defaulting (let the model handle it)
                    # This way we don't mask DTD players that ESPN marks differently
                    
                    # Parse player stats
                    stats_data = self._parse_player_stats(player_data.get("stats", []))
                    
                    player = Player(
                        id=player_data["id"],
                        fullName=player_data.get("fullName", ""),
                        firstName=player_data.get("firstName", ""),
                        lastName=player_data.get("lastName", ""),
                        jersey=player_data.get("jersey"),
                        proTeamId=player_data.get("proTeamId"),
                        defaultPositionId=player_data["defaultPositionId"],
                        eligibleSlots=player_data.get("eligibleSlots"),
                        injured=player_data.get("injured", False),
                        injuryStatus=injury_status,
                        active=player_data.get("active"),
                        droppable=player_data.get("droppable"),
                        stats=stats_data,
                    )

                    player_pool_entry = PlayerPoolEntry(
                        id=entry["playerPoolEntry"]["id"],
                        player=player,
                        onTeamId=entry["playerPoolEntry"].get("onTeamId"),
                        keeperValue=entry["playerPoolEntry"].get("keeperValue"),
                        keeperValueFuture=entry["playerPoolEntry"].get("keeperValueFuture"),
                        lineupLocked=entry["playerPoolEntry"].get("lineupLocked"),
                    )

                    roster_entry = RosterEntry(
                        playerId=entry["playerId"],
                        playerPoolEntry=player_pool_entry,
                        lineupSlotId=entry["lineupSlotId"],
                        acquisitionDate=entry.get("acquisitionDate"),
                        acquisitionType=entry.get("acquisitionType"),
                        injuryStatus=injury_status,
                    )

                    roster_entries.append(roster_entry)

                return Roster(teamId=team_id, entries=roster_entries)

        # Log the detailed error but return generic message
        logger.warning(f"Team with ID {team_id} not found in league {self.league_id}")
        raise ValueError("Team not found in this league")

    def _parse_player_stats(self, stats_list: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Parse ESPN stats array into a clean stats dictionary."""
        if not stats_list:
            return None
        
        stats_data = {}
        
        # Look for current season stats first (00YYYY format)
        current_season_id = f"00{self.year}"
        
        for stat_set in stats_list:
            stat_id = str(stat_set.get("id", ""))
            
            # "00YYYY" = season actuals (what we want primarily)
            # "10YYYY" = projections
            # "01YYYY" = last 7 days
            # "02YYYY" = last 15 days
            # "03YYYY" = last 30 days
            # Prioritize current season (2026) over previous seasons
            if stat_id == current_season_id:
                averages = stat_set.get("averages", {})
                totals = stat_set.get("stats", {})
                
                # ESPN stat ID mapping for basketball:
                # 0=PTS, 1=BLK, 2=STL, 3=AST, 6=REB, 11=TO, 17=3PM, 19=FG%, 20=FT%, 40=MIN, 42=GP
                
                # Calculate per-game averages if we have totals but not averages
                games_played = totals.get("42", 0)
                
                if averages:
                    stats_data = {
                        "gamesPlayed": int(games_played) if games_played else 0,
                        "minutes": round(averages.get("40", 0), 1),
                        "points": round(averages.get("0", 0), 1),
                        "rebounds": round(averages.get("6", 0), 1),
                        "assists": round(averages.get("3", 0), 1),
                        "steals": round(averages.get("2", 0), 1),
                        "blocks": round(averages.get("1", 0), 1),
                        "threes": round(averages.get("17", 0), 1),
                        "turnovers": round(averages.get("11", 0), 1),
                        "fg_pct": round(averages.get("19", 0) * 100, 1) if averages.get("19") else None,
                        "ft_pct": round(averages.get("20", 0) * 100, 1) if averages.get("20") else None,
                    }
                elif totals and games_played > 0:
                    # Calculate averages from totals
                    gp = games_played
                    stats_data = {
                        "gamesPlayed": int(gp),
                        "minutes": round(totals.get("40", 0) / gp, 1),
                        "points": round(totals.get("0", 0) / gp, 1),
                        "rebounds": round(totals.get("6", 0) / gp, 1),
                        "assists": round(totals.get("3", 0) / gp, 1),
                        "steals": round(totals.get("2", 0) / gp, 1),
                        "blocks": round(totals.get("1", 0) / gp, 1),
                        "threes": round(totals.get("17", 0) / gp, 1),
                        "turnovers": round(totals.get("11", 0) / gp, 1),
                        "fg_pct": round(totals.get("19", 0) * 100, 1) if totals.get("19") else None,
                        "ft_pct": round(totals.get("20", 0) * 100, 1) if totals.get("20") else None,
                    }
                
                # Add season totals as well (useful for category leagues)
                if totals:
                    stats_data["totals"] = {
                        "points": int(totals.get("0", 0)),
                        "rebounds": int(totals.get("6", 0)),
                        "assists": int(totals.get("3", 0)),
                        "steals": int(totals.get("2", 0)),
                        "blocks": int(totals.get("1", 0)),
                        "threes": int(totals.get("17", 0)),
                        "turnovers": int(totals.get("11", 0)),
                    }
                
                # Add fantasy points average if available
                if "appliedAverage" in stat_set:
                    stats_data["fantasyAvg"] = round(stat_set["appliedAverage"], 1)
                if "appliedTotal" in stat_set:
                    stats_data["fantasyTotal"] = round(stat_set["appliedTotal"], 1)
                    
                break  # Found season stats, stop looking
        
        return stats_data if stats_data else None

    async def get_free_agents(self, size: int = 50, position_id: int | None = None) -> list[Player]:
        """Get free agents/waiver wire players.

        Args:
            size: Number of players to return (max 50)
            position_id: Filter by position ID (optional)

        Raises:
            ValueError: If size or position_id is invalid
        """
        # Validate inputs
        if not isinstance(size, int) or size <= 0 or size > 50:
            raise ValueError(f"Invalid size: {size}. Must be between 1 and 50.")
        self._validate_positive_int(position_id, "position_id")

        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        
        # Build the filter for free agents, sorted by ownership %, with stats
        filter_dict = {
            "players": {
                "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
                "limit": size,
                "sortPercOwned": {"sortAsc": False, "sortPriority": 1},
                "filterStatsForTopScoringPeriodIds": {
                    "value": 5,
                    "additionalValue": [
                        f"00{self.year}",   # Current season total
                        f"10{self.year}",   # Current season projected
                    ]
                }
            }
        }
        
        # Add position filter if specified
        if position_id:
            filter_dict["players"]["filterSlotIds"] = {"value": [position_id]}
        
        # ESPN expects the filter as a header, not a param
        import json
        headers = {"x-fantasy-filter": json.dumps(filter_dict)}
        params = {"view": "kona_player_info"}

        data = await self._make_request(url, params, headers)

        players = []
        for player_data in data.get("players", []):
            player_info = player_data["player"]
            
            # Parse ownership data
            ownership_data = player_data.get("ownership", {})
            percent_owned = ownership_data.get("percentOwned", 0)
            percent_change = ownership_data.get("percentChange", 0)
            
            # Parse stats - ESPN returns stats as a list of stat objects by period
            stats_data = {}
            player_stats_list = player_info.get("stats", [])
            
            if player_stats_list and len(player_stats_list) > 0:
                # Find the current season stats (id starts with "00" for actuals)
                for stat_set in player_stats_list:
                    stat_id = str(stat_set.get("id", ""))
                    
                    # "00YYYY" = season actuals, "10YYYY" = projections
                    if stat_id.startswith("00"):
                        # Get averages if available, otherwise use totals
                        averages = stat_set.get("averages", {})
                        totals = stat_set.get("stats", {})
                        
                        # Use averages preferentially (per-game stats)
                        source = averages if averages else totals
                        
                        # ESPN stat ID mapping for basketball:
                        # 0=PTS, 1=BLK, 2=STL, 3=AST, 6=REB, 13=FG%, 14=FT%, 17=3PM, 11=TO, 40=MIN
                        stats_data = {
                            "points": round(source.get("0", 0), 1),
                            "blocks": round(source.get("1", 0), 1),
                            "steals": round(source.get("2", 0), 1),
                            "assists": round(source.get("3", 0), 1),
                            "rebounds": round(source.get("6", 0), 1),
                            "fg_pct": round(source.get("19", 0) * 100, 1) if source.get("19") else None,  # FG%
                            "ft_pct": round(source.get("20", 0) * 100, 1) if source.get("20") else None,  # FT%
                            "threes": round(source.get("17", 0), 1),
                            "turnovers": round(source.get("11", 0), 1),
                            "minutes": round(source.get("40", 0), 1),
                            "games_played": stat_set.get("stats", {}).get("42", 0),
                        }
                        
                        # Also grab fantasy points average if available
                        if "appliedAverage" in stat_set:
                            stats_data["fantasy_avg"] = round(stat_set["appliedAverage"], 1)
                        
                        break  # Found season stats, stop looking
            
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
                ownership={
                    "percentOwned": percent_owned,
                    "percentChange": percent_change,
                },
                stats=stats_data if stats_data else None,
            )
            players.append(player)

        return players


    async def get_matchups(self, scoring_period: int | None = None) -> list[Matchup]:
        """Get matchups for the league."""
        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        params = {"view": "mMatchup"}

        if scoring_period:
            params["scoringPeriodId"] = str(scoring_period)

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
                        cumulativeScore=home_data.get("cumulativeScore"),
                    )

                away_team = None
                if schedule_item.get("away"):
                    away_data = schedule_item["away"]
                    away_team = MatchupTeam(
                        teamId=away_data.get("teamId"),
                        totalPoints=away_data.get("totalPoints"),
                        totalProjectedPoints=away_data.get("totalProjectedPoints"),
                        gamesPlayed=away_data.get("gamesPlayed"),
                        cumulativeScore=away_data.get("cumulativeScore"),
                    )

                matchup = Matchup(
                    id=schedule_item["id"],
                    matchupPeriodId=schedule_item["matchupPeriodId"],
                    home=home_team,
                    away=away_team,
                    winner=schedule_item.get("winner"),
                    playoff=schedule_item.get("playoff"),
                )
                matchups.append(matchup)

        return matchups

    async def get_nba_schedule(self, date: str | None = None) -> list[NBAGame]:
        """Get NBA schedule.

        Args:
            date: Date in YYYY-MM-DD format (optional, defaults to today)

        Returns:
            List of NBA games, or empty list if API fails
        """
        # Validate date format if provided
        if date:
            import re
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
                raise ValueError(f"Invalid date format: {date}. Must be YYYY-MM-DD.")

        url = f"{self.NBA_BASE_URL}/scoreboard"
        params = {}

        if date:
            params["dates"] = date

        try:
            data = await self._make_request(url, params)

            games = []
            for event in data.get("events", []):
                game = NBAGame(
                    id=event["id"], date=event["date"], competitions=event["competitions"]
                )
                games.append(game)

            return games
        except httpx.HTTPError as e:
            # Log specific HTTP errors but return empty list
            logger.warning(f"NBA API request failed with HTTP error: {e}")
            return []
        except Exception as e:
            # Log unexpected errors but return empty list
            logger.error(f"Unexpected error fetching NBA schedule: {e}")
            return []

    async def get_draft_status(self) -> DraftStatus:
        """Get current draft status and picks."""
        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        params = {"view": "mDraftDetail"}

        data = await self._make_request(url, params)
        draft_detail = data.get("draftDetail", {})

        picks = []
        for pick_data in draft_detail.get("picks", []):
            pick = DraftPick(
                id=pick_data["id"],
                playerId=pick_data["playerId"],
                teamId=pick_data["teamId"],
                bidAmount=pick_data.get("bidAmount", 0),
                overallPickNumber=pick_data["overallPickNumber"],
                roundId=pick_data["roundId"],
                roundPickNumber=pick_data["roundPickNumber"],
                nominatingTeamId=pick_data.get("nominatingTeamId"),
                memberId=pick_data.get("memberId"),
                lineupSlotId=pick_data.get("lineupSlotId"),
                keeper=pick_data.get("keeper", False),
            )
            picks.append(pick)

        # Determine current pick if draft is in progress
        current_pick_number = None
        current_nominating_team = None
        if draft_detail.get("inProgress", False):
            current_pick_number = len(picks) + 1
            # In auction drafts, teams take turns nominating
            if current_pick_number <= 12:  # Assuming 12 teams
                current_nominating_team = ((current_pick_number - 1) % 12) + 1

        return DraftStatus(
            inProgress=draft_detail.get("inProgress", False),
            drafted=draft_detail.get("drafted", False),
            completeDate=draft_detail.get("completeDate"),
            picks=picks,
            currentPickNumber=current_pick_number,
            currentNominatingTeam=current_nominating_team,
        )

    async def get_available_players(self, limit: int = 100) -> list[PlayerDraftInfo]:
        """Get available players for draft with auction values."""
        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        params = {"view": "kona_player_info"}

        data = await self._make_request(url, params)

        # Get current draft status to see who's been drafted
        draft_status = await self.get_draft_status()
        drafted_players = {
            pick.playerId: (pick.teamId, pick.bidAmount) for pick in draft_status.picks
        }

        players: list[PlayerDraftInfo] = []
        for player_entry in data.get("players", []):
            if len(players) >= limit:
                break

            player_data = player_entry["player"]
            player_id = player_data["id"]

            # Skip if already drafted
            if player_id in drafted_players:
                continue

            player = Player(
                id=player_id,
                fullName=player_data.get("fullName", ""),
                firstName=player_data.get("firstName", ""),
                lastName=player_data.get("lastName", ""),
                defaultPositionId=player_data["defaultPositionId"],
                eligibleSlots=player_data.get("eligibleSlots"),
                proTeamId=player_data.get("proTeamId"),
                active=player_data.get("active", True),
                injured=player_data.get("injured", False),
                injuryStatus=player_data.get("injuryStatus"),
            )

            # Get auction value from draft rankings
            auction_value = None
            rank = None
            if player_data.get("draftRanksByRankType", {}).get("STANDARD"):
                auction_value = player_data["draftRanksByRankType"]["STANDARD"].get(
                    "auctionValue", 0
                )
                rank = player_data["draftRanksByRankType"]["STANDARD"].get("rank")

            player_draft_info = PlayerDraftInfo(
                playerId=player_id,
                player=player,
                draftAuctionValue=player_entry.get("draftAuctionValue", 0),
                auctionValue=auction_value,
                rank=rank,
                isDrafted=False,
            )

            players.append(player_draft_info)

        # Sort by auction value (highest first)
        players.sort(key=lambda p: p.auctionValue or 0, reverse=True)
        return players

    async def get_team_draft_summary(self, team_id: int) -> TeamDraftSummary:
        """Get draft summary for a specific team."""
        # Get current draft picks
        draft_status = await self.get_draft_status()
        team_picks = [pick for pick in draft_status.picks if pick.teamId == team_id]

        # Get team info
        teams = await self.get_league_teams()
        team = next((t for t in teams if t.id == team_id), None)
        team_name = team.name if team else f"Team {team_id}"

        # Calculate spending
        total_spent = sum(pick.bidAmount for pick in team_picks)
        players_count = len(team_picks)

        # Assuming $200 budget (standard for auction)
        remaining_budget = 200 - total_spent

        # Get position counts (simplified)
        # TODO: This would need player data to get actual positions
        position_counts: dict[str, int] = {}

        return TeamDraftSummary(
            teamId=team_id,
            teamName=team_name,
            totalSpent=total_spent,
            playersCount=players_count,
            remainingBudget=remaining_budget,
            positionCounts=position_counts,
        )

    async def get_draft_recommendation(
        self, team_id: int, current_player_id: int | None = None
    ) -> DraftRecommendation:
        """Get draft recommendation for current situation."""
        # Get team's current status
        team_summary = await self.get_team_draft_summary(team_id)

        # Get available players
        available_players = await self.get_available_players(50)

        if current_player_id:
            # Player is currently being nominated - should we bid?
            current_player = next(
                (p for p in available_players if p.playerId == current_player_id), None
            )

            if not current_player:
                return DraftRecommendation(
                    action="pass",
                    reasoning="Player not found in available players list",
                    priority=1,
                )

            # Simple bidding logic
            player_value = current_player.auctionValue or 0
            max_affordable = min(
                team_summary.remainingBudget - (13 - team_summary.playersCount), player_value
            )

            if player_value >= 10 and max_affordable >= player_value * 0.8:
                return DraftRecommendation(
                    action="bid",
                    playerId=current_player_id,
                    playerName=current_player.player.fullName,
                    suggestedBid=min(player_value, max_affordable),
                    maxBid=max_affordable,
                    reasoning=f"Good value player worth ${player_value}. You can afford up to ${max_affordable}.",
                    priority=7,
                    category_impact={"value": "positive"},
                )
            else:
                return DraftRecommendation(
                    action="pass",
                    playerName=current_player.player.fullName,
                    reasoning=f"Player value (${player_value}) too high for remaining budget (${team_summary.remainingBudget})",
                    priority=3,
                )
        else:
            # Recommend next player to target
            if available_players:
                best_player = available_players[0]
                return DraftRecommendation(
                    action="nominate",
                    playerId=best_player.playerId,
                    playerName=best_player.player.fullName,
                    suggestedBid=best_player.auctionValue or 1,
                    reasoning=f"Highest ranked available player (rank #{best_player.rank})",
                    priority=9,
                    category_impact={"overall": "strong positive"},
                )

            return DraftRecommendation(
                action="pass", reasoning="No quality players available", priority=1
            )

    async def analyze_punt_strategy(self, team_id: int) -> dict[str, Any]:
        """Analyze current punt strategy based on drafted players."""
        team_summary = await self.get_team_draft_summary(team_id)

        # This would need more sophisticated analysis with player stats
        # For now, return basic info
        return {
            "totalSpent": team_summary.totalSpent,
            "remainingBudget": team_summary.remainingBudget,
            "playersCount": team_summary.playersCount,
            "strategy": "balanced" if team_summary.playersCount < 5 else "punt_detection_needed",
            "recommendation": f"You have ${team_summary.remainingBudget} for {13 - team_summary.playersCount} more players",
        }

    async def get_player_stats(self, player_id: int, timeframe: str = "season") -> PlayerStats:
        """Get comprehensive player statistics for specified timeframe.

        Args:
            player_id: ESPN player ID
            timeframe: One of "season", "projections", "last_7", "last_15", "last_30"

        Raises:
            ValueError: If player_id or timeframe is invalid, or player not found
        """
        # Validate inputs
        self._validate_positive_int(player_id, "player_id")

        # Map timeframe to ESPN stat period ID prefix
        timeframe_map = {
            "season": f"00{self.year}",
            "projections": f"10{self.year}",
            "last_7": f"01{self.year}",
            "last_15": f"02{self.year}",
            "last_30": f"03{self.year}",
        }

        if timeframe not in timeframe_map:
            raise ValueError(f"Invalid timeframe: {timeframe}. Must be one of {list(timeframe_map.keys())}")

        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        stat_period = timeframe_map[timeframe]

        # Build filter to request specific player with stats
        filter_dict = {
            "players": {
                "filterIds": {"value": [player_id]},
                "filterStatsForTopScoringPeriodIds": {
                    "value": 5,
                    "additionalValue": [stat_period]
                }
            }
        }
        
        import json
        headers = {"x-fantasy-filter": json.dumps(filter_dict)}
        params = {"view": "kona_player_info"}

        data = await self._make_request(url, params, headers)

        # Find the player in the response
        player_data = None
        for player_entry in data.get("players", []):
            if player_entry.get("player", {}).get("id") == player_id:
                player_data = player_entry
                break
        
        if not player_data:
            logger.warning(f"Player with ID {player_id} not found")
            raise ValueError("Player not found")

        player_info = player_data.get("player", {})
        
        # Parse stats for the requested timeframe
        stats_dict = self._parse_player_stats_for_timeframe(
            player_info.get("stats", []), 
            timeframe
        )

        return PlayerStats(
            playerId=player_id,
            playerName=player_info.get("fullName", "Unknown Player"),
            timeframe=timeframe,
            gamesPlayed=stats_dict.get("gamesPlayed"),
            minutes=stats_dict.get("minutes"),
            points=stats_dict.get("points"),
            rebounds=stats_dict.get("rebounds"),
            assists=stats_dict.get("assists"),
            steals=stats_dict.get("steals"),
            blocks=stats_dict.get("blocks"),
            threePointMade=stats_dict.get("threes"),
            turnovers=stats_dict.get("turnovers"),
            fieldGoalPercentage=stats_dict.get("fg_pct"),
            freeThrowPercentage=stats_dict.get("ft_pct"),
            fantasyPoints=stats_dict.get("fantasyAvg"),
        )

    def _parse_player_stats_for_timeframe(
        self, stats_list: list[dict[str, Any]], timeframe: str
    ) -> dict[str, Any]:
        """Parse stats for a specific timeframe."""
        # Map timeframe to ESPN stat ID prefix
        prefix_map = {
            "season": "00",
            "projections": "10", 
            "last_7": "01",
            "last_15": "02",
            "last_30": "03",
        }
        target_prefix = prefix_map.get(timeframe, "00")
        
        for stat_set in stats_list:
            stat_id = str(stat_set.get("id", ""))
            
            if stat_id.startswith(target_prefix):
                averages = stat_set.get("averages", {})
                totals = stat_set.get("stats", {})
                games_played = totals.get("42", 0)
                
                stats_data = {}
                
                if averages:
                    stats_data = {
                        "gamesPlayed": int(games_played) if games_played else 0,
                        "minutes": round(averages.get("40", 0), 1),
                        "points": round(averages.get("0", 0), 1),
                        "rebounds": round(averages.get("6", 0), 1),
                        "assists": round(averages.get("3", 0), 1),
                        "steals": round(averages.get("2", 0), 1),
                        "blocks": round(averages.get("1", 0), 1),
                        "threes": round(averages.get("17", 0), 1),
                        "turnovers": round(averages.get("11", 0), 1),
                        "fg_pct": round(averages.get("19", 0) * 100, 1) if averages.get("19") else None,
                        "ft_pct": round(averages.get("20", 0) * 100, 1) if averages.get("20") else None,
                    }
                elif totals and games_played > 0:
                    gp = games_played
                    stats_data = {
                        "gamesPlayed": int(gp),
                        "minutes": round(totals.get("40", 0) / gp, 1),
                        "points": round(totals.get("0", 0) / gp, 1),
                        "rebounds": round(totals.get("6", 0) / gp, 1),
                        "assists": round(totals.get("3", 0) / gp, 1),
                        "steals": round(totals.get("2", 0) / gp, 1),
                        "blocks": round(totals.get("1", 0) / gp, 1),
                        "threes": round(totals.get("17", 0) / gp, 1),
                        "turnovers": round(totals.get("11", 0) / gp, 1),
                        "fg_pct": round(totals.get("19", 0) * 100, 1) if totals.get("19") else None,
                        "ft_pct": round(totals.get("20", 0) * 100, 1) if totals.get("20") else None,
                    }
                
                if "appliedAverage" in stat_set:
                    stats_data["fantasyAvg"] = round(stat_set["appliedAverage"], 1)
                    
                return stats_data
        
        return {}

    def _extract_player_stats(self, player_data: dict[str, Any], timeframe: str) -> dict[str, Any]:
        """Extract statistics from ESPN player data based on timeframe."""
        stats = {}

        # Get the appropriate stats object based on timeframe
        if timeframe == "season":
            # Season stats
            stat_source = player_data.get("player", {}).get("stats", [])
            if stat_source:
                # ESPN provides stats as a list, typically index 0 is current season
                season_stats = stat_source[0] if isinstance(stat_source, list) else stat_source
                stats = self._parse_espn_stats(season_stats)
        elif timeframe == "projections":
            # Projected stats
            stat_source = player_data.get("player", {}).get("projections", {})
            stats = self._parse_espn_stats(stat_source)
        elif timeframe.startswith("last_"):
            # For last X games, we'd need to calculate from game logs
            # This is a simplified version - in practice you'd aggregate recent games
            stat_source = player_data.get("player", {}).get("stats", [])
            if stat_source:
                season_stats = stat_source[0] if isinstance(stat_source, list) else stat_source
                stats = self._parse_espn_stats(season_stats)
                # Note: This is season stats, not actually last X games
                # To get true last X games, you'd need to fetch game logs separately

        return stats

    def _parse_espn_stats(self, stat_data: dict[str, Any]) -> dict[str, Any]:
        """Parse ESPN's stat format into our standardized format."""
        # ESPN uses different stat IDs for different categories
        # This is a mapping of common ESPN stat IDs to our field names
        stat_mapping = {
            "0": "points",  # Points
            "1": "rebounds",  # Rebounds
            "2": "assists",  # Assists
            "3": "steals",  # Steals
            "4": "blocks",  # Blocks
            "17": "threePointMade",  # 3PM
            "19": "fieldGoalPercentage",  # FG%
            "20": "freeThrowPercentage",  # FT%
            "11": "turnovers",  # Turnovers
            "40": "minutes",  # Minutes
            "gamesPlayed": "gamesPlayed",
        }

        parsed_stats = {}

        # ESPN stores stats in different formats depending on endpoint
        if "appliedStats" in stat_data:
            # Fantasy scoring stats
            applied_stats = stat_data["appliedStats"]
            for espn_id, field_name in stat_mapping.items():
                if espn_id in applied_stats:
                    parsed_stats[field_name] = applied_stats[espn_id]

        if "stats" in stat_data:
            # Raw stats
            raw_stats = stat_data["stats"]
            for espn_id, field_name in stat_mapping.items():
                if espn_id in raw_stats:
                    parsed_stats[field_name] = raw_stats[espn_id]

        # Calculate fantasy points if available
        if "appliedTotal" in stat_data:
            parsed_stats["fantasyPoints"] = stat_data["appliedTotal"]

        return parsed_stats

    async def compare_players(
        self, player_ids: list[int], categories: list[str] | None = None
    ) -> PlayerComparison:
        """Compare multiple players across specified statistical categories."""
        if categories is None:
            categories = [
                "points",
                "rebounds",
                "assists",
                "steals",
                "blocks",
                "threePointMade",
                "fieldGoalPercentage",
                "freeThrowPercentage",
                "turnovers",
            ]

        # Get stats for all players
        players_stats = []
        for player_id in player_ids:
            try:
                stats = await self.get_player_stats(player_id)
                players_stats.append(stats)
            except ValueError:
                # Player not found, skip
                continue

        if len(players_stats) < 2:
            raise ValueError("Need at least 2 valid players to compare")

        # Determine winner in each category
        winner_by_category = {}
        for category in categories:
            best_value = None
            best_player_id = None

            # For percentage stats, higher is better. For turnovers, lower is better
            reverse_categories = ["turnovers"]
            reverse = category in reverse_categories

            for player_stats in players_stats:
                value = getattr(player_stats, category, None)
                if value is not None:
                    if best_value is None or (
                        (value > best_value and not reverse) or (value < best_value and reverse)
                    ):
                        best_value = value
                        best_player_id = player_stats.playerId

            if best_player_id:
                winner_by_category[category] = best_player_id

        # Generate overall recommendation
        category_wins = {}
        for player_stats in players_stats:
            category_wins[player_stats.playerId] = sum(
                1 for winner in winner_by_category.values() if winner == player_stats.playerId
            )

        best_overall = max(category_wins.items(), key=lambda x: x[1])
        best_player_name = next(
            p.playerName for p in players_stats if p.playerId == best_overall[0]
        )

        overall_recommendation = (
            f"{best_player_name} wins {best_overall[1]}/{len(categories)} categories"
        )
        analysis = (
            f"Detailed comparison across {len(categories)} statistical categories. "
            f"{best_player_name} provides the most balanced production."
        )

        return PlayerComparison(
            players=players_stats,
            categories=categories,
            winner_by_category=winner_by_category,
            overall_recommendation=overall_recommendation,
            analysis=analysis,
        )

    async def analyze_trade_proposal(
        self, your_player_ids: list[int], their_player_ids: list[int]
    ) -> TradeAnalysis:
        """Analyze a trade proposal using comprehensive statistical analysis."""
        # Get stats for all players involved
        your_players = []
        their_players = []

        for player_id in your_player_ids:
            try:
                stats = await self.get_player_stats(player_id)
                your_players.append(stats)
            except ValueError:
                continue

        for player_id in their_player_ids:
            try:
                stats = await self.get_player_stats(player_id)
                their_players.append(stats)
            except ValueError:
                continue

        if not your_players or not their_players:
            raise ValueError("Could not find valid players for trade analysis")

        # Calculate total value using fantasy points as base metric
        your_total_value = sum(p.fantasyPoints or 0 for p in your_players)
        their_total_value = sum(p.fantasyPoints or 0 for p in their_players)

        value_difference = their_total_value - your_total_value
        value_percentage = abs(value_difference) / max(your_total_value, 1) * 100

        # Generate recommendation
        if value_percentage < 5:
            recommendation = "fair_trade"
            reasoning = "Trade values are very close, consider team needs and schedule"
        elif value_difference > 0:
            if value_percentage > 20:
                recommendation = "accept"
                reasoning = f"You gain significant value (+{value_difference:.1f} fantasy points)"
            else:
                recommendation = "slight_accept"
                reasoning = f"You gain moderate value (+{value_difference:.1f} fantasy points)"
        else:
            if value_percentage > 20:
                recommendation = "reject"
                reasoning = f"You lose significant value ({value_difference:.1f} fantasy points)"
            else:
                recommendation = "negotiate"
                reasoning = (
                    f"You lose some value ({value_difference:.1f} fantasy points), try to get more"
                )

        # Analyze category impact (simplified)
        category_impact = self._analyze_category_impact(your_players, their_players)

        # Calculate confidence based on data quality
        confidence = min(0.95, 0.5 + (len(your_players) + len(their_players)) * 0.1)

        return TradeAnalysis(
            your_players=your_players,
            their_players=their_players,
            your_total_value=your_total_value,
            their_total_value=their_total_value,
            value_difference=value_difference,
            recommendation=recommendation,
            reasoning=reasoning,
            category_impact=category_impact,
            confidence=confidence,
        )

    def _analyze_category_impact(
        self, your_players: list[PlayerStats], their_players: list[PlayerStats]
    ) -> dict[str, str]:
        """Analyze the category-by-category impact of a trade."""
        categories = ["points", "rebounds", "assists", "steals", "blocks", "threePointMade"]
        impact = {}

        for category in categories:
            your_total = sum(getattr(p, category, 0) or 0 for p in your_players)
            their_total = sum(getattr(p, category, 0) or 0 for p in their_players)
            difference = their_total - your_total

            if abs(difference) < 0.5:
                impact[category] = "neutral"
            elif difference > 0:
                impact[category] = "gain"
            else:
                impact[category] = "loss"

        return impact

    async def get_trending_players(
        self, direction: str = "up", limit: int = 20
    ) -> list[TrendingPlayer]:
        """Get players trending up or down in adds/drops."""
        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        params = {"view": "kona_player_info"}

        data = await self._make_request(url, params)

        trending_players: list[TrendingPlayer] = []

        for player_entry in data.get("players", []):
            if len(trending_players) >= limit:
                break

            player_info = player_entry["player"]
            ownership = player_entry.get("ownership", {})

            # Calculate trending metrics
            add_percentage = ownership.get("percentChange", 0)

            # Determine if this player matches the requested direction
            is_trending_up = add_percentage > 1  # More than 1% increase
            is_trending_down = add_percentage < -1  # More than 1% decrease

            if direction == "up" and not is_trending_up:
                continue
            elif direction == "down" and not is_trending_down:
                continue

            # Create Player object
            player = Player(
                id=player_info["id"],
                fullName=player_info.get("fullName", ""),
                defaultPositionId=player_info["defaultPositionId"],
            )

            # Determine reason for trending
            if is_trending_up:
                reason = "Increased add rate due to recent performance"
            elif is_trending_down:
                reason = "Increased drop rate, possibly due to poor performance or injury"
            else:
                reason = "Stable ownership"

            trending_player = TrendingPlayer(
                playerId=player_info["id"],
                player=player,
                trend_direction="up"
                if is_trending_up
                else "down"
                if is_trending_down
                else "stable",
                add_percentage=max(0, add_percentage),
                drop_percentage=max(0, -add_percentage),
                net_adds=int(add_percentage * 100),  # Approximate
                reason=reason,
            )

            trending_players.append(trending_player)

        # Sort by trending strength
        trending_players.sort(key=lambda x: abs(x.add_percentage - x.drop_percentage), reverse=True)

        return trending_players

    async def get_player_schedule(
        self, player_id: int, nba_team_id: int, start_date: str, end_date: str
    ) -> PlayerSchedule:
        """Get schedule for a specific player.

        Args:
            player_id: ESPN player ID
            nba_team_id: NBA team ID (proTeamId from player data)
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format

        Returns:
            PlayerSchedule with games and summary

        Raises:
            ValueError: If dates are invalid
        """
        # Validate inputs
        self._validate_positive_int(player_id, "player_id")
        import re
        from datetime import datetime

        if not re.match(r"^\d{4}-\d{2}-\d{2}$", start_date):
            raise ValueError(f"Invalid start_date format: {start_date}. Must be YYYY-MM-DD.")
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", end_date):
            raise ValueError(f"Invalid end_date format: {end_date}. Must be YYYY-MM-DD.")

        # Get NBA team schedule from ESPN API
        # We need to get all games for this team and filter by date range
        url = f"{self.NBA_BASE_URL}/teams/{nba_team_id}/schedule"
        params = {"season": self.year}

        try:
            data = await self._make_request(url, params)
        except httpx.HTTPError as e:
            logger.warning(f"Failed to get schedule for NBA team {nba_team_id}: {e}")
            # Return empty schedule if API fails
            return PlayerSchedule(
                playerId=player_id,
                playerName="Unknown Player",
                teamAbbreviation="UNK",
                games=[],
                gamesThisWeek=0,
                gamesNextWeek=0,
            )

        # Parse schedule data
        games = []
        team_abbrev = data.get("team", {}).get("abbreviation", "UNK")
        player_name = f"Player {player_id}"  # We'll need to get this from elsewhere

        events = data.get("events", [])
        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)

        for event in events:
            game_date_str = event.get("date", "")[:10]  # Get just YYYY-MM-DD part
            try:
                game_dt = datetime.fromisoformat(game_date_str)
            except ValueError:
                continue

            # Filter by date range
            if start_dt <= game_dt <= end_dt:
                competitions = event.get("competitions", [{}])[0]
                competitors = competitions.get("competitors", [])

                # Determine opponent and home/away status
                opponent = ""
                is_home = False

                for comp in competitors:
                    comp_team = comp.get("team", {})
                    comp_team_id = comp_team.get("id")
                    if str(comp_team_id) == str(nba_team_id):
                        # This is the player's team
                        is_home = comp.get("homeAway") == "home"
                    else:
                        # This is the opponent
                        opponent = comp_team.get("abbreviation", "UNK")

                game = PlayerScheduleGame(
                    date=game_date_str,
                    opponent=opponent,
                    is_home=is_home,
                    game_id=event.get("id"),
                )
                games.append(game)

        # Calculate games this week and next week
        # For simplicity, count all games in the range as "this week"
        games_this_week = len(games)
        games_next_week = 0  # Would need additional date range to calculate

        return PlayerSchedule(
            playerId=player_id,
            playerName=player_name,
            teamAbbreviation=team_abbrev,
            games=games,
            gamesThisWeek=games_this_week,
            gamesNextWeek=games_next_week,
        )

    async def get_roster_schedule_summary(
        self, team_id: int, start_date: str, end_date: str
    ) -> RosterScheduleSummary:
        """Get schedule summary for all players on a fantasy roster.

        Args:
            team_id: Fantasy team ID
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format

        Returns:
            RosterScheduleSummary with schedule data for all rostered players

        Raises:
            ValueError: If team_id or dates are invalid
        """
        # Validate inputs
        self._validate_positive_int(team_id, "team_id")

        # Get the roster first
        roster = await self.get_team_roster(team_id)

        player_schedules = []
        total_games = 0

        # Get schedule for each player on the roster
        for entry in roster.entries:
            player = entry.playerPoolEntry.player
            nba_team_id = player.proTeamId

            if not nba_team_id:
                # Player doesn't have NBA team (e.g., injured reserve, not assigned)
                continue

            try:
                schedule = await self.get_player_schedule(
                    player.id, nba_team_id, start_date, end_date
                )
                # Update player name with actual name from roster
                schedule.playerName = player.fullName
                player_schedules.append(schedule)
                total_games += schedule.gamesThisWeek
            except Exception as e:
                logger.warning(f"Failed to get schedule for player {player.fullName}: {e}")
                continue

        # Calculate average
        avg_games = total_games / len(player_schedules) if player_schedules else 0.0

        return RosterScheduleSummary(
            teamId=team_id,
            scoringPeriod=0,  # Would need to determine current scoring period
            playerSchedules=player_schedules,
            totalGamesThisWeek=total_games,
            averageGamesPerPlayer=round(avg_games, 2),
        )

"""ESPN Fantasy Basketball API client."""

import logging
import os
from typing import Any

import httpx

from .models import (
    AcquisitionSettings,
    CategoryProjection,
    CurrentMatchup,
    DraftPick,
    DraftRecommendation,
    DraftStatus,
    LeagueSettings,
    LeagueStatus,
    Matchup,
    MatchupAnalysis,
    MatchupTeam,
    NBAGame,
    Player,
    PlayerComparison,
    PlayerDraftInfo,
    PlayerPoolEntry,
    PlayerRecommendation,
    PlayerSchedule,
    PlayerScheduleGame,
    PlayerStats,
    Roster,
    RosterEntry,
    RosterScheduleSummary,
    RosterSettings,
    ScheduleSettings,
    ScoringItem,
    ScoringSettings,
    Team,
    TeamDraftSummary,
    TeamSeasonStats,
    TodaysGame,
    TradeAnalysis,
    TradeSettings,
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

    @staticmethod
    def _get_timezone() -> str:
        """Get timezone from MY_TIMEZONE environment variable.

        Returns:
            Timezone string (defaults to 'America/New_York' if not set)
        """
        return os.getenv("MY_TIMEZONE", "America/New_York")

    def _convert_utc_to_timezone_iso(self, utc_date_str: str) -> str:
        """Convert UTC date string to ISO format in the configured timezone.

        Args:
            utc_date_str: UTC date string (e.g., "2025-01-15T20:00:00Z")

        Returns:
            ISO formatted datetime string in the configured timezone, or original string if conversion fails
        """
        if not utc_date_str:
            return utc_date_str
        
        try:
            from datetime import datetime, timezone
            from zoneinfo import ZoneInfo
            # Parse UTC datetime (API returns format like "2025-01-15T20:00:00Z")
            utc_dt = datetime.fromisoformat(utc_date_str.replace('Z', '+00:00'))
            # Convert to timezone specified by MY_TIMEZONE
            tz_dt = utc_dt.astimezone(ZoneInfo(self._get_timezone()))
            # Format as ISO datetime string
            return tz_dt.isoformat()
        except (ValueError, OSError) as e:
            logger.warning(f"Could not parse date {utc_date_str}: {e}")
            # Fallback to original date string
            return utc_date_str

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

    async def get_league_settings(self) -> LeagueSettings:
        """Get league settings including schedule, roster, scoring, and acquisition settings.

        Returns:
            LeagueSettings object with all league configuration

        Raises:
            ValueError: If league not found or settings unavailable
        """
        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        params = {"view": "mSettings"}

        data = await self._make_request(url, params)

        if "settings" not in data:
            raise ValueError("Settings not found in API response")

        settings_data = data["settings"]
        status_data = data.get("status", {})

        # Parse scoring settings
        scoring_data = settings_data.get("scoringSettings", {})
        # Get stat ID mapping for human-readable category names
        stat_mapping = self._get_stat_id_mapping()
        scoring_items = []
        for item in scoring_data.get("scoringItems", []):
            stat_id = item.get("statId", 0)
            # Map stat ID to human-readable category name
            category_name = stat_mapping.get(str(stat_id), f"stat_{stat_id}")
            scoring_items.append(
                ScoringItem(
                    statId=stat_id,
                    categoryName=category_name,
                    points=item.get("points", 0.0),
                    isReverseItem=item.get("isReverseItem", False),
                    pointsOverrides=item.get("pointsOverrides", {}),
                )
            )
        scoring_settings = ScoringSettings(
            scoringType=scoring_data.get("scoringType", "H2H_CATEGORY"),
            scoringItems=scoring_items,
            playerRankType=scoring_data.get("playerRankType"),
            matchupTieRule=scoring_data.get("matchupTieRule"),
            allowOutOfPositionScoring=scoring_data.get("allowOutOfPositionScoring", False),
        )

        # Parse schedule settings
        schedule_data = settings_data.get("scheduleSettings", {})
        schedule_settings = ScheduleSettings(
            matchupPeriodCount=schedule_data.get("matchupPeriodCount", 0),
            matchupPeriodLength=schedule_data.get("matchupPeriodLength", 1),
            matchupPeriods=schedule_data.get("matchupPeriods", {}),
            periodTypeId=schedule_data.get("periodTypeId", 2),
            playoffTeamCount=schedule_data.get("playoffTeamCount", 0),
            playoffMatchupPeriodLength=schedule_data.get("playoffMatchupPeriodLength", 1),
            playoffSeedingRule=schedule_data.get("playoffSeedingRule"),
        )

        # Parse roster settings
        roster_data = settings_data.get("rosterSettings", {})
        # Get slot ID mapping for human-readable slot names
        slot_mapping = self._get_lineup_slot_id_mapping()
        lineup_slot_counts = {str(k): v for k, v in roster_data.get("lineupSlotCounts", {}).items()}
        # Map slot IDs to human-readable names
        lineup_slot_names = {
            slot_id: slot_mapping.get(int(slot_id), f"SLOT_{slot_id}")
            for slot_id in lineup_slot_counts.keys()
        }
        roster_settings = RosterSettings(
            lineupSlotCounts=lineup_slot_counts,
            lineupSlotNames=lineup_slot_names if lineup_slot_names else None,
            positionLimits={str(k): v for k, v in roster_data.get("positionLimits", {}).items()},
            lineupLocktimeType=roster_data.get("lineupLocktimeType", "FIRSTGAME_WEEKLY"),
            rosterLocktimeType=roster_data.get("rosterLocktimeType"),
            isBenchUnlimited=roster_data.get("isBenchUnlimited", False),
            moveLimit=roster_data.get("moveLimit", -1),
        )

        # Parse acquisition settings
        acquisition_data = settings_data.get("acquisitionSettings", {})
        acquisition_settings = AcquisitionSettings(
            acquisitionType=acquisition_data.get("acquisitionType", "WAIVERS_TRADITIONAL"),
            waiverHours=acquisition_data.get("waiverHours", 24),
            waiverProcessDays=acquisition_data.get("waiverProcessDays", []),
            waiverProcessHour=acquisition_data.get("waiverProcessHour", 0),
            matchupAcquisitionLimit=acquisition_data.get("matchupAcquisitionLimit", 0.0),
            matchupLimitPerScoringPeriod=acquisition_data.get("matchupLimitPerScoringPeriod", False),
            acquisitionLimit=acquisition_data.get("acquisitionLimit", -1),
            minimumBid=acquisition_data.get("minimumBid", 0),
        )

        # Parse trade settings
        trade_data = settings_data.get("tradeSettings", {})
        deadline_date = trade_data.get("deadlineDate")
        deadline_date_iso = None
        if deadline_date:
            # Convert epoch timestamp (milliseconds) to ISO 8601 datetime string in ET timezone
            from datetime import datetime, timezone
            try:
                # ESPN uses milliseconds, so divide by 1000
                dt = datetime.fromtimestamp(deadline_date / 1000, tz=timezone.utc)
                # Convert to ET (matching acquisitionDateISO and game time conversions)
                from zoneinfo import ZoneInfo
                et_dt = dt.astimezone(ZoneInfo(self._get_timezone()))
                deadline_date_iso = et_dt.isoformat()
            except (ValueError, OSError) as e:
                logger.warning(f"Could not parse deadline date {deadline_date}: {e}")
        trade_settings = TradeSettings(
            deadlineDate=deadline_date,
            deadlineDateISO=deadline_date_iso,
            vetoVotesRequired=trade_data.get("vetoVotesRequired", 0),
            revisionHours=trade_data.get("revisionHours", 24),
            max=trade_data.get("max", -1),
            allowOutOfUniverse=trade_data.get("allowOutOfUniverse", False),
        )

        # Parse status
        status = LeagueStatus(
            currentMatchupPeriod=status_data.get("currentMatchupPeriod", 0),
            latestScoringPeriod=status_data.get("latestScoringPeriod", 0),
            firstScoringPeriod=status_data.get("firstScoringPeriod", 1),
            finalScoringPeriod=status_data.get("finalScoringPeriod", 0),
            isActive=status_data.get("isActive", False),
            transactionScoringPeriod=status_data.get("transactionScoringPeriod"),
        )

        return LeagueSettings(
            leagueId=data.get("id", self.league_id),
            leagueName=settings_data.get("name", ""),
            seasonId=data.get("seasonId", self.year),
            size=settings_data.get("size", 0),
            scoringSettings=scoring_settings,
            scheduleSettings=schedule_settings,
            rosterSettings=roster_settings,
            acquisitionSettings=acquisition_settings,
            tradeSettings=trade_settings,
            status=status,
        )

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

        # Fetch today's NBA schedule once for all players (optimization)
        # Don't pass date parameter - API defaults to today's games
        todays_games_cache = {}
        team_id_to_abbrev = {}  # Maps proTeamId to abbreviation for teams playing today
        try:
            url_nba = f"{self.NBA_BASE_URL}/scoreboard"
            # Don't pass dates parameter - API defaults to today's games in ET timezone
            params_nba = {}
            nba_data = await self._make_request(url_nba, params_nba)
            todays_games_cache, team_id_to_abbrev = self._parse_todays_games(nba_data)
        except Exception as e:
            logger.debug(f"Could not fetch today's NBA schedule: {e}")

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
                    
                    pro_team_id = player_data.get("proTeamId")
                    # Use consistent fallback logic for team abbreviation
                    pro_team_abbrev = self._resolve_pro_team_abbrev(
                        pro_team_id,
                        player_data.get("proTeamAbbrev"),
                        team_id_to_abbrev
                    )
                    pro_team_name = player_data.get("proTeamName")
                    
                    # Map position and slot IDs to names
                    position_mapping = self._get_position_id_mapping()
                    slot_mapping = self._get_lineup_slot_id_mapping()
                    default_position_id = player_data["defaultPositionId"]
                    default_position = position_mapping.get(default_position_id)
                    
                    eligible_slots = player_data.get("eligibleSlots")
                    eligible_slot_names = None
                    if eligible_slots:
                        eligible_slot_names = [slot_mapping.get(slot_id, f"SLOT_{slot_id}") for slot_id in eligible_slots]
                    
                    player = Player(
                        id=player_data["id"],
                        fullName=player_data.get("fullName", ""),
                        firstName=player_data.get("firstName", ""),
                        lastName=player_data.get("lastName", ""),
                        jersey=player_data.get("jersey"),
                        proTeamId=pro_team_id,
                        proTeamAbbrev=pro_team_abbrev,
                        proTeamName=pro_team_name,
                        defaultPositionId=default_position_id,
                        defaultPosition=default_position,
                        eligibleSlots=eligible_slots,
                        eligibleSlotNames=eligible_slot_names,
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

                    # Map lineup slot ID to name
                    slot_mapping = self._get_lineup_slot_id_mapping()
                    lineup_slot_id = entry["lineupSlotId"]
                    lineup_slot_name = slot_mapping.get(lineup_slot_id, f"SLOT_{lineup_slot_id}")
                    
                    # Get today's game info for this player from cache
                    # Lookup by abbreviation (which we've populated above)
                    todays_game = todays_games_cache.get(pro_team_abbrev) if pro_team_abbrev else None
                    
                    # Convert acquisitionDate to ISO format if present
                    acquisition_date = entry.get("acquisitionDate")
                    acquisition_date_iso = None
                    if acquisition_date:
                        from datetime import datetime, timezone
                        try:
                            # ESPN uses milliseconds, so divide by 1000
                            dt = datetime.fromtimestamp(acquisition_date / 1000, tz=timezone.utc)
                            # Convert to ET (matching game time conversions)
                            from zoneinfo import ZoneInfo
                            et_dt = dt.astimezone(ZoneInfo(self._get_timezone()))
                            acquisition_date_iso = et_dt.isoformat()
                        except (ValueError, OSError) as e:
                            logger.warning(f"Could not parse acquisition date {acquisition_date}: {e}")
                    
                    roster_entry = RosterEntry(
                        playerId=entry["playerId"],
                        playerPoolEntry=player_pool_entry,
                        lineupSlotId=lineup_slot_id,
                        lineupSlotName=lineup_slot_name,
                        acquisitionDate=acquisition_date,
                        acquisitionDateISO=acquisition_date_iso,
                        acquisitionType=entry.get("acquisitionType"),
                        injuryStatus=injury_status,
                        todaysGame=todays_game,
                    )

                    roster_entries.append(roster_entry)

                return Roster(teamId=team_id, entries=roster_entries)

        # Log the detailed error but return generic message
        logger.warning(f"Team with ID {team_id} not found in league {self.league_id}")
        raise ValueError("Team not found in this league")

    def _make_roster_slim(self, roster: Roster) -> Roster:
        """Create a slim version of a roster with stats removed.
        
        Args:
            roster: Full roster object
            
        Returns:
            New Roster object with player stats set to None
        """
        from espn_fantasy_basketball_mcp.models import Player, PlayerPoolEntry, RosterEntry
        
        slim_entries = []
        for entry in roster.entries:
            # Create slim player (without stats)
            # Preserve position/slot mappings from original player
            slim_player = Player(
                id=entry.playerPoolEntry.player.id,
                fullName=entry.playerPoolEntry.player.fullName,
                firstName=entry.playerPoolEntry.player.firstName,
                lastName=entry.playerPoolEntry.player.lastName,
                jersey=entry.playerPoolEntry.player.jersey,
                proTeamId=entry.playerPoolEntry.player.proTeamId,
                proTeamAbbrev=entry.playerPoolEntry.player.proTeamAbbrev,  # Preserve team mapping
                proTeamName=entry.playerPoolEntry.player.proTeamName,  # Preserve team mapping
                defaultPositionId=entry.playerPoolEntry.player.defaultPositionId,
                defaultPosition=entry.playerPoolEntry.player.defaultPosition,
                eligibleSlots=entry.playerPoolEntry.player.eligibleSlots,
                eligibleSlotNames=entry.playerPoolEntry.player.eligibleSlotNames,
                injured=entry.playerPoolEntry.player.injured,
                injuryStatus=entry.playerPoolEntry.player.injuryStatus,
                stats=None,  # Remove stats
                ownership=entry.playerPoolEntry.player.ownership,
                active=entry.playerPoolEntry.player.active,
                droppable=entry.playerPoolEntry.player.droppable,
            )
            
            # Create slim player pool entry
            slim_player_pool_entry = PlayerPoolEntry(
                id=entry.playerPoolEntry.id,
                player=slim_player,
                onTeamId=entry.playerPoolEntry.onTeamId,
                keeperValue=entry.playerPoolEntry.keeperValue,
                keeperValueFuture=entry.playerPoolEntry.keeperValueFuture,
                lineupLocked=entry.playerPoolEntry.lineupLocked,
            )
            
            # Create slim roster entry
            slim_entry = RosterEntry(
                playerId=entry.playerId,
                playerPoolEntry=slim_player_pool_entry,
                lineupSlotId=entry.lineupSlotId,
                lineupSlotName=entry.lineupSlotName,  # Preserve slot name
                acquisitionDate=entry.acquisitionDate,
                acquisitionDateISO=entry.acquisitionDateISO,  # Preserve ISO date
                acquisitionType=entry.acquisitionType,
                injuryStatus=entry.injuryStatus,
            )
            
            slim_entries.append(slim_entry)
        
        return Roster(teamId=roster.teamId, entries=slim_entries)

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

    async def get_free_agents(
        self, size: int = 50, position_id: int | None = None, verbose: bool = False
    ) -> list[Player]:
        """Get free agents/waiver wire players.

        Args:
            size: Number of players to return (max 50)
            position_id: Filter by position ID (optional)
            verbose: If True, include full season stats and per-game averages.
                     If False, return only essential fields (id, name, position, ownership) (default False).

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
            
            # Parse stats only if verbose mode
            stats_data = None
            if verbose:
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
            
            # Use consistent fallback logic for team abbreviation
            pro_team_id = player_info.get("proTeamId")
            pro_team_abbrev = self._resolve_pro_team_abbrev(
                pro_team_id,
                player_info.get("proTeamAbbrev")
            )
            pro_team_name = player_info.get("proTeamName")
            
            # Map position and slot IDs to names
            position_mapping = self._get_position_id_mapping()
            slot_mapping = self._get_lineup_slot_id_mapping()
            default_position_id = player_info["defaultPositionId"]
            default_position = position_mapping.get(default_position_id)
            
            eligible_slots = player_info.get("eligibleSlots")
            eligible_slot_names = None
            if eligible_slots:
                eligible_slot_names = [slot_mapping.get(slot_id, f"SLOT_{slot_id}") for slot_id in eligible_slots]
            
            player = Player(
                id=player_info["id"],
                fullName=player_info["fullName"],
                firstName=player_info.get("firstName"),
                lastName=player_info.get("lastName"),
                jersey=player_info.get("jersey"),
                proTeamId=pro_team_id,
                proTeamAbbrev=pro_team_abbrev,
                proTeamName=pro_team_name,
                defaultPositionId=default_position_id,
                defaultPosition=default_position,
                eligibleSlots=eligible_slots,
                eligibleSlotNames=eligible_slot_names,
                injured=player_info.get("injured", False),
                injuryStatus=player_info.get("injuryStatus"),
                ownership={
                    "percentOwned": percent_owned,
                    "percentChange": percent_change,
                },
                stats=stats_data,
            )
            players.append(player)

        return players


    async def get_matchups(
        self, scoring_period: int | None = None, team_id: int | None = None
    ) -> list[Matchup]:
        """Get matchups for the league.
        
        Args:
            scoring_period: Specific scoring period (defaults to current week if not provided)
            team_id: Filter to only return matchups for this team (optional)
            
        Returns:
            List of Matchup objects
        """
        # Default to current scoring period if not provided
        if scoring_period is None:
            try:
                league_settings = await self.get_league_settings()
                scoring_period = league_settings.status.currentMatchupPeriod
            except Exception as e:
                logger.warning(f"Could not get current scoring period from league settings: {e}")
                # Try to get it from the API response as fallback
                # We'll fetch matchups without filtering first, then extract the current period
                scoring_period = None  # Will be determined from API response
        
        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        params = {"view": "mMatchup"}

        if scoring_period:
            params["scoringPeriodId"] = str(scoring_period)

        data = await self._make_request(url, params)
        
        # If scoring_period is still None, try to determine it from the API response
        if scoring_period is None:
            # Find the most recent matchup period that has completed or is in progress
            schedule = data.get("schedule", [])
            if schedule:
                # Get all unique matchup periods, sorted descending
                matchup_periods = sorted(
                    set(item.get("matchupPeriodId") for item in schedule if item.get("matchupPeriodId")),
                    reverse=True
                )
                if matchup_periods:
                    # Use the most recent matchup period as fallback
                    scoring_period = matchup_periods[0]
                    logger.info(f"Determined current scoring period from API response: {scoring_period}")
                else:
                    # If we can't determine it, raise an error rather than returning all matchups
                    raise ValueError(
                        "Could not determine current scoring period. "
                        "Please provide scoring_period parameter explicitly."
                    )
            else:
                # No schedule data available
                raise ValueError(
                    "Could not determine current scoring period. "
                    "Please provide scoring_period parameter explicitly."
                )
        
        # Get stat ID mapping for human-readable category names
        stat_mapping = self._get_stat_id_mapping()
        
        # Get league settings to determine scoring categories
        league_settings = None
        scoring_stat_ids = set()
        try:
            league_settings = await self.get_league_settings()
            scoring_stat_ids = self._get_scoring_stat_ids(league_settings)
        except Exception as e:
            logger.warning(f"Could not get league settings for scoring category filtering: {e}")

        # Get team names mapping
        team_names = {}
        try:
            teams = await self.get_league_teams()
            team_names = {team.id: team.name for team in teams}
        except Exception as e:
            logger.warning(f"Could not get team names: {e}")

        matchups = []
        for schedule_item in data.get("schedule", []):
            # Now that scoring_period is guaranteed to be set, filter by it
            if schedule_item.get("matchupPeriodId") == scoring_period:
                # Filter by team_id if provided
                home_team_id = schedule_item.get("home", {}).get("teamId")
                away_team_id = schedule_item.get("away", {}).get("teamId")
                
                if team_id is not None:
                    if home_team_id != team_id and away_team_id != team_id:
                        continue  # Skip matchups not involving this team
                
                # Extract team info from home/away data
                home_team = None
                if schedule_item.get("home"):
                    home_data = schedule_item["home"]
                    cumulative_score = home_data.get("cumulativeScore", {})
                    
                    # Convert stat IDs to human-readable category names
                    # cumulativeScore has structure: {"scoreByStat": {"0": {"score": 409.0, ...}, ...}}
                    all_category_scores = {}
                    score_by_stat = cumulative_score.get("scoreByStat", {})
                    if isinstance(score_by_stat, dict):
                        for stat_id, stat_data in score_by_stat.items():
                            if isinstance(stat_data, dict) and "score" in stat_data:
                                score_value = stat_data["score"]
                                category_name = stat_mapping.get(stat_id, f"stat_{stat_id}")
                                all_category_scores[category_name] = score_value
                    
                    # Separate scoring categories from component stats
                    scoring_categories, component_stats = self._filter_category_scores(
                        all_category_scores, scoring_stat_ids, stat_mapping
                    )
                    
                    home_team_id = home_data.get("teamId")
                    home_team = MatchupTeam(
                        teamId=home_team_id,
                        teamName=team_names.get(home_team_id) if home_team_id else None,
                        totalPoints=home_data.get("totalPoints"),
                        totalProjectedPoints=home_data.get("totalProjectedPoints"),
                        gamesPlayed=home_data.get("gamesPlayed"),
                        cumulativeScore=cumulative_score,  # Keep raw data for percentage calculations
                        categoryScores=scoring_categories if scoring_categories else None,
                        componentStats=component_stats if component_stats else None,
                    )

                away_team = None
                if schedule_item.get("away"):
                    away_data = schedule_item["away"]
                    cumulative_score = away_data.get("cumulativeScore", {})
                    
                    # Convert stat IDs to human-readable category names
                    # cumulativeScore has structure: {"scoreByStat": {"0": {"score": 409.0, ...}, ...}}
                    all_category_scores = {}
                    score_by_stat = cumulative_score.get("scoreByStat", {})
                    if isinstance(score_by_stat, dict):
                        for stat_id, stat_data in score_by_stat.items():
                            if isinstance(stat_data, dict) and "score" in stat_data:
                                score_value = stat_data["score"]
                                category_name = stat_mapping.get(stat_id, f"stat_{stat_id}")
                                all_category_scores[category_name] = score_value
                    
                    # Separate scoring categories from component stats
                    scoring_categories, component_stats = self._filter_category_scores(
                        all_category_scores, scoring_stat_ids, stat_mapping
                    )
                    
                    away_team_id = away_data.get("teamId")
                    away_team = MatchupTeam(
                        teamId=away_team_id,
                        teamName=team_names.get(away_team_id) if away_team_id else None,
                        totalPoints=away_data.get("totalPoints"),
                        totalProjectedPoints=away_data.get("totalProjectedPoints"),
                        gamesPlayed=away_data.get("gamesPlayed"),
                        cumulativeScore=cumulative_score,  # Keep raw data for percentage calculations
                        categoryScores=scoring_categories if scoring_categories else None,
                        componentStats=component_stats if component_stats else None,
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

    async def get_my_current_matchup(self, team_id: int, verbose: bool = False) -> CurrentMatchup | None:
        """Get complete current matchup information for a team.
        
        This combines multiple API calls into a single response:
        - Current matchup (filtered by team_id)
        - Your team's roster
        - Opponent's roster
        - Current category scores
        - The week/scoring period
        
        Args:
            team_id: Your team ID
            verbose: If True, include full player stats in rosters.
                     If False, omit player stats from rosters (keeps only lineup info) (default False)
            
        Returns:
            CurrentMatchup object with all matchup data, or None if no current matchup found
        """
        # Get current matchup period and latest scoring period
        league_settings = await self.get_league_settings()
        current_matchup_period = league_settings.status.currentMatchupPeriod
        current_scoring_period = league_settings.status.latestScoringPeriod
        
        # Get matchups for current matchup period, filtered by team_id
        # Note: get_matchups filters by matchupPeriodId, not scoringPeriodId
        matchups = await self.get_matchups(scoring_period=current_matchup_period, team_id=team_id)
        
        if not matchups:
            logger.warning(f"No matchup found for team {team_id} in matchup period {current_matchup_period}")
            return None
        
        # Should only be one matchup for a team in a given period
        matchup = matchups[0]
        
        # Determine which team is "yours" and which is the opponent
        if matchup.home and matchup.home.teamId == team_id:
            your_team_data = matchup.home
            opponent_team_data = matchup.away
        elif matchup.away and matchup.away.teamId == team_id:
            your_team_data = matchup.away
            opponent_team_data = matchup.home
        else:
            logger.error(f"Team {team_id} not found in matchup {matchup.id}")
            return None
        
        if not opponent_team_data or not opponent_team_data.teamId:
            logger.error(f"No opponent found for matchup {matchup.id}")
            return None
        
        # Get rosters for both teams using the actual scoring period
        # Reuse get_team_roster to avoid duplicating roster fetching logic
        # get_team_roster expects scoringPeriodId, not matchupPeriodId
        your_roster = await self.get_team_roster(team_id, scoring_period=current_scoring_period)
        opponent_roster = await self.get_team_roster(opponent_team_data.teamId, scoring_period=current_scoring_period)
        
        # Apply slim roster if not verbose
        if not verbose:
            your_roster = self._make_roster_slim(your_roster)
            opponent_roster = self._make_roster_slim(opponent_roster)
        
            return CurrentMatchup(
            matchupId=matchup.id,
            scoringPeriod=current_scoring_period,
            yourTeam=your_team_data,
            opponentTeam=opponent_team_data,
            yourRoster=your_roster,
            opponentRoster=opponent_roster,
            winner=matchup.winner,
            playoff=matchup.playoff,
        )

    async def get_matchup_for_period(
        self, team_id: int, matchup_period: int, verbose: bool = False
    ) -> CurrentMatchup | None:
        """Get matchup information for a specific matchup period.
        
        Args:
            team_id: Your team ID
            matchup_period: Matchup period to get (e.g., 1, 2, 3...)
            verbose: If True, include full player stats in rosters (default False)
            
        Returns:
            CurrentMatchup object with matchup data, or None if not found
        """
        # Get league settings to determine scoring period for this matchup period
        league_settings = await self.get_league_settings()
        
        # Get matchups for the specified matchup period
        matchups = await self.get_matchups(scoring_period=matchup_period, team_id=team_id)
        
        if not matchups:
            logger.warning(f"No matchup found for team {team_id} in matchup period {matchup_period}")
            return None
        
        # Should only be one matchup for a team in a given period
        matchup = matchups[0]
        
        # Determine which team is "yours" and which is the opponent
        if matchup.home and matchup.home.teamId == team_id:
            your_team_data = matchup.home
            opponent_team_data = matchup.away
        elif matchup.away and matchup.away.teamId == team_id:
            your_team_data = matchup.away
            opponent_team_data = matchup.home
        else:
            logger.error(f"Team {team_id} not found in matchup {matchup.id}")
            return None
        
        if not opponent_team_data or not opponent_team_data.teamId:
            logger.error(f"No opponent found for matchup {matchup.id}")
            return None
        
        # For future matchups, we need to estimate the scoring period
        # Matchup periods typically correspond to weeks, so we can estimate
        # For current/next week, use the latest scoring period
        # For future weeks, estimate based on matchup period
        current_matchup_period = league_settings.status.currentMatchupPeriod
        latest_scoring_period = league_settings.status.latestScoringPeriod
        
        if matchup_period == current_matchup_period:
            # Current week - use latest scoring period
            scoring_period = latest_scoring_period
        elif matchup_period > current_matchup_period:
            # Future week - estimate scoring period (usually matchup period + some offset)
            # This is an approximation; ESPN's scoring periods may not align perfectly
            scoring_period = latest_scoring_period + (matchup_period - current_matchup_period)
        else:
            # Past week - use matchup period as scoring period (approximation)
            scoring_period = matchup_period
        
        # Get rosters for both teams
        your_roster = await self.get_team_roster(team_id, scoring_period=scoring_period)
        opponent_roster = await self.get_team_roster(opponent_team_data.teamId, scoring_period=scoring_period)
        
        # Apply slim roster if not verbose
        if not verbose:
            your_roster = self._make_roster_slim(your_roster)
            opponent_roster = self._make_roster_slim(opponent_roster)
        
        return CurrentMatchup(
            matchupId=matchup.id,
            scoringPeriod=scoring_period,
            yourTeam=your_team_data,
            opponentTeam=opponent_team_data,
            yourRoster=your_roster,
            opponentRoster=opponent_roster,
            winner=matchup.winner,
            playoff=matchup.playoff,
        )

    async def analyze_matchup(
        self, team_id: int, matchup_period: int | None = None
    ) -> MatchupAnalysis:
        """Analyze a matchup and provide strategic recommendations.
        
        By default, analyzes the next matchup (current + 1). Can also analyze
        any other matchup period by specifying matchup_period.
        
        This provides comprehensive analysis including:
        - Category win/loss projections
        - Close categories where decisions matter
        - Player recommendations based on category needs
        - Games remaining analysis
        
        Args:
            team_id: Your team ID
            matchup_period: Matchup period to analyze (defaults to next matchup).
                          Use None for next matchup, or specify a period number (e.g., 1, 2, 3...)
            
        Returns:
            MatchupAnalysis object with detailed matchup analysis
            
        Raises:
            ValueError: If team_id is invalid or no matchup found
        """
        # Determine which matchup period to analyze
        league_settings = await self.get_league_settings()
        current_matchup_period = league_settings.status.currentMatchupPeriod
        
        if matchup_period is None:
            # Default to next matchup
            target_matchup_period = current_matchup_period + 1
        else:
            target_matchup_period = matchup_period
        
        # Get matchup data for the specified period
        matchup = await self.get_matchup_for_period(team_id, target_matchup_period, verbose=True)
        if not matchup:
            period_desc = "next" if matchup_period is None else f"period {matchup_period}"
            raise ValueError(f"No matchup found for team {team_id} in {period_desc} matchup")
        
        # Use league settings already fetched
        scoring_stat_ids = self._get_scoring_stat_ids(league_settings)
        stat_mapping = self._get_stat_id_mapping()
        
        # Get current category scores
        your_category_scores = matchup.yourTeam.categoryScores or {}
        opponent_category_scores = matchup.opponentTeam.categoryScores or {}
        your_projected_points = matchup.yourTeam.totalProjectedPoints or 0.0
        opponent_projected_points = matchup.opponentTeam.totalProjectedPoints or 0.0
        
        # Get roster schedules to determine games remaining
        # Use proper scoring period dates instead of simple date estimation
        from datetime import datetime, timedelta
        
        # Get actual dates for the matchup period using scoring period mapping
        # Matchup periods typically correspond to scoring periods, but we need to map correctly
        # For now, use the matchup period as the scoring period to get dates
        try:
            scoring_start, scoring_end = await self._get_scoring_period_dates(target_matchup_period)
            if scoring_start and scoring_end:
                start_date = scoring_start
                # Extend end_date to cover the full week
                end_date = (datetime.fromisoformat(scoring_end) + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                # Fallback to date estimation if scoring period dates not available
                if target_matchup_period == current_matchup_period:
                    start_date = datetime.now().strftime("%Y-%m-%d")
                elif target_matchup_period > current_matchup_period:
                    weeks_ahead = target_matchup_period - current_matchup_period
                    start_date = (datetime.now() + timedelta(weeks=weeks_ahead)).strftime("%Y-%m-%d")
                else:
                    weeks_back = current_matchup_period - target_matchup_period
                    start_date = (datetime.now() - timedelta(weeks=weeks_back)).strftime("%Y-%m-%d")
                end_date = (datetime.fromisoformat(start_date) + timedelta(days=7)).strftime("%Y-%m-%d")
        except Exception as e:
            logger.warning(f"Could not get scoring period dates, using date estimation: {e}")
            # Fallback to date estimation
            if target_matchup_period == current_matchup_period:
                start_date = datetime.now().strftime("%Y-%m-%d")
            elif target_matchup_period > current_matchup_period:
                weeks_ahead = target_matchup_period - current_matchup_period
                start_date = (datetime.now() + timedelta(weeks=weeks_ahead)).strftime("%Y-%m-%d")
            else:
                weeks_back = current_matchup_period - target_matchup_period
                start_date = (datetime.now() - timedelta(weeks=weeks_back)).strftime("%Y-%m-%d")
            end_date = (datetime.fromisoformat(start_date) + timedelta(days=7)).strftime("%Y-%m-%d")
        
        # Use the matchup period as scoring period for schedule lookup
        your_schedule = await self.get_roster_schedule_summary(
            team_id, start_date, end_date, target_matchup_period
        )
        opponent_team_id = matchup.opponentTeam.teamId
        if not opponent_team_id:
            raise ValueError("Opponent team ID not found in matchup")
        
        opponent_schedule = await self.get_roster_schedule_summary(
            opponent_team_id, start_date, end_date, target_matchup_period
        )
        
        # Get player stats for all players (projections and recent performance)
        your_player_ids = [entry.playerId for entry in matchup.yourRoster.entries]
        opponent_player_ids = [entry.playerId for entry in matchup.opponentRoster.entries]
        all_player_ids = your_player_ids + opponent_player_ids
        
        # Get projections and recent stats
        player_projections = {}
        player_recent_stats = {}
        if all_player_ids:
            try:
                projections_list = await self.get_player_stats(all_player_ids, "projections")
                recent_list = await self.get_player_stats(all_player_ids, "last_7")
                
                # Normalize to lists
                if isinstance(projections_list, list):
                    for stats in projections_list:
                        player_projections[stats.playerId] = stats
                else:
                    player_projections[projections_list.playerId] = projections_list
                
                if isinstance(recent_list, list):
                    for stats in recent_list:
                        player_recent_stats[stats.playerId] = stats
                else:
                    player_recent_stats[recent_list.playerId] = recent_list
            except Exception as e:
                logger.warning(f"Could not get player stats for analysis: {e}")
        
        # Calculate category projections
        category_projections = []
        categories_winning = []
        categories_losing = []
        categories_tied = []
        close_categories = []
        
        # Get current category wins/losses/ties from cumulativeScore
        your_cumulative = matchup.yourTeam.categoryScores or {}
        opponent_cumulative = matchup.opponentTeam.categoryScores or {}
        current_category_wins = 0
        current_category_losses = 0
        current_category_ties = 0
        
        # Calculate per-game averages and project totals
        # Note: totalGamesThisWeek includes all games in the week, but we'll count only future games per player
        your_games_remaining = your_schedule.totalGamesThisWeek
        opponent_games_remaining = opponent_schedule.totalGamesThisWeek
        
        # Import datetime for counting future games
        from datetime import datetime
        today = datetime.now().date()
        
        # Map stat IDs to category names for scoring categories
        reverse_stat_mapping = {v: k for k, v in stat_mapping.items()}
        
        for stat_id in scoring_stat_ids:
            category_name = stat_mapping.get(str(stat_id))
            if not category_name:
                continue
            
            your_current = your_category_scores.get(category_name, 0.0)
            opponent_current = opponent_category_scores.get(category_name, 0.0)
            current_lead = your_current - opponent_current
            
            # Special handling for percentage categories
            is_percentage_category = category_name in ["fieldGoalPercentage", "freeThrowPercentage"]
            
            # For percentage categories, we need to calculate from FGM/FGA or FTM/FTA totals
            if is_percentage_category:
                # Get component stats to calculate current percentages accurately
                # These should contain FGM/FGA/FTM/FTA counts (stat IDs 13, 14, 15, 16)
                your_component_stats = matchup.yourTeam.componentStats or {}
                opponent_component_stats = matchup.opponentTeam.componentStats or {}
                
                # Also try to get raw data from cumulativeScore if available
                # This ensures we get actual counts even if componentStats is missing or incorrect
                your_cumulative_score = matchup.yourTeam.cumulativeScore or {}
                opponent_cumulative_score = matchup.opponentTeam.cumulativeScore or {}
                your_score_by_stat = your_cumulative_score.get("scoreByStat", {}) if isinstance(your_cumulative_score, dict) else {}
                opponent_score_by_stat = opponent_cumulative_score.get("scoreByStat", {}) if isinstance(opponent_cumulative_score, dict) else {}
                
                if category_name == "fieldGoalPercentage":
                    # Get FGM/FGA counts - try componentStats first, then raw API data
                    your_fgm_raw = your_component_stats.get("fieldGoalsMade", 0.0)
                    your_fga_raw = your_component_stats.get("fieldGoalsAttempted", 0.0)
                    opponent_fgm_raw = opponent_component_stats.get("fieldGoalsMade", 0.0)
                    opponent_fga_raw = opponent_component_stats.get("fieldGoalsAttempted", 0.0)
                    
                    # If componentStats doesn't have valid counts, try reading from raw API response
                    if your_fgm_raw < 1.0 or your_fga_raw < 1.0:
                        your_fgm_stat = your_score_by_stat.get("13", {})
                        your_fga_stat = your_score_by_stat.get("14", {})
                        if isinstance(your_fgm_stat, dict) and "score" in your_fgm_stat:
                            your_fgm_raw = your_fgm_stat["score"]
                        if isinstance(your_fga_stat, dict) and "score" in your_fga_stat:
                            your_fga_raw = your_fga_stat["score"]
                    
                    if opponent_fgm_raw < 1.0 or opponent_fga_raw < 1.0:
                        opponent_fgm_stat = opponent_score_by_stat.get("13", {})
                        opponent_fga_stat = opponent_score_by_stat.get("14", {})
                        if isinstance(opponent_fgm_stat, dict) and "score" in opponent_fgm_stat:
                            opponent_fgm_raw = opponent_fgm_stat["score"]
                        if isinstance(opponent_fga_stat, dict) and "score" in opponent_fga_stat:
                            opponent_fga_raw = opponent_fga_stat["score"]
                    
                    # Validate that we have actual counts, not percentages
                    # Counts should be large numbers (>= 1), percentages are < 1
                    # If values look like percentages, treat as missing and use categoryScores percentage
                    your_fgm = your_fgm_raw if your_fgm_raw >= 1.0 else 0.0
                    your_fga = your_fga_raw if your_fga_raw >= 1.0 else 0.0
                    opponent_fgm = opponent_fgm_raw if opponent_fgm_raw >= 1.0 else 0.0
                    opponent_fga = opponent_fga_raw if opponent_fga_raw >= 1.0 else 0.0
                    
                    # Recalculate current percentages from totals if available
                    # This ensures we're using the correct current percentage
                    if your_fga > 0:
                        your_current = your_fgm / your_fga
                    else:
                        # If no FGA counts available, use the percentage from categoryScores
                        your_current = your_category_scores.get(category_name, 0.0)
                    
                    if opponent_fga > 0:
                        opponent_current = opponent_fgm / opponent_fga
                    else:
                        # If no FGA counts available, use the percentage from categoryScores
                        opponent_current = opponent_category_scores.get(category_name, 0.0)
                    
                    # Start projected totals from current counts
                    # Projected = (currentFGM + projectedFGM) / (currentFGA + projectedFGA)
                    your_projected_fgm = your_fgm
                    your_projected_fga = your_fga
                    opponent_projected_fgm = opponent_fgm
                    opponent_projected_fga = opponent_fga
                    
                    # Add projected contributions based on games remaining
                    # For current week, only count games that haven't been played yet
                    from datetime import datetime
                    today = datetime.now().date()
                    
                    for entry in matchup.yourRoster.entries:
                        player_id = entry.playerId
                        player_schedule = next(
                            (ps for ps in your_schedule.playerSchedules if ps.playerId == player_id),
                            None
                        )
                        
                        # Count games remaining (future games only)
                        games_left = 0
                        if player_schedule:
                            for game in player_schedule.games:
                                try:
                                    game_date = datetime.fromisoformat(game.date).date()
                                    if game_date >= today:
                                        games_left += 1
                                except (ValueError, AttributeError):
                                    # If date parsing fails, skip this game
                                    continue
                        
                        if games_left > 0 and player_id in player_projections:
                                proj = player_projections[player_id]
                                # Try to get FGM/FGA from projections
                                # Note: PlayerStats may not include these, so we estimate from FG% and attempts
                                fgm_per_game = getattr(proj, "fieldGoalsMade", None)
                                fga_per_game = getattr(proj, "fieldGoalsAttempted", None)
                                
                                # If not available, estimate from FG% and points (rough estimate)
                                if fgm_per_game is None or fga_per_game is None:
                                    fg_pct = getattr(proj, "fieldGoalPercentage", None)
                                    points_per_game = getattr(proj, "points", None) or 0.0
                                    # Normalize percentage to decimal (PlayerStats stores as whole number 47.8, need 0.478)
                                    if fg_pct is not None:
                                        if fg_pct > 1.0:
                                            fg_pct = fg_pct / 100.0  # Convert from whole number to decimal
                                    # Rough estimate: assume ~2 points per FGM (accounting for 3s and FTs)
                                    if fg_pct and fg_pct > 0:
                                        estimated_fgm = points_per_game / 2.0  # Rough estimate
                                        estimated_fga = estimated_fgm / fg_pct if fg_pct > 0 else 0.0
                                        fgm_per_game = fgm_per_game if fgm_per_game is not None else estimated_fgm
                                        fga_per_game = fga_per_game if fga_per_game is not None else estimated_fga
                                
                                if fgm_per_game is not None and fga_per_game is not None:
                                    your_projected_fgm += fgm_per_game * games_left
                                    your_projected_fga += fga_per_game * games_left
                    
                    # Add projected contributions for opponent
                    for entry in matchup.opponentRoster.entries:
                        player_id = entry.playerId
                        player_schedule = next(
                            (ps for ps in opponent_schedule.playerSchedules if ps.playerId == player_id),
                            None
                        )
                        
                        # Count games remaining (future games only)
                        games_left = 0
                        if player_schedule:
                            for game in player_schedule.games:
                                try:
                                    game_date = datetime.fromisoformat(game.date).date()
                                    if game_date >= today:
                                        games_left += 1
                                except (ValueError, AttributeError):
                                    # If date parsing fails, skip this game
                                    continue
                        
                        if games_left > 0 and player_id in player_projections:
                                proj = player_projections[player_id]
                                # Try to get FGM/FGA from projections
                                fgm_per_game = getattr(proj, "fieldGoalsMade", None)
                                fga_per_game = getattr(proj, "fieldGoalsAttempted", None)
                                
                                # If not available, estimate from FG% and points
                                if fgm_per_game is None or fga_per_game is None:
                                    fg_pct = getattr(proj, "fieldGoalPercentage", None)
                                    points_per_game = getattr(proj, "points", None) or 0.0
                                    # Normalize percentage to decimal (PlayerStats stores as whole number 47.8, need 0.478)
                                    if fg_pct is not None:
                                        if fg_pct > 1.0:
                                            fg_pct = fg_pct / 100.0  # Convert from whole number to decimal
                                    if fg_pct and fg_pct > 0:
                                        estimated_fgm = points_per_game / 2.0  # Rough estimate
                                        estimated_fga = estimated_fgm / fg_pct if fg_pct > 0 else 0.0
                                        fgm_per_game = fgm_per_game if fgm_per_game is not None else estimated_fgm
                                        fga_per_game = fga_per_game if fga_per_game is not None else estimated_fga
                                
                                if fgm_per_game is not None and fga_per_game is not None:
                                    opponent_projected_fgm += fgm_per_game * games_left
                                    opponent_projected_fga += fga_per_game * games_left
                    
                    # Calculate projected percentages using weighted average formula
                    # Projected = (currentFGM + projectedFGM) / (currentFGA + projectedFGA)
                    if your_projected_fga > 0:
                        your_projected = your_projected_fgm / your_projected_fga
                    else:
                        # If no FGA projected, use current percentage
                        your_projected = your_current
                    
                    if opponent_projected_fga > 0:
                        opponent_projected = opponent_projected_fgm / opponent_projected_fga
                    else:
                        # If no FGA projected, use current percentage
                        opponent_projected = opponent_current
                    
                elif category_name == "freeThrowPercentage":
                    # Get FTM/FTA counts - try componentStats first, then raw API data
                    your_ftm_raw = your_component_stats.get("freeThrowsMade", 0.0)
                    your_fta_raw = your_component_stats.get("freeThrowsAttempted", 0.0)
                    opponent_ftm_raw = opponent_component_stats.get("freeThrowsMade", 0.0)
                    opponent_fta_raw = opponent_component_stats.get("freeThrowsAttempted", 0.0)
                    
                    # If componentStats doesn't have valid counts, try reading from raw API response
                    if your_ftm_raw < 1.0 or your_fta_raw < 1.0:
                        your_ftm_stat = your_score_by_stat.get("15", {})
                        your_fta_stat = your_score_by_stat.get("16", {})
                        if isinstance(your_ftm_stat, dict) and "score" in your_ftm_stat:
                            your_ftm_raw = your_ftm_stat["score"]
                        if isinstance(your_fta_stat, dict) and "score" in your_fta_stat:
                            your_fta_raw = your_fta_stat["score"]
                    
                    if opponent_ftm_raw < 1.0 or opponent_fta_raw < 1.0:
                        opponent_ftm_stat = opponent_score_by_stat.get("15", {})
                        opponent_fta_stat = opponent_score_by_stat.get("16", {})
                        if isinstance(opponent_ftm_stat, dict) and "score" in opponent_ftm_stat:
                            opponent_ftm_raw = opponent_ftm_stat["score"]
                        if isinstance(opponent_fta_stat, dict) and "score" in opponent_fta_stat:
                            opponent_fta_raw = opponent_fta_stat["score"]
                    
                    # Validate that we have actual counts, not percentages
                    # Counts should be large numbers (>= 1), percentages are < 1
                    # If values look like percentages, treat as missing and use categoryScores percentage
                    your_ftm = your_ftm_raw if your_ftm_raw >= 1.0 else 0.0
                    your_fta = your_fta_raw if your_fta_raw >= 1.0 else 0.0
                    opponent_ftm = opponent_ftm_raw if opponent_ftm_raw >= 1.0 else 0.0
                    opponent_fta = opponent_fta_raw if opponent_fta_raw >= 1.0 else 0.0
                    
                    # Recalculate current percentages from totals if available
                    if your_fta > 0:
                        your_current = your_ftm / your_fta
                    else:
                        # If no FTA counts available, use the percentage from categoryScores
                        your_current = your_category_scores.get(category_name, 0.0)
                    
                    if opponent_fta > 0:
                        opponent_current = opponent_ftm / opponent_fta
                    else:
                        # If no FTA counts available, use the percentage from categoryScores
                        opponent_current = opponent_category_scores.get(category_name, 0.0)
                    
                    # Start projected totals from current counts
                    # Projected = (currentFTM + projectedFTM) / (currentFTA + projectedFTA)
                    your_projected_ftm = your_ftm
                    your_projected_fta = your_fta
                    opponent_projected_ftm = opponent_ftm
                    opponent_projected_fta = opponent_fta
                    
                    # Add projected contributions based on games remaining
                    # For current week, only count games that haven't been played yet
                    for entry in matchup.yourRoster.entries:
                        player_id = entry.playerId
                        player_schedule = next(
                            (ps for ps in your_schedule.playerSchedules if ps.playerId == player_id),
                            None
                        )
                        
                        # Count games remaining (future games only)
                        games_left = 0
                        if player_schedule:
                            for game in player_schedule.games:
                                try:
                                    game_date = datetime.fromisoformat(game.date).date()
                                    if game_date >= today:
                                        games_left += 1
                                except (ValueError, AttributeError):
                                    # If date parsing fails, skip this game
                                    continue
                        
                        if games_left > 0 and player_id in player_projections:
                            proj = player_projections[player_id]
                            # Try to get FTM/FTA from projections
                            ftm_per_game = getattr(proj, "freeThrowsMade", None)
                            fta_per_game = getattr(proj, "freeThrowsAttempted", None)
                            
                            # If not available, estimate from FT% and points/assists (players who drive get more FTs)
                            if ftm_per_game is None or fta_per_game is None:
                                ft_pct = getattr(proj, "freeThrowPercentage", None)
                                points_per_game = getattr(proj, "points", None) or 0.0
                                # Normalize percentage to decimal (PlayerStats stores as whole number 75.3, need 0.753)
                                if ft_pct is not None:
                                    if ft_pct > 1.0:
                                        ft_pct = ft_pct / 100.0  # Convert from whole number to decimal
                                # Rough estimate: assume ~20% of points come from FTs, so ~0.2 * points = FTM
                                if ft_pct and ft_pct > 0:
                                    estimated_ftm = points_per_game * 0.2  # Rough estimate
                                    estimated_fta = estimated_ftm / ft_pct if ft_pct > 0 else 0.0
                                    ftm_per_game = ftm_per_game if ftm_per_game is not None else estimated_ftm
                                    fta_per_game = fta_per_game if fta_per_game is not None else estimated_fta
                            
                            if ftm_per_game is not None and fta_per_game is not None:
                                your_projected_ftm += ftm_per_game * games_left
                                your_projected_fta += fta_per_game * games_left
                    
                    # Add projected contributions for opponent
                    for entry in matchup.opponentRoster.entries:
                        player_id = entry.playerId
                        player_schedule = next(
                            (ps for ps in opponent_schedule.playerSchedules if ps.playerId == player_id),
                            None
                        )
                        
                        # Count games remaining (future games only)
                        games_left = 0
                        if player_schedule:
                            for game in player_schedule.games:
                                try:
                                    game_date = datetime.fromisoformat(game.date).date()
                                    if game_date >= today:
                                        games_left += 1
                                except (ValueError, AttributeError):
                                    # If date parsing fails, skip this game
                                    continue
                        
                        if games_left > 0 and player_id in player_projections:
                            proj = player_projections[player_id]
                            # Try to get FTM/FTA from projections
                            ftm_per_game = getattr(proj, "freeThrowsMade", None)
                            fta_per_game = getattr(proj, "freeThrowsAttempted", None)
                            
                            # If not available, estimate from FT% and points
                            if ftm_per_game is None or fta_per_game is None:
                                ft_pct = getattr(proj, "freeThrowPercentage", None)
                                points_per_game = getattr(proj, "points", None) or 0.0
                                # Normalize percentage to decimal (PlayerStats stores as whole number 75.3, need 0.753)
                                if ft_pct is not None:
                                    if ft_pct > 1.0:
                                        ft_pct = ft_pct / 100.0  # Convert from whole number to decimal
                                if ft_pct and ft_pct > 0:
                                    estimated_ftm = points_per_game * 0.2  # Rough estimate
                                    estimated_fta = estimated_ftm / ft_pct if ft_pct > 0 else 0.0
                                    ftm_per_game = ftm_per_game if ftm_per_game is not None else estimated_ftm
                                    fta_per_game = fta_per_game if fta_per_game is not None else estimated_fta
                            
                            if ftm_per_game is not None and fta_per_game is not None:
                                opponent_projected_ftm += ftm_per_game * games_left
                                opponent_projected_fta += fta_per_game * games_left
                    
                    # Calculate projected percentages using weighted average formula
                    # Projected = (currentFTM + projectedFTM) / (currentFTA + projectedFTA)
                    if your_projected_fta > 0:
                        your_projected = your_projected_ftm / your_projected_fta
                    else:
                        # If no FTA projected, use current percentage
                        your_projected = your_current
                    
                    if opponent_projected_fta > 0:
                        opponent_projected = opponent_projected_ftm / opponent_projected_fta
                    else:
                        # If no FTA projected, use current percentage
                        opponent_projected = opponent_current
                
                # Recalculate current_lead with accurate percentages
                current_lead = your_current - opponent_current
                
            else:
                # For non-percentage categories, use additive projection
                # Always calculate projections based on games remaining and player averages
                your_projected_add = 0.0
                opponent_projected_add = 0.0
                
                # Calculate projections for your team
                for entry in matchup.yourRoster.entries:
                    player_id = entry.playerId
                    player_schedule = next(
                        (ps for ps in your_schedule.playerSchedules if ps.playerId == player_id),
                        None
                    )
                    games_left = player_schedule.gamesThisWeek if player_schedule else 0
                    
                    if games_left > 0 and player_id in player_projections:
                        proj = player_projections[player_id]
                        # Get per-game average for this category
                        category_value = getattr(proj, category_name, None)
                        if category_value is not None:
                            # Add projected contribution: per-game average * games remaining
                            your_projected_add += category_value * games_left
                
                # Calculate projections for opponent team
                for entry in matchup.opponentRoster.entries:
                    player_id = entry.playerId
                    player_schedule = next(
                        (ps for ps in opponent_schedule.playerSchedules if ps.playerId == player_id),
                        None
                    )
                    games_left = player_schedule.gamesThisWeek if player_schedule else 0
                    
                    if games_left > 0 and player_id in player_projections:
                        proj = player_projections[player_id]
                        category_value = getattr(proj, category_name, None)
                        if category_value is not None:
                            # Add projected contribution: per-game average * games remaining
                            opponent_projected_add += category_value * games_left
                
                # Projections = current score + (games remaining × player averages)
                your_projected = your_current + your_projected_add
                opponent_projected = opponent_current + opponent_projected_add
            
            projected_lead = your_projected - opponent_projected if your_projected is not None and opponent_projected is not None else None
            
            # Determine projected result with appropriate thresholds
            projected_result = None
            margin = None
            is_close = False
            
            if projected_lead is not None:
                margin = abs(projected_lead)
                
                # Use much smaller threshold for percentage categories
                if is_percentage_category:
                    # For percentages, use 0.002 (0.2 percentage points) as threshold
                    threshold = 0.002
                    is_close = margin <= threshold
                    
                    if projected_lead > 0.002:
                        projected_result = "win"
                        categories_winning.append(category_name)
                    elif projected_lead < -0.002:
                        projected_result = "loss"
                        categories_losing.append(category_name)
                    else:
                        projected_result = "tie"
                        categories_tied.append(category_name)
                else:
                    # For non-percentage categories, use original logic
                    threshold = max(abs(your_current) * 0.05, 2.0)  # 5% or minimum 2.0
                    is_close = margin <= threshold
                    
                    if projected_lead > 0.1:
                        projected_result = "win"
                        categories_winning.append(category_name)
                    elif projected_lead < -0.1:
                        projected_result = "loss"
                        categories_losing.append(category_name)
                    else:
                        projected_result = "tie"
                        categories_tied.append(category_name)
                
                if is_close:
                    close_categories.append(category_name)
            
            # Track current category wins/losses/ties with appropriate thresholds
            if is_percentage_category:
                # Use smaller threshold for percentage categories
                if current_lead > 0.002:
                    current_category_wins += 1
                elif current_lead < -0.002:
                    current_category_losses += 1
                else:
                    current_category_ties += 1
            else:
                # Use original threshold for non-percentage categories
                if current_lead > 0.1:
                    current_category_wins += 1
                elif current_lead < -0.1:
                    current_category_losses += 1
                else:
                    current_category_ties += 1
            
            # Always include projections, even if they equal current (for future matchups, current is 0)
            category_projections.append(CategoryProjection(
                category=category_name,
                yourCurrent=your_current,
                opponentCurrent=opponent_current,
                yourProjected=your_projected,
                opponentProjected=opponent_projected,
                currentLead=current_lead,
                projectedLead=projected_lead,
                projectedResult=projected_result,
                margin=margin,
                isClose=is_close,
            ))
        
        # Generate player recommendations
        player_recommendations = []
        
        # Create a map of player schedules for quick lookup
        your_player_schedules = {ps.playerId: ps for ps in your_schedule.playerSchedules}
        
        for entry in matchup.yourRoster.entries:
            player_id = entry.playerId
            player = entry.playerPoolEntry.player
            player_schedule = your_player_schedules.get(player_id)
            games_remaining = player_schedule.gamesThisWeek if player_schedule else 0
            
            # Skip players with no games remaining or on IR
            if games_remaining == 0 or entry.lineupSlotId == 13:  # IR slot
                continue
            
            # Get player stats
            proj_stats = player_projections.get(player_id)
            recent_stats = player_recent_stats.get(player_id)
            
            if not proj_stats:
                continue
            
            # Determine which categories this player helps with
            categories_helped = []
            categories_hurt = []
            priority_score = 5  # Base priority
            
            # Check each close category or category we're losing
            relevant_categories = set(close_categories + categories_losing)
            
            for category in relevant_categories:
                category_value = getattr(proj_stats, category, None)
                if category_value is None:
                    continue
                
                # Check if this player helps in this category
                if category == "turnovers":
                    # Lower turnovers is better
                    if category_value < 3.0:  # Low turnover player
                        categories_helped.append(category)
                        priority_score += 2
                    elif category_value > 4.0:  # High turnover player
                        categories_hurt.append(category)
                        priority_score -= 1
                elif category in ["fieldGoalPercentage", "freeThrowPercentage"]:
                    # Higher percentage is better
                    if category_value > 0.45:  # Good shooter
                        categories_helped.append(category)
                        priority_score += 1
                    elif category_value < 0.40:  # Poor shooter
                        categories_hurt.append(category)
                        priority_score -= 1
                else:
                    # Higher is better for most categories
                    # Compare to league average (rough estimates)
                    thresholds = {
                        "points": 15.0,
                        "rebounds": 6.0,
                        "assists": 4.0,
                        "steals": 1.0,
                        "blocks": 0.8,
                        "threePointMade": 1.5,
                    }
                    threshold = thresholds.get(category, 5.0)
                    
                    if category_value >= threshold:
                        categories_helped.append(category)
                        priority_score += 2
                    elif category_value < threshold * 0.7:
                        categories_hurt.append(category)
                        priority_score -= 1
            
            # Boost priority for players with more games remaining
            if games_remaining >= 3:
                priority_score += 2
            elif games_remaining == 2:
                priority_score += 1
            
            # Boost priority if player helps in multiple categories
            if len(categories_helped) >= 3:
                priority_score += 2
            elif len(categories_helped) >= 2:
                priority_score += 1
            
            # Cap priority between 1-10
            priority_score = max(1, min(10, priority_score))
            
            # Build reasoning
            reasoning_parts = []
            if categories_helped:
                reasoning_parts.append(f"Strong in: {', '.join(categories_helped)}")
            if games_remaining >= 3:
                reasoning_parts.append(f"{games_remaining} games remaining")
            if not reasoning_parts:
                reasoning_parts.append("Active player")
            
            reasoning = ". ".join(reasoning_parts)
            
            # Get lineup slot name
            lineup_slot_name = None
            if entry.lineupSlotName:
                lineup_slot_name = entry.lineupSlotName
            else:
                lineup_slot_mapping = self._get_lineup_slot_id_mapping()
                lineup_slot_name = lineup_slot_mapping.get(entry.lineupSlotId, f"SLOT_{entry.lineupSlotId}")
            
            player_recommendations.append(PlayerRecommendation(
                playerId=player_id,
                playerName=player.fullName,
                position=player.defaultPosition,
                lineupSlotId=entry.lineupSlotId,
                lineupSlotName=lineup_slot_name,
                gamesRemaining=games_remaining,
                priority=priority_score,
                reasoning=reasoning,
                categoriesHelped=categories_helped,
                categoriesHurt=categories_hurt,
                injuryStatus=entry.injuryStatus,
                todaysGame=entry.todaysGame,
            ))
        
        # Sort recommendations by priority (highest first)
        player_recommendations.sort(key=lambda x: x.priority, reverse=True)
        
        # Generate strategy notes
        strategy_notes = []
        
        # Calculate projected category record
        projected_category_wins = len(categories_winning)
        projected_category_losses = len(categories_losing)
        
        if projected_category_wins > projected_category_losses:
            strategy_notes.append(f"Projected to win {projected_category_wins}-{projected_category_losses}")
        elif projected_category_losses > projected_category_wins:
            strategy_notes.append(f"Currently trailing, projected {projected_category_wins}-{projected_category_losses}")
        else:
            strategy_notes.append(f"Projected tie at {projected_category_wins}-{projected_category_wins}")
        
        if close_categories:
            strategy_notes.append(f"Focus on {len(close_categories)} close categories: {', '.join(close_categories)}")
        
        if your_games_remaining > opponent_games_remaining:
            strategy_notes.append(f"You have {your_games_remaining - opponent_games_remaining} more games remaining - advantage")
        elif opponent_games_remaining > your_games_remaining:
            strategy_notes.append(f"Opponent has {opponent_games_remaining - your_games_remaining} more games remaining - consider streaming")
        
        if categories_losing:
            strategy_notes.append(f"Prioritize players who help in: {', '.join(categories_losing[:3])}")
        
        return MatchupAnalysis(
            matchupId=matchup.matchupId,
            scoringPeriod=matchup.scoringPeriod,
            yourTeamId=team_id,
            opponentTeamId=opponent_team_id,
            yourTeamName=matchup.yourTeam.teamName,
            opponentTeamName=matchup.opponentTeam.teamName,
            categoryProjections=category_projections,
            categoriesWinning=categories_winning,
            categoriesLosing=categories_losing,
            categoriesTied=categories_tied,
            closeCategories=close_categories,
            playerRecommendations=player_recommendations,
            yourGamesRemaining=your_games_remaining,
            opponentGamesRemaining=opponent_games_remaining,
            currentCategoryWins=current_category_wins,
            currentCategoryLosses=current_category_losses,
            currentCategoryTies=current_category_ties,
            projectedCategoryWins=projected_category_wins,
            projectedCategoryLosses=projected_category_losses,
            strategyNotes=strategy_notes,
        )

    async def get_team_season_stats(self, team_id: int) -> TeamSeasonStats:
        """Get team statistics aggregated across the entire season.
        
        This aggregates stats from all matchups in the season for a specific team.
        
        Args:
            team_id: Team ID to get season stats for
            
        Returns:
            TeamSeasonStats object with aggregated season statistics
            
        Raises:
            ValueError: If team_id is invalid or team not found
        """
        # Validate input
        self._validate_positive_int(team_id, "team_id")
        
        # Get league settings to determine scoring categories
        league_settings = await self.get_league_settings()
        stat_mapping = self._get_stat_id_mapping()
        scoring_stat_ids = self._get_scoring_stat_ids(league_settings)
        
        # Get current matchup period to exclude incomplete/current week data
        current_matchup_period = league_settings.status.currentMatchupPeriod
        
        # Get all matchups for the season (no scoring_period filter)
        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        params = {"view": "mMatchup"}
        
        data = await self._make_request(url, params)
        
        # Get team name
        team_name = None
        try:
            teams = await self.get_league_teams()
            team = next((t for t in teams if t.id == team_id), None)
            if team:
                team_name = team.name
        except Exception as e:
            logger.warning(f"Could not get team name: {e}")
        
        # Get team record from API (more reliable than calculating from matchups)
        # This only includes completed matchups, not the current week
        matchup_wins = None
        matchup_losses = None
        matchup_ties = 0  # Start at 0, will count from completed matchups only
        
        try:
            teams = await self.get_league_teams()
            team = next((t for t in teams if t.id == team_id), None)
            if team and team.record and team.record.overall:
                matchup_wins = team.record.overall.wins
                matchup_losses = team.record.overall.losses
        except Exception as e:
            logger.warning(f"Could not get team record from API: {e}")
        
        # Track records for all teams to calculate games back
        team_records: dict[int, dict[str, int]] = {}  # team_id -> {wins, losses, ties}
        
        # Aggregate stats across all matchups
        # Track component stats separately for percentage calculations
        aggregated_category_scores: dict[str, float] = {}
        aggregated_component_stats: dict[str, float] = {}
        total_games_played = 0
        
        # Track totals for percentage calculations
        field_goals_made = 0.0
        field_goals_attempted = 0.0
        free_throws_made = 0.0
        free_throws_attempted = 0.0
        
        for schedule_item in data.get("schedule", []):
            home_data = schedule_item.get("home", {})
            away_data = schedule_item.get("away", {})
            
            # Check if this matchup involves our team
            home_team_id = home_data.get("teamId")
            away_team_id = away_data.get("teamId")
            
            if home_team_id != team_id and away_team_id != team_id:
                continue  # Skip matchups not involving this team
            
            # Determine which team data to use
            team_data = home_data if home_team_id == team_id else away_data
            
            # Aggregate category scores and component stats
            if team_data.get("cumulativeScore"):
                cumulative_score = team_data.get("cumulativeScore", {})
                score_by_stat = cumulative_score.get("scoreByStat", {})
                if isinstance(score_by_stat, dict):
                    for stat_id, stat_data in score_by_stat.items():
                        if isinstance(stat_data, dict) and "score" in stat_data:
                            score_value = stat_data["score"]
                            category_name = stat_mapping.get(stat_id, f"stat_{stat_id}")
                            
                            # Track component stats for percentage calculations
                            if stat_id == "13":  # Field Goals Made
                                field_goals_made += score_value
                            elif stat_id == "14":  # Field Goals Attempted
                                field_goals_attempted += score_value
                            elif stat_id == "15":  # Free Throws Made
                                free_throws_made += score_value
                            elif stat_id == "16":  # Free Throws Attempted
                                free_throws_attempted += score_value
                            
                            # Points (stat ID 0) should always be in categoryScores
                            # Separate scoring categories from component stats
                            stat_id_int = int(stat_id) if stat_id.isdigit() else None
                            if stat_id == "0" or (stat_id_int and stat_id_int in scoring_stat_ids):
                                # This is a scoring category (including points) - aggregate it
                                if category_name not in aggregated_category_scores:
                                    aggregated_category_scores[category_name] = 0.0
                                aggregated_category_scores[category_name] += score_value
                            else:
                                # This is a component stat - aggregate it
                                if category_name not in aggregated_component_stats:
                                    aggregated_component_stats[category_name] = 0.0
                                aggregated_component_stats[category_name] += score_value
            
            # Aggregate games played - TODO: this is not returning the right data, it looks like the API is just returning 0 for all matchups
            games_played = team_data.get("gamesPlayed", 0)
            if games_played:
                total_games_played += games_played
            
            # Track records for all teams to calculate games back
            winner = schedule_item.get("winner")
            
            # Initialize team records if not present
            if home_team_id and home_team_id not in team_records:
                team_records[home_team_id] = {"wins": 0, "losses": 0, "ties": 0}
            if away_team_id and away_team_id not in team_records:
                team_records[away_team_id] = {"wins": 0, "losses": 0, "ties": 0}
            
            # Get cumulativeScore data for both teams
            home_cumulative = home_data.get("cumulativeScore", {})
            away_cumulative = away_data.get("cumulativeScore", {})
            
            # Only count ties from completed matchups (exclude current matchup period)
            # This matches the timeline used for wins/losses from team.record.overall
            matchup_period_id = schedule_item.get("matchupPeriodId")
            is_completed_matchup = matchup_period_id is not None and matchup_period_id < current_matchup_period
            
            if is_completed_matchup:
                # Sum up cumulativeScore.ties for the requested team from completed matchups only
                # cumulativeScore.ties indicates matchup-level ties (not category ties)
                if home_team_id == team_id:
                    home_matchup_ties = home_cumulative.get("ties", 0)
                    if home_matchup_ties > 0:
                        matchup_ties += home_matchup_ties
                elif away_team_id == team_id:
                    away_matchup_ties = away_cumulative.get("ties", 0)
                    if away_matchup_ties > 0:
                        matchup_ties += away_matchup_ties
            
            # Also track for games back calculation
            home_category_wins = home_cumulative.get("wins", 0)
            away_category_wins = away_cumulative.get("wins", 0)
            
            # Determine winner and update records for games back calculation
            if winner == "HOME":
                if home_team_id:
                    team_records[home_team_id]["wins"] += 1
                if away_team_id:
                    team_records[away_team_id]["losses"] += 1
            elif winner == "AWAY":
                if away_team_id:
                    team_records[away_team_id]["wins"] += 1
                if home_team_id:
                    team_records[home_team_id]["losses"] += 1
            elif home_category_wins == away_category_wins and home_category_wins > 0:
                # Matchup tie: both teams won the same number of categories
                if home_team_id:
                    team_records[home_team_id]["ties"] += 1
                if away_team_id:
                    team_records[away_team_id]["ties"] += 1
            else:
                # Incomplete matchup or no winner determined
                # Fallback: check if we can determine winner from total points (points leagues)
                home_total = home_data.get("totalPoints")
                away_total = away_data.get("totalPoints")
                if home_total is not None and away_total is not None:
                    if home_total == away_total and home_total > 0:
                        # Actual tie based on points
                        if home_team_id:
                            team_records[home_team_id]["ties"] += 1
                        if away_team_id:
                            team_records[away_team_id]["ties"] += 1
                    elif home_total > away_total:
                        if home_team_id:
                            team_records[home_team_id]["wins"] += 1
                        if away_team_id:
                            team_records[away_team_id]["losses"] += 1
                    elif away_total > home_total:
                        if away_team_id:
                            team_records[away_team_id]["wins"] += 1
                        if home_team_id:
                            team_records[home_team_id]["losses"] += 1
        
        # Calculate percentages from season totals
        if field_goals_attempted > 0:
            field_goal_percentage = field_goals_made / field_goals_attempted
            aggregated_category_scores["fieldGoalPercentage"] = field_goal_percentage
            # Remove from component stats if it was there
            aggregated_component_stats.pop("fieldGoalPercentage", None)
        
        if free_throws_attempted > 0:
            free_throw_percentage = free_throws_made / free_throws_attempted
            aggregated_category_scores["freeThrowPercentage"] = free_throw_percentage
            # Remove from component stats if it was there
            aggregated_component_stats.pop("freeThrowPercentage", None)
        
        # Ensure points is in categoryScores, not componentStats
        if "points" in aggregated_component_stats:
            points_value = aggregated_component_stats.pop("points")
            aggregated_category_scores["points"] = points_value
        
        # Calculate win percentage (excludes ties: W/(W+L))
        win_percentage = None
        if matchup_wins is not None and matchup_losses is not None:
            total_decided_matchups = matchup_wins + matchup_losses
            if total_decided_matchups > 0:
                win_percentage = matchup_wins / total_decided_matchups
        
        # Calculate games back using team records from API
        games_back = None
        if matchup_wins is not None and matchup_losses is not None:
            try:
                teams = await self.get_league_teams()
                
                # Find leader: most wins, then fewest losses
                leader_wins = -1
                leader_losses = float('inf')
                
                for team in teams:
                    if team.record and team.record.overall:
                        wins = team.record.overall.wins
                        losses = team.record.overall.losses
                        # Leader is team with most wins, or if tied, fewest losses
                        if wins > leader_wins or (wins == leader_wins and losses < leader_losses):
                            leader_wins = wins
                            leader_losses = losses
                
                # Calculate games back for the requested team
                if leader_wins >= 0:
                    if matchup_wins == leader_wins and matchup_losses == leader_losses:
                        # This team is tied for the lead
                        games_back = 0.0
                    else:
                        # Games back = ((Leader's wins - Team's wins) + (Team's losses - Leader's losses)) / 2
                        games_back = ((leader_wins - matchup_wins) + (matchup_losses - leader_losses)) / 2.0
            except Exception as e:
                logger.warning(f"Could not calculate games back: {e}")
        
        return TeamSeasonStats(
            teamId=team_id,
            teamName=team_name,
            categoryScores=aggregated_category_scores,
            componentStats=aggregated_component_stats if aggregated_component_stats else None,
            totalGamesPlayed=total_games_played if total_games_played > 0 else None,
            matchupWins=matchup_wins,
            matchupLosses=matchup_losses,
            matchupTies=matchup_ties if matchup_ties > 0 else None,
            winPercentage=win_percentage,
            gamesBack=games_back,
        )

    async def get_nba_schedule(self, date: str | None = None) -> list[NBAGame]:
        """Get NBA schedule.

        Args:
            date: Date in YYYY-MM-DD format (optional, defaults to today).
                  The API accepts dates in YYYYMMDD format (no dashes) via the 'date' parameter.

        Returns:
            List of NBA games, or empty list if API fails
        """
        url = f"{self.NBA_BASE_URL}/scoreboard"
        params = {}

        if date:
            # Validate and convert date format
            import re
            from datetime import datetime
            
            # Accept YYYY-MM-DD format
            if re.match(r'^\d{4}-\d{2}-\d{2}$', date):
                # Convert to YYYYMMDD format (no dashes) for API
                date_obj = datetime.strptime(date, "%Y-%m-%d")
                date_formatted = date_obj.strftime("%Y%m%d")
                # Use 'date' parameter (not 'dates') with YYYYMMDD format
                params["date"] = date_formatted
            elif re.match(r'^\d{8}$', date):
                # Already in YYYYMMDD format
                params["date"] = date
            else:
                raise ValueError(f"Invalid date format: {date}. Must be YYYY-MM-DD or YYYYMMDD.")
        else:
            # Don't pass date parameter - API defaults to today's games
            pass

        try:
            data = await self._make_request(url, params)

            games = []
            for event in data.get("events", []):
                # Convert UTC date to timezone specified by MY_TIMEZONE
                date_str = event.get("date", "")
                date_iso = self._convert_utc_to_timezone_iso(date_str)
                
                game = NBAGame(
                    id=event["id"], date=date_iso, competitions=event["competitions"]
                )
                games.append(game)

            return games
        except httpx.HTTPError as e:
            # If explicit date fails, try without date parameter (defaults to today)
            if date and "400" in str(e):
                logger.debug(f"NBA API rejected explicit date {date}, trying without date parameter")
                try:
                    # Try without date parameter - API defaults to today
                    data = await self._make_request(url, {})
                    games = []
                    for event in data.get("events", []):
                        # Convert UTC date to timezone specified by MY_TIMEZONE
                        date_str = event.get("date", "")
                        date_iso = self._convert_utc_to_timezone_iso(date_str)
                        
                        game = NBAGame(
                            id=event["id"], date=date_iso, competitions=event["competitions"]
                        )
                        games.append(game)
                    logger.warning(f"NBA API doesn't accept explicit dates. Returned today's games instead of {date}")
                    return games
                except Exception:
                    pass
            
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

            # Use consistent fallback logic for team abbreviation
            pro_team_id = player_data.get("proTeamId")
            pro_team_abbrev = self._resolve_pro_team_abbrev(
                pro_team_id,
                player_data.get("proTeamAbbrev")
            )
            pro_team_name = player_data.get("proTeamName")
            
            # Map position and slot IDs to names
            position_mapping = self._get_position_id_mapping()
            slot_mapping = self._get_lineup_slot_id_mapping()
            default_position_id = player_data["defaultPositionId"]
            default_position = position_mapping.get(default_position_id)
            
            eligible_slots = player_data.get("eligibleSlots")
            eligible_slot_names = None
            if eligible_slots:
                eligible_slot_names = [slot_mapping.get(slot_id, f"SLOT_{slot_id}") for slot_id in eligible_slots]
            
            player = Player(
                id=player_id,
                fullName=player_data.get("fullName", ""),
                firstName=player_data.get("firstName", ""),
                lastName=player_data.get("lastName", ""),
                defaultPositionId=default_position_id,
                defaultPosition=default_position,
                eligibleSlots=eligible_slots,
                eligibleSlotNames=eligible_slot_names,
                proTeamId=pro_team_id,
                proTeamAbbrev=pro_team_abbrev,
                proTeamName=pro_team_name,
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

    async def get_player_stats(
        self, 
        player_id: int | list[int], 
        timeframe: str = "season"
    ) -> PlayerStats | list[PlayerStats]:
        """Get comprehensive player statistics for one or more players.
        
        Can be called with a single player ID (returns PlayerStats) or a list of 
        player IDs (returns list[PlayerStats]). Using a list is more efficient as 
        it makes a single API request for all players.

        Args:
            player_id: ESPN player ID (int) or list of player IDs (list[int])
            timeframe: One of "season", "projections", "last_7", "last_15", "last_30"

        Returns:
            PlayerStats if single ID provided, list[PlayerStats] if list provided

        Raises:
            ValueError: If player_id or timeframe is invalid, or player(s) not found
        """
        # Normalize to list for processing
        is_single = isinstance(player_id, int)
        player_ids = [player_id] if is_single else player_id
        
        if not player_ids:
            raise ValueError("player_id cannot be empty")
        
        # Validate all player IDs
        for pid in player_ids:
            self._validate_positive_int(pid, "player_id")

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

        # Build filter to request players with stats
        filter_dict = {
            "players": {
                "filterIds": {"value": player_ids},
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

        # Process all players returned in the response
        results = []
        found_player_ids = set()
        
        for player_entry in data.get("players", []):
            player_info = player_entry.get("player", {})
            pid = player_info.get("id")
            
            if pid not in player_ids:
                continue  # Skip players not in our requested list
            
            found_player_ids.add(pid)
            
            # Parse stats for the requested timeframe
            stats_dict = self._parse_player_stats_for_timeframe(
                player_info.get("stats", []), 
                timeframe
            )

            results.append(PlayerStats(
                playerId=pid,
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
            ))
        
        # Log warning for any players not found
        missing_ids = set(player_ids) - found_player_ids
        if missing_ids:
            logger.warning(f"Players with IDs {missing_ids} not found in API response")
        
        if not results:
            raise ValueError("No players found")
        
        # Return single PlayerStats if single ID was provided, otherwise return list
        return results[0] if is_single else results

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

    @staticmethod
    def _get_stat_id_mapping() -> dict[str, str]:
        """Get mapping of ESPN stat IDs to human-readable category names.
        
        ESPN stat ID mapping: 0=PTS, 1=BLK, 2=STL, 3=AST, 6=REB
        
        Returns:
            Dictionary mapping stat ID strings to category names
        """
        return {
            "0": "points",  # Points
            "1": "blocks",  # Blocks
            "2": "steals",  # Steals
            "3": "assists",  # Assists
            "4": "offensiveRebounds",  # Offensive Rebounds (less common in matchups)
            "6": "rebounds",  # Rebounds (total rebounds)
            "11": "turnovers",  # Turnovers
            "13": "fieldGoalsMade",  # Field Goals Made
            "14": "fieldGoalsAttempted",  # Field Goals Attempted
            "15": "freeThrowsMade",  # Free Throws Made
            "16": "freeThrowsAttempted",  # Free Throws Attempted
            "17": "threePointMade",  # 3PM
            "19": "fieldGoalPercentage",  # FG%
            "20": "freeThrowPercentage",  # FT%
            "40": "minutes",  # Minutes
            "gamesPlayed": "gamesPlayed",
        }
    
    @staticmethod
    def _get_lineup_slot_id_mapping() -> dict[int, str]:
        """Get mapping of ESPN lineup slot IDs to human-readable slot names.
        
        This includes both position slots (0-6) and special slots (7, 11-13).
        Position IDs and lineup slot IDs use the same values for positions.
        
        Returns:
            Dictionary mapping slot ID integers to slot names
        """
        return {
            0: "PG",   # Point Guard
            1: "SG",   # Shooting Guard
            2: "SF",   # Small Forward
            3: "PF",   # Power Forward
            4: "C",    # Center
            5: "G",    # Guard (PG or SG)
            6: "F",    # Forward (SF or PF)
            7: "UTIL", # Utility
            11: "UTIL", # Utility (alternate)
            12: "BENCH", # Bench
            13: "IR",  # Injured Reserve
        }
    
    @staticmethod
    def _normalize_nba_abbrev(nba_abbrev: str) -> str:
        """Normalize NBA API abbreviation to ESPN Fantasy abbreviation.
        
        The NBA API uses slightly different abbreviations than ESPN Fantasy:
        - NBA API: "GS" -> ESPN Fantasy: "GSW"
        - NBA API: "WSH" -> ESPN Fantasy: "WAS"
        - NBA API: "UTAH" -> ESPN Fantasy: "UTA"
        
        Args:
            nba_abbrev: Abbreviation from NBA API
            
        Returns:
            Normalized abbreviation matching ESPN Fantasy format
        """
        normalization_map = {
            "GS": "GSW",    # Golden State Warriors
            "WSH": "WAS",   # Washington Wizards
            "UTAH": "UTA",  # Utah Jazz
        }
        return normalization_map.get(nba_abbrev, nba_abbrev)
    
    def _parse_todays_games(self, nba_data: dict[str, Any]) -> tuple[dict[str, TodaysGame], dict[int, str]]:
        """Parse today's NBA schedule and return mappings.
        
        Args:
            nba_data: Raw NBA schedule API response
            
        Returns:
            Tuple of:
            - Dictionary mapping team abbreviation (ESPN Fantasy format) to TodaysGame object
            - Dictionary mapping ESPN proTeamId to team abbreviation (for teams playing today)
        """
        games_map = {}
        team_id_to_abbrev = {}  # Maps ESPN proTeamId to abbreviation
        
        # Build reverse mapping: NBA API abbrev -> ESPN proTeamId
        # This helps us map NBA API team IDs to ESPN proTeamId
        nba_abbrev_to_espn_id = {}
        espn_mapping = self._get_pro_team_id_to_abbrev()
        for espn_id, espn_abbrev in espn_mapping.items():
            # Also map normalized versions
            nba_abbrev_to_espn_id[espn_abbrev] = espn_id
        
        try:
            for event in nba_data.get("events", []):
                competitions = event.get("competitions", [])
                if not competitions:
                    continue
                    
                competition = competitions[0]  # Usually one competition per event
                competitors = competition.get("competitors", [])
                if len(competitors) != 2:
                    continue
                
                home_team_abbr_nba = None
                away_team_abbr_nba = None
                home_team_id_nba = None
                away_team_id_nba = None
                
                for comp in competitors:
                    team_obj = comp.get("team", {})
                    team_abbr_nba = team_obj.get("abbreviation", "")
                    team_id_nba = team_obj.get("id") or comp.get("id")
                    
                    if comp.get("homeAway") == "home":
                        home_team_abbr_nba = team_abbr_nba
                        if team_id_nba:
                            home_team_id_nba = int(team_id_nba)
                    else:
                        away_team_abbr_nba = team_abbr_nba
                        if team_id_nba:
                            away_team_id_nba = int(team_id_nba)
                
                if not home_team_abbr_nba or not away_team_abbr_nba:
                    continue
                
                # Normalize abbreviations to ESPN Fantasy format
                home_team_abbr = self._normalize_nba_abbrev(home_team_abbr_nba)
                away_team_abbr = self._normalize_nba_abbrev(away_team_abbr_nba)
                
                # Extract game time and ISO datetime
                game_time = None
                game_time_iso = None
                date_str = event.get("date", "")
                if date_str:
                    try:
                        from datetime import datetime
                        from zoneinfo import ZoneInfo
                        # Parse UTC datetime
                        utc_dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        # Convert to ET timezone
                        et_dt = utc_dt.astimezone(ZoneInfo(self._get_timezone()))
                        # Format human-readable time
                        hour = et_dt.strftime('%I').lstrip('0') or '12'
                        minute = et_dt.strftime('%M')
                        am_pm = et_dt.strftime('%p')
                        game_time = f"{hour}:{minute} {am_pm}"  # e.g., "6:00 PM"
                        # Format ISO datetime (already in ET timezone)
                        game_time_iso = et_dt.isoformat()  # e.g., "2026-02-28T18:00:00-05:00"
                    except Exception:
                        pass
                
                # Create TodaysGame for both teams (using normalized ESPN Fantasy abbreviations)
                games_map[home_team_abbr] = TodaysGame(
                    opponent=away_team_abbr,
                    time=game_time,
                    timeISO=game_time_iso,
                    home=True
                )
                games_map[away_team_abbr] = TodaysGame(
                    opponent=home_team_abbr,
                    time=game_time,
                    timeISO=game_time_iso,
                    home=False
                )
                
                # Map NBA API team IDs to ESPN proTeamId using abbreviation lookup
                if home_team_id_nba and home_team_abbr in nba_abbrev_to_espn_id:
                    espn_id = nba_abbrev_to_espn_id[home_team_abbr]
                    team_id_to_abbrev[espn_id] = home_team_abbr
                if away_team_id_nba and away_team_abbr in nba_abbrev_to_espn_id:
                    espn_id = nba_abbrev_to_espn_id[away_team_abbr]
                    team_id_to_abbrev[espn_id] = away_team_abbr
        except Exception as e:
            logger.debug(f"Error parsing today's games: {e}")
        
        return games_map, team_id_to_abbrev
    
    @staticmethod
    def _get_pro_team_id_to_abbrev() -> dict[int, str]:
        """Get mapping of ESPN Fantasy proTeamId to team abbreviation.
        
        This mapping is based on ESPN Fantasy Basketball's proTeamId system.
        It was manually validated by checking which players map to which codes and checking against the ESPN Fantasy UI.
        Note: ESPN Fantasy uses different team IDs than the NBA API, but the
        abbreviations are consistent (with a few exceptions like GSW vs GS).
        
        Returns:
            Dictionary mapping ESPN Fantasy proTeamId to team abbreviation
        """

        return {
            1: "ATL",  # Atlanta Hawks
            2: "BOS",  # Boston Celtics
            3: "NO",  # Brooklyn Nets 
            4: "CHI",  # Chicago Bulls 
            5: "CLE",  # Cleveland Cavaliers 
            6: "DAL",  # Dallas Mavericks
            7: "DEN",  # Denver Nuggets
            8: "DET",  # Detroit Pistons
            9: "GS",  # Golden State Warriors 
            10: "HOU",  # Houston Rockets 
            11: "IND",  # Indiana Pacers 
            12: "LAC",  # LA Clippers 
            13: "LAL",  # Los Angeles Lakers 
            14: "MIA",  # Miami Heat 
            15: "MIL",  # Milwaukee Bucks
            16: "MIN",  # Minnesota Timberwolves
            17: "BKN",  # Brooklyn Nets 
            18: "NY",  # New York Knicks
            19: "ORL",   # Orlando Magic 
            20: "PHI",   # Philadelphia 76ers 
            21: "PHX",  # Phoenix Suns 
            22: "POR",  # Portland Trail Blazers 
            23: "SAC",  # Sacramento Kings 
            24: "SA",  # San Antonio Spurs 
            25: "OKC",  # Oklahoma City Thunder 
            26: "UTAH",  # Utah Jazz 
            27: "WAS",   # Washington Wizards 
            28: "TOR",  # Toronto Raptors
            29: "MEM",  # Memphis Grizzlies 
            30: "CHA",  # Charlotte Hornets 
        }
    
    def _resolve_pro_team_abbrev(
        self, 
        pro_team_id: int | None, 
        api_pro_team_abbrev: str | None = None,
        team_id_to_abbrev: dict[int, str] | None = None
    ) -> str | None:
        """Resolve proTeamAbbrev with consistent fallback logic.
        
        This ensures consistent team abbreviation resolution across all player sources.
        Priority:
        1. Use API-provided abbreviation if available
        2. Use team_id_to_abbrev mapping (from today's games) if available
        3. Use static mapping from proTeamId
        
        Args:
            pro_team_id: ESPN Fantasy proTeamId
            api_pro_team_abbrev: Abbreviation returned by API (if any)
            team_id_to_abbrev: Optional mapping from today's games (proTeamId -> abbrev)
            
        Returns:
            Team abbreviation or None if proTeamId is invalid
        """
        # Use API value if available
        if api_pro_team_abbrev:
            return api_pro_team_abbrev
        
        # If no proTeamId, can't resolve
        if not pro_team_id:
            return None
        
        # Try today's games mapping first (if provided)
        if team_id_to_abbrev and pro_team_id in team_id_to_abbrev:
            return team_id_to_abbrev[pro_team_id]
        
        # Fallback to static mapping
        pro_team_id_mapping = self._get_pro_team_id_to_abbrev()
        return pro_team_id_mapping.get(pro_team_id)
    
    @staticmethod
    def _get_position_id_mapping() -> dict[int, str]:
        """Get mapping of ESPN position IDs to human-readable position names.
        
        ESPN uses 1-based indexing for defaultPositionId:
        1=PG, 2=SG, 3=SF, 4=PF, 5=C
        
        Note: eligibleSlots uses 0-based indexing (0=PG, 1=SG, etc.)
        
        Returns:
            Dictionary mapping position ID integers to position names
        """
        return {
            1: "PG",  # Point Guard
            2: "SG",  # Shooting Guard
            3: "SF",  # Small Forward
            4: "PF",  # Power Forward
            5: "C",   # Center
            6: "G",   # Guard (PG or SG)
            7: "F",   # Forward (SF or PF)
        }
    
    def _get_scoring_stat_ids(self, league_settings: LeagueSettings | None = None) -> set[int]:
        """Get set of stat IDs that are scoring categories for this league.
        
        Args:
            league_settings: LeagueSettings object (optional, will fetch if not provided)
            
        Returns:
            Set of stat ID integers that are scoring categories
        """
        if league_settings is None:
            # Return empty set if we can't determine scoring categories
            # This will include all stats in categoryScores
            return set()
        
        scoring_stat_ids = set()
        for scoring_item in league_settings.scoringSettings.scoringItems:
            scoring_stat_ids.add(scoring_item.statId)
        
        return scoring_stat_ids
    
    def _filter_category_scores(
        self, 
        category_scores: dict[str, float], 
        scoring_stat_ids: set[int],
        stat_mapping: dict[str, str]
    ) -> tuple[dict[str, float], dict[str, float]]:
        """Separate category scores into scoring categories and component stats.
        
        Args:
            category_scores: Dictionary of category name -> score value
            scoring_stat_ids: Set of stat IDs that are scoring categories
            stat_mapping: Mapping of stat ID strings to category names
            
        Returns:
            Tuple of (scoring_categories, component_stats) dictionaries
        """
        scoring_categories = {}
        component_stats = {}
        
        # Reverse mapping: category name -> stat ID
        reverse_mapping = {v: k for k, v in stat_mapping.items()}
        
        for category_name, score_value in category_scores.items():
            stat_id_str = reverse_mapping.get(category_name)
            if stat_id_str:
                try:
                    stat_id_int = int(stat_id_str)
                    if stat_id_int in scoring_stat_ids:
                        scoring_categories[category_name] = score_value
                    else:
                        # Component stats (FGM, FGA, FTM, FTA, etc.)
                        component_stats[category_name] = score_value
                except (ValueError, TypeError):
                    # If we can't determine, include in scoring categories
                    scoring_categories[category_name] = score_value
            else:
                # Unknown category, include in scoring categories
                scoring_categories[category_name] = score_value
        
        return scoring_categories, component_stats
    
    def _parse_espn_stats(self, stat_data: dict[str, Any]) -> dict[str, Any]:
        """Parse ESPN's stat format into our standardized format."""
        # ESPN uses different stat IDs for different categories
        # This is a mapping of common ESPN stat IDs to our field names
        stat_mapping = self._get_stat_id_mapping()

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

        # Get stats for all players in a single API call
        try:
            players_stats = await self.get_player_stats(player_ids)
            # Ensure we got a list (should always be the case when passing a list)
            if not isinstance(players_stats, list):
                players_stats = [players_stats]
        except ValueError:
            players_stats = []

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
            # Use consistent fallback logic for team abbreviation
            pro_team_id = player_info.get("proTeamId")
            pro_team_abbrev = self._resolve_pro_team_abbrev(
                pro_team_id,
                player_info.get("proTeamAbbrev")
            )
            pro_team_name = player_info.get("proTeamName")
            
            # Map position ID to name
            position_mapping = self._get_position_id_mapping()
            default_position_id = player_info["defaultPositionId"]
            default_position = position_mapping.get(default_position_id)
            
            player = Player(
                id=player_info["id"],
                fullName=player_info.get("fullName", ""),
                proTeamId=pro_team_id,
                proTeamAbbrev=pro_team_abbrev,
                proTeamName=pro_team_name,
                defaultPositionId=default_position_id,
                defaultPosition=default_position,
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

    async def _get_season_start_date(self):
        """Get the NBA season start date by querying the NBA schedule API.
        
        Queries a team's schedule to find the first game of the season,
        which is more reliable than querying scoreboard for specific dates.
        
        Returns:
            datetime object representing the first game date of the season, or None if not found
        """
        from datetime import datetime
        
        try:
            # Query any team's schedule to get all games for the season
            # Using a common team (Lakers = 13) to get season schedule
            url = f"{self.NBA_BASE_URL}/teams/13/schedule"
            params = {"season": self.year}
            
            data = await self._make_request(url, params)
            events = data.get("events", [])
            
            if not events:
                return None
            
            # Find the earliest game date
            earliest_date = None
            for event in events:
                date_str = event.get("date", "")
                if not date_str:
                    continue
                
                try:
                    # Parse the date (format: "2025-10-15T02:00Z")
                    game_date_str = date_str[:10]  # Extract YYYY-MM-DD
                    game_date = datetime.fromisoformat(game_date_str)
                    
                    if earliest_date is None or game_date < earliest_date:
                        earliest_date = game_date
                except (ValueError, TypeError):
                    continue
            
            return earliest_date
        except Exception as e:
            logger.warning(f"Could not determine season start date from API: {e}")
            return None
    
    async def _get_scoring_period_dates(
        self, scoring_period: int
    ) -> tuple[str | None, str | None]:
        """Get date range for a specific scoring period by querying NBA schedule.
        
        Determines the season start date from the NBA schedule API, then calculates
        scoring period dates based on week boundaries (Monday-Sunday).
        
        Args:
            scoring_period: Scoring period number
            
        Returns:
            Tuple of (start_date, end_date) in YYYY-MM-DD format, or (None, None) if not found
        """
        from datetime import datetime, timedelta
        
        # Get league settings to determine week start day
        try:
            league_settings = await self.get_league_settings()
            week_start_day = self._infer_week_start_day(league_settings)
        except Exception:
            week_start_day = 0  # Default to Monday
        
        # Get season start date from NBA schedule API
        first_game_date = await self._get_season_start_date()
        
        if not first_game_date:
            # Fallback: estimate based on typical season start
            logger.warning("Could not get season start from API, using estimate")
            first_game_date = datetime(self.year - 1, 10, 15)
        
        # Find the Monday of the week containing the first game
        # This becomes the start of scoring period 1
        days_since_week_start = (first_game_date.weekday() - week_start_day) % 7
        scoring_period_1_start = first_game_date - timedelta(days=days_since_week_start)
        
        # Calculate the start date for the requested scoring period
        scoring_period_start = scoring_period_1_start + timedelta(days=(scoring_period - 1) * 7)
        scoring_period_end = scoring_period_start + timedelta(days=6)  # Week ends 6 days later
        
        return scoring_period_start.strftime('%Y-%m-%d'), scoring_period_end.strftime('%Y-%m-%d')
    
    def _infer_week_start_day(self, league_settings: LeagueSettings | None) -> int:
        """Infer week start day from league settings.
        
        ESPN doesn't explicitly provide week start day, but we can infer it:
        - If waiverProcessDays contains "SUNDAY", weeks likely end on Sunday (start Monday)
        - periodTypeId: 2 typically means weekly periods
        - Default to Monday (0) if we can't infer
        
        Args:
            league_settings: League settings object, or None
            
        Returns:
            Weekday number (0=Monday, 6=Sunday)
        """
        if league_settings and league_settings.acquisitionSettings.waiverProcessDays:
            waiver_days = league_settings.acquisitionSettings.waiverProcessDays
            # If waivers process on Sunday, weeks likely end on Sunday (start Monday)
            if "SUNDAY" in waiver_days:
                logger.debug("Inferred week start: Monday (from waiverProcessDays=SUNDAY)")
                return 0  # Monday
            # If waivers process on Monday, weeks might start on Monday
            if "MONDAY" in waiver_days:
                logger.debug("Inferred week start: Monday (from waiverProcessDays=MONDAY)")
                return 0  # Monday
        
        # Default to Monday (most common for fantasy basketball)
        logger.debug("Using default week start: Monday")
        return 0  # Monday
    
    def _get_week_boundaries(self, date: str, week_start_day: int = 0) -> tuple[str, str]:
        """Get week boundaries for a given date based on week start day.
        
        Args:
            date: Date in YYYY-MM-DD format
            week_start_day: Weekday number (0=Monday, 6=Sunday)
            
        Returns:
            Tuple of (week_start_date, week_end_date) in YYYY-MM-DD format
        """
        from datetime import datetime, timedelta
        
        dt = datetime.fromisoformat(date)
        # Get the start day of the week
        days_since_start = (dt.weekday() - week_start_day) % 7
        week_start = dt - timedelta(days=days_since_start)
        week_end = week_start + timedelta(days=6)
        
        return week_start.strftime("%Y-%m-%d"), week_end.strftime("%Y-%m-%d")
    
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
        from datetime import datetime, timedelta

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
            # Parse date from ESPN API
            date_str = event.get("date", "")
            if not date_str:
                continue
                
            try:
                # ESPN returns dates like "2025-12-18T00:00Z" in UTC
                # NBA games are played in the evening in local time (ET/PT)
                # A game at midnight UTC Dec 18 is actually Dec 17 evening in ET
                # So we need to convert to ET and use that date
                try:
                    from zoneinfo import ZoneInfo
                    utc_dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    et_dt = utc_dt.astimezone(ZoneInfo(self._get_timezone()))
                    game_date_str = et_dt.strftime('%Y-%m-%d')
                    game_dt = datetime.fromisoformat(game_date_str)
                except (ImportError, ValueError):
                    # Fallback: parse UTC datetime and check if we need to adjust
                    # Only subtract 1 day if the UTC time is before ~5 AM (midnight ET)
                    # This handles games that occur late at night ET but are the next day UTC
                    try:
                        utc_dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        # If UTC time is before 5 AM, the game is likely the previous day in ET
                        # Otherwise, use the UTC date as-is
                        if utc_dt.hour < 5:
                            game_dt = utc_dt - timedelta(days=1)
                        else:
                            game_dt = utc_dt
                        game_date_str = game_dt.strftime('%Y-%m-%d')
                    except (ValueError, AttributeError):
                        # Last resort: use date part directly without timezone conversion
                        # ESPN's game dates are typically stored in local time anyway
                        game_date_str = date_str[:10]
                        game_dt = datetime.fromisoformat(game_date_str)
            except ValueError:
                logger.warning(f"Could not parse date: {date_str}")
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

        # Calculate games this week and next week using league-defined week boundaries
        from datetime import datetime, timedelta
        
        # Get league settings to infer week start day
        try:
            league_settings = await self.get_league_settings()
            week_start_day = self._infer_week_start_day(league_settings)
        except Exception as e:
            logger.warning(f"Could not get league settings for week boundaries, using default: {e}")
            week_start_day = 0  # Default to Monday
        
        start_dt = datetime.fromisoformat(start_date)
        week_start, week_end = self._get_week_boundaries(start_date, week_start_day)
        week_start_dt = datetime.fromisoformat(week_start)
        week_end_dt = datetime.fromisoformat(week_end)
        next_week_start_dt = week_end_dt + timedelta(days=1)
        next_week_end_dt = next_week_start_dt + timedelta(days=6)
        
        games_this_week = 0
        games_next_week = 0
        
        for game in games:
            game_dt = datetime.fromisoformat(game.date)
            if week_start_dt <= game_dt <= week_end_dt:
                games_this_week += 1
            elif next_week_start_dt <= game_dt <= next_week_end_dt:
                games_next_week += 1

        return PlayerSchedule(
            playerId=player_id,
            playerName=player_name,
            teamAbbreviation=team_abbrev,
            games=games,
            gamesThisWeek=games_this_week,
            gamesNextWeek=games_next_week,
        )

    async def get_roster_schedule_summary(
        self, team_id: int, start_date: str | None = None, end_date: str | None = None, scoring_period: int | None = None
    ) -> RosterScheduleSummary:
        """Get schedule summary for all players on a fantasy roster.

        Uses league settings to properly map scoring periods to dates and calculate
        week boundaries based on Monday-to-Sunday weeks.

        Args:
            team_id: Fantasy team ID
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            scoring_period: Optional scoring period to use for date mapping

        Returns:
            RosterScheduleSummary with schedule data for all rostered players

        Raises:
            ValueError: If team_id or dates are invalid
        """
        # Validate inputs
        self._validate_positive_int(team_id, "team_id")
        from datetime import datetime, timedelta

        # Get league settings to understand scoring period structure
        try:
            league_settings = await self.get_league_settings()
        except Exception as e:
            logger.warning(f"Failed to get league settings, using date-based calculation: {e}")
            league_settings = None

        # If scoring period provided, get estimated dates for that period
        if scoring_period:
            scoring_start, scoring_end = await self._get_scoring_period_dates(scoring_period)
            if scoring_start and scoring_end:
                # Use the estimated scoring period dates
                # Extend end_date to cover next week for "gamesNextWeek" calculation
                from datetime import datetime, timedelta
                end_dt = datetime.fromisoformat(scoring_end) + timedelta(days=7)
                start_date = scoring_start
                end_date = end_dt.strftime('%Y-%m-%d')
                logger.debug(f"Scoring period {scoring_period} estimated dates: {start_date} to {end_date}")
        
        # Validate dates are provided
        if not start_date or not end_date:
            from datetime import datetime, timedelta
            if not start_date:
                start_date = datetime.now().strftime("%Y-%m-%d")
            if not end_date:
                end_date = (datetime.fromisoformat(start_date) + timedelta(days=7)).strftime("%Y-%m-%d")

        # Get the roster first
        roster = await self.get_team_roster(team_id)

        player_schedules = []
        total_games_this_week = 0
        total_games_next_week = 0

        # Calculate week boundaries based on league settings
        week_start_day = self._infer_week_start_day(league_settings)
        week_start, week_end = self._get_week_boundaries(start_date, week_start_day)
        week_start_dt = datetime.fromisoformat(week_start)
        week_end_dt = datetime.fromisoformat(week_end)
        next_week_start_dt = week_end_dt + timedelta(days=1)
        next_week_end_dt = next_week_start_dt + timedelta(days=6)

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
                total_games_this_week += schedule.gamesThisWeek
                total_games_next_week += schedule.gamesNextWeek
            except Exception as e:
                logger.warning(f"Failed to get schedule for player {player.fullName}: {e}")
                continue

        # Calculate average
        avg_games = total_games_this_week / len(player_schedules) if player_schedules else 0.0

        # Determine scoring period if not provided
        determined_scoring_period = scoring_period
        if not determined_scoring_period and league_settings:
            # Use current matchup period from status
            determined_scoring_period = league_settings.status.currentMatchupPeriod

        return RosterScheduleSummary(
            teamId=team_id,
            scoringPeriod=determined_scoring_period or 0,
            playerSchedules=player_schedules,
            totalGamesThisWeek=total_games_this_week,
            totalGamesNextWeek=total_games_next_week,
            averageGamesPerPlayer=round(avg_games, 2),
        )

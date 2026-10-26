"""ESPN Fantasy Basketball API client."""

import asyncio
import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Any, overload
from zoneinfo import ZoneInfo

import httpx

from .analysis import analyze_matchup as analyze_matchup_impl
from .analysis import player_availability
from .constants import (
    ABBREV_ALIASES,
    AVAILABILITY_FACTORS,
    LINEUP_SLOT_NAMES,
    POSITION_NAMES,
    PRO_TEAM_ABBREVS,
    SHOOTING_THRESHOLDS,
    SLOT_BENCH,
    SLOT_IR,
    STAT_ID_TO_CATEGORY,
    normalize_nba_abbrev,
)
from .dates import (
    date_for_scoring_period,
    games_remaining_by_player,
    matchup_period_window,
    week_boundaries,
)
from .models import (
    AcquisitionSettings,
    CurrentMatchup,
    DraftPick,
    DraftRecommendation,
    DraftSettings,
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
    PlayerOwnership,
    PlayerPoolEntry,
    PlayerSchedule,
    PlayerScheduleGame,
    PlayerSearchResult,
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
from .search import SEARCH_MIN_SCORE, name_match_score, normalize_name

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

    def _epoch_ms_to_iso(self, epoch_ms: int | None) -> str | None:
        """Convert an ESPN epoch-milliseconds timestamp to ISO 8601 in MY_TIMEZONE."""
        if not epoch_ms:
            return None
        try:
            dt = datetime.fromtimestamp(epoch_ms / 1000, tz=ZoneInfo("UTC"))
            return dt.astimezone(ZoneInfo(self._get_timezone())).isoformat()
        except (ValueError, OSError, OverflowError) as e:
            logger.warning(f"Could not parse timestamp {epoch_ms}: {e}")
            return None

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
            from datetime import datetime
            from zoneinfo import ZoneInfo

            # Parse UTC datetime (API returns format like "2025-01-15T20:00:00Z")
            utc_dt = datetime.fromisoformat(utc_date_str.replace("Z", "+00:00"))
            # Convert to timezone specified by MY_TIMEZONE
            tz_dt = utc_dt.astimezone(ZoneInfo(self._get_timezone()))
            # Format as ISO datetime string
            return tz_dt.isoformat()
        except (ValueError, OSError) as e:
            logger.warning(f"Could not parse date {utc_date_str}: {e}")
            # Fallback to original date string
            return utc_date_str

    # ------------------------------------------------------------------ response cache
    # One process-wide cache shared by every client instance (the MCP server creates a new
    # client per tool call, so a per-instance cache would never be reused). Entries are keyed
    # by URL, query, filter header and account, and expire per endpoint: slow-changing data is
    # kept for minutes, live data only long enough to de-duplicate the many identical requests
    # a single tool call makes. Concurrent identical requests share one in-flight fetch.
    # Set ESPN_MCP_DISABLE_CACHE=1 to bypass the cache entirely.
    _response_cache: dict[str, tuple[float, Any]] = {}
    _inflight: dict[str, tuple[asyncio.AbstractEventLoop, "asyncio.Task[Any]"]] = {}
    _cache_hits: int = 0
    _cache_misses: int = 0
    _CACHE_MAX_ENTRIES = 512

    # Lifetimes in seconds. Settings and team lists change rarely; an NBA team's season
    # schedule almost never; the scoreboard changes as games tip off; everything else (rosters,
    # matchups, players, draft) is live and is only de-duplicated within a burst of calls.
    TTL_SETTINGS = 600.0
    TTL_TEAMS = 300.0
    TTL_NBA_TEAM_SCHEDULE = 6 * 3600.0
    TTL_SCOREBOARD = 60.0
    TTL_PRO_PLAYERS = 6 * 3600.0  # league-independent list of all active NBA players
    TTL_LIVE = 15.0

    @classmethod
    def clear_cache(cls) -> None:
        """Drop every cached response and reset the hit/miss counters."""
        cls._response_cache.clear()
        cls._inflight.clear()
        cls._cache_hits = 0
        cls._cache_misses = 0

    @classmethod
    def cache_stats(cls) -> dict[str, int]:
        """Return hit/miss counters and the number of cached responses."""
        return {
            "hits": cls._cache_hits,
            "misses": cls._cache_misses,
            "entries": len(cls._response_cache),
        }

    @staticmethod
    def _cache_enabled() -> bool:
        return os.getenv("ESPN_MCP_DISABLE_CACHE", "").strip().lower() not in ("1", "true", "yes")

    @classmethod
    def _cache_ttl(cls, url: str, params: dict[str, Any] | None) -> float:
        """Pick the cache lifetime for a request from its endpoint and view."""
        if url.endswith("/scoreboard"):
            return cls.TTL_SCOREBOARD
        if "/teams/" in url and url.endswith("/schedule"):
            return cls.TTL_NBA_TEAM_SCHEDULE
        if url.endswith("/players"):
            return cls.TTL_PRO_PLAYERS
        view = (params or {}).get("view")
        views = set(view) if isinstance(view, list) else ({view} if view else set())
        if views == {"mSettings"}:
            return cls.TTL_SETTINGS
        if views == {"mTeam"}:
            return cls.TTL_TEAMS
        return cls.TTL_LIVE

    def _cache_key(
        self, url: str, params: dict[str, Any] | None, headers: dict[str, str] | None
    ) -> str:
        normalized_headers = {k.lower(): v for k, v in (headers or {}).items()}
        return json.dumps(
            [
                url,
                params or {},
                normalized_headers.get("x-fantasy-filter"),
                self.cookies.get("SWID"),
            ],
            sort_keys=True,
            default=str,
        )

    @classmethod
    def _store(cls, key: str, ttl: float, data: Any) -> None:
        now = time.monotonic()
        if len(cls._response_cache) >= cls._CACHE_MAX_ENTRIES:
            for stale in [k for k, (exp, _) in cls._response_cache.items() if exp <= now]:
                cls._response_cache.pop(stale, None)
            while len(cls._response_cache) >= cls._CACHE_MAX_ENTRIES:
                oldest = min(cls._response_cache, key=lambda k: cls._response_cache[k][0])
                cls._response_cache.pop(oldest, None)
        cls._response_cache[key] = (now + ttl, data)

    async def _make_request(
        self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> Any:
        """GET an ESPN endpoint, serving repeats from the response cache.

        Returns the decoded JSON (a dict for league endpoints, a list for the players list).
        The returned object may be shared with other callers; treat it as read-only.

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

        if not self._cache_enabled():
            return await self._fetch(url, params, headers)

        cls = type(self)
        key = self._cache_key(url, params, headers)

        cached = cls._response_cache.get(key)
        if cached is not None and cached[0] > time.monotonic():
            cls._cache_hits += 1
            return cached[1]

        loop = asyncio.get_running_loop()
        inflight = cls._inflight.get(key)
        if inflight is not None and inflight[0] is loop and not inflight[1].done():
            cls._cache_hits += 1
            return await asyncio.shield(inflight[1])

        cls._cache_misses += 1
        task = loop.create_task(self._fetch(url, params, headers))
        cls._inflight[key] = (loop, task)
        try:
            data = await task
        finally:
            current = cls._inflight.get(key)
            if current is not None and current[1] is task:
                cls._inflight.pop(key, None)

        ttl = self._cache_ttl(url, params)
        if ttl > 0:
            self._store(key, ttl, data)
        return data

    async def _fetch(
        self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> Any:
        """Perform the actual HTTP GET. Errors are logged and re-raised, never cached."""
        try:
            # Set a reasonable timeout (30 seconds)
            timeout = httpx.Timeout(30.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                logger.debug(f"Making request to {url}")
                response = await client.get(
                    url, params=params, headers=headers, cookies=self.cookies
                )
                response.raise_for_status()
                return response.json()
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
        roster_size = sum(
            int(count)
            for slot_id, count in lineup_slot_counts.items()
            if str(slot_id) != str(self._SLOT_IR)
        )
        position_limits = {str(k): v for k, v in roster_data.get("positionLimits", {}).items()}
        roster_settings = RosterSettings(
            lineupSlotCounts=lineup_slot_counts,
            lineupSlotNames=lineup_slot_names if lineup_slot_names else None,
            rosterSize=roster_size or None,
            positionLimits=position_limits,
            positionLimitNames=self._name_position_limits(position_limits),
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
            matchupLimitPerScoringPeriod=acquisition_data.get(
                "matchupLimitPerScoringPeriod", False
            ),
            acquisitionLimit=acquisition_data.get("acquisitionLimit", -1),
            minimumBid=acquisition_data.get("minimumBid", 0),
            waiverProcessTimeLocal=self._eastern_hour_to_local(
                acquisition_data.get("waiverProcessHour")
            ),
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

        # Parse draft settings
        draft_data = settings_data.get("draftSettings", {})
        draft_date = draft_data.get("date")
        draft_settings = DraftSettings(
            type=draft_data.get("type"),
            auctionBudget=draft_data.get("auctionBudget"),
            pickOrder=[int(t) for t in draft_data.get("pickOrder", []) or []],
            keeperCount=draft_data.get("keeperCount", 0) or 0,
            date=draft_date,
            dateISO=self._epoch_ms_to_iso(draft_date),
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

        league_settings = LeagueSettings(
            leagueId=data.get("id", self.league_id),
            leagueName=settings_data.get("name", ""),
            seasonId=data.get("seasonId", self.year),
            size=settings_data.get("size", 0),
            scoringSettings=scoring_settings,
            scheduleSettings=schedule_settings,
            rosterSettings=roster_settings,
            acquisitionSettings=acquisition_settings,
            tradeSettings=trade_settings,
            draftSettings=draft_settings,
            status=status,
        )

        # Calendar dates for every matchup period, so readers need not interpret the raw
        # week-indexed matchupPeriods mapping themselves.
        try:
            anchor = await self._scoring_period_anchor(league_settings)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Could not anchor scoring periods: {e}")
            anchor = None
        if anchor is not None:
            anchor_period, anchor_date = anchor
            season_start = date_for_scoring_period(
                status.firstScoringPeriod or 1, anchor_period, anchor_date
            )
            week_start_day = self._infer_week_start_day(league_settings)
            period_dates: dict[str, list[str]] = {}
            for key in schedule_settings.matchupPeriods:
                try:
                    window = matchup_period_window(
                        int(key), season_start, schedule_settings.matchupPeriods, week_start_day
                    )
                except ValueError:
                    continue
                if window is not None:
                    period_dates[key] = [window[0].isoformat(), window[1].isoformat()]
            schedule_settings.matchupPeriodDates = period_dates or None

        return league_settings

    @staticmethod
    def _name_position_limits(position_limits: dict[str, int]) -> dict[str, int] | None:
        """Key ESPN's positionLimits by position name.

        The keys are position IDs. When they all fit the 1-based defaultPositionId scheme
        (1=PG ... 5=C) that is used; otherwise the lineup slot names are tried.
        """
        if not position_limits:
            return None
        try:
            ids = [int(k) for k in position_limits]
        except ValueError:
            return None
        table = POSITION_NAMES if all(i in POSITION_NAMES for i in ids) else LINEUP_SLOT_NAMES
        named = {table.get(i, f"POS_{i}"): position_limits[str(i)] for i in ids}
        return named

    def _eastern_hour_to_local(self, hour: int | None) -> str | None:
        """Express an ESPN hour-of-day (Eastern time) in MY_TIMEZONE, e.g. "07:00 America/Chicago"."""
        if hour is None:
            return None
        try:
            eastern = datetime.now(ZoneInfo("America/New_York")).replace(
                hour=int(hour), minute=0, second=0, microsecond=0
            )
            local = eastern.astimezone(ZoneInfo(self._get_timezone()))
            return f"{local:%H:%M} {self._get_timezone()}"
        except (ValueError, OSError):
            return None

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
                        f"00{self.year}",  # Current season actuals
                        f"10{self.year}",  # Projections
                    ],
                }
            }
        }

        import json

        headers = {"x-fantasy-filter": json.dumps(filter_dict)}
        params: dict[str, Any] = {"view": ["mRoster", "mTeam"]}

        if scoring_period:
            params["scoringPeriodId"] = str(scoring_period)

        data = await self._make_request(url, params, headers)

        # Fetch today's NBA schedule once for all players (optimization)
        # Don't pass date parameter - API defaults to today's games
        todays_games_cache: dict[str, TodaysGame] = {}
        # Maps proTeamId to abbreviation for teams playing today
        team_id_to_abbrev: dict[int, str] = {}
        try:
            url_nba = f"{self.NBA_BASE_URL}/scoreboard"
            # Don't pass dates parameter - API defaults to today's games in ET timezone
            params_nba: dict[str, Any] = {}
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
                        or entry.get(
                            "injuryStatus"
                        )  # Fall back to entry level if player level not available
                    )
                    # ESPN might return null/empty for DTD players - check if there's an injury object
                    if not injury_status:
                        injury_info = player_data.get("injury") or entry.get("injury")
                        if injury_info:
                            # ESPN might have injury details in an object
                            injury_status = injury_info.get("status") or injury_info.get(
                                "injuryStatus"
                            )
                    # If still no status, preserve None rather than defaulting (let the model handle it)
                    # This way we don't mask DTD players that ESPN marks differently

                    # Parse player stats
                    stats_data = self._parse_player_stats(player_data.get("stats", []))

                    pro_team_id = player_data.get("proTeamId")
                    # Use consistent fallback logic for team abbreviation
                    pro_team_abbrev = self._resolve_pro_team_abbrev(
                        pro_team_id, player_data.get("proTeamAbbrev"), team_id_to_abbrev
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
                        eligible_slot_names = [
                            slot_mapping.get(slot_id, f"SLOT_{slot_id}")
                            for slot_id in eligible_slots
                        ]

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
                    todays_game = (
                        todays_games_cache.get(pro_team_abbrev) if pro_team_abbrev else None
                    )

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
                            logger.warning(
                                f"Could not parse acquisition date {acquisition_date}: {e}"
                            )

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
                        "fg_pct": round(averages.get("19", 0) * 100, 1)
                        if averages.get("19")
                        else None,
                        "ft_pct": round(averages.get("20", 0) * 100, 1)
                        if averages.get("20")
                        else None,
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
                        f"00{self.year}",  # Current season total
                        f"10{self.year}",  # Current season projected
                    ],
                },
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
                                "fg_pct": round(source.get("19", 0) * 100, 1)
                                if source.get("19")
                                else None,  # FG%
                                "ft_pct": round(source.get("20", 0) * 100, 1)
                                if source.get("20")
                                else None,  # FT%
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
                pro_team_id, player_info.get("proTeamAbbrev")
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
                eligible_slot_names = [
                    slot_mapping.get(slot_id, f"SLOT_{slot_id}") for slot_id in eligible_slots
                ]

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
                ownership=PlayerOwnership(
                    percentOwned=percent_owned,
                    percentChange=percent_change,
                ),
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
        league_settings: LeagueSettings | None = None

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
                    {
                        item.get("matchupPeriodId")
                        for item in schedule
                        if item.get("matchupPeriodId")
                    },
                    reverse=True,
                )
                if matchup_periods:
                    # Use the most recent matchup period as fallback
                    scoring_period = matchup_periods[0]
                    logger.info(
                        f"Determined current scoring period from API response: {scoring_period}"
                    )
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

        # Get league settings to determine scoring categories (reuse if already fetched above)
        scoring_stat_ids: set[int] = set()
        try:
            if league_settings is None:
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

                # Extract team info from home/away data using helper method
                home_team = None
                if schedule_item.get("home"):
                    home_data = schedule_item["home"]
                    home_team = self._parse_matchup_team_data(
                        home_data, team_names, scoring_stat_ids, stat_mapping
                    )

                away_team = None
                if schedule_item.get("away"):
                    away_data = schedule_item["away"]
                    away_team = self._parse_matchup_team_data(
                        away_data, team_names, scoring_stat_ids, stat_mapping
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

    def _parse_matchup_team_data(
        self,
        team_data: dict[str, Any],
        team_names: dict[int, str],
        scoring_stat_ids: set[int],
        stat_mapping: dict[str, str],
    ) -> MatchupTeam:
        """Parse team data from matchup API response into MatchupTeam object.

        Args:
            team_data: Raw team data from API (home or away)
            team_names: Mapping of team_id -> team_name
            scoring_stat_ids: Set of stat IDs that are scoring categories
            stat_mapping: Mapping of stat ID strings to category names

        Returns:
            MatchupTeam object with parsed data
        """
        cumulative_score = team_data.get("cumulativeScore", {})

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

        team_id = team_data.get("teamId")
        return MatchupTeam(
            teamId=team_id,
            teamName=team_names.get(team_id) if team_id else None,
            totalPoints=team_data.get("totalPoints"),
            totalProjectedPoints=team_data.get("totalProjectedPoints"),
            gamesPlayed=team_data.get("gamesPlayed"),
            cumulativeScore=cumulative_score,  # Keep raw data for percentage calculations
            categoryScores=scoring_categories if scoring_categories else None,
            componentStats=component_stats if component_stats else None,
        )

    def _determine_team_sides(
        self, matchup: Matchup, team_id: int
    ) -> tuple[MatchupTeam, MatchupTeam] | None:
        """Determine which team is 'yours' and which is the opponent in a matchup.

        Args:
            matchup: The matchup object
            team_id: Your team ID

        Returns:
            Tuple of (your_team_data, opponent_team_data) or None if team not found
        """
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

        return your_team_data, opponent_team_data

    async def get_my_current_matchup(
        self, team_id: int, verbose: bool = False
    ) -> CurrentMatchup | None:
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
        # Get current matchup period and delegate to get_matchup_for_period
        league_settings = await self.get_league_settings()
        current_matchup_period = league_settings.status.currentMatchupPeriod

        # Delegate to get_matchup_for_period, passing league_settings to avoid duplicate call
        return await self.get_matchup_for_period(
            team_id, current_matchup_period, verbose, league_settings=league_settings
        )

    async def get_matchup_for_period(
        self,
        team_id: int,
        matchup_period: int,
        verbose: bool = False,
        league_settings: LeagueSettings | None = None,
    ) -> CurrentMatchup | None:
        """Get matchup information for a specific matchup period.

        Args:
            team_id: Your team ID
            matchup_period: Matchup period to get (e.g., 1, 2, 3...)
            verbose: If True, include full player stats in rosters (default False)
            league_settings: Optional league settings to avoid duplicate API call

        Returns:
            CurrentMatchup object with matchup data, or None if not found
        """
        # Get league settings if not provided
        if league_settings is None:
            league_settings = await self.get_league_settings()

        # Get matchups for the specified matchup period
        matchups = await self.get_matchups(scoring_period=matchup_period, team_id=team_id)

        if not matchups:
            logger.warning(
                f"No matchup found for team {team_id} in matchup period {matchup_period}"
            )
            return None

        # Should only be one matchup for a team in a given period
        matchup = matchups[0]

        # Determine which team is "yours" and which is the opponent
        team_sides = self._determine_team_sides(matchup, team_id)
        if not team_sides:
            return None
        your_team_data, opponent_team_data = team_sides
        opponent_team_id = opponent_team_data.teamId
        if opponent_team_id is None:
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

        # Get rosters for both teams concurrently
        your_roster, opponent_roster = await asyncio.gather(
            self.get_team_roster(team_id, scoring_period=scoring_period),
            self.get_team_roster(opponent_team_id, scoring_period=scoring_period),
        )

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

    # Pure helpers live in constants.py, dates.py, search.py and analysis.py. These aliases keep
    # the class API (and the test surface) stable.
    _SHOOTING_THRESHOLDS = SHOOTING_THRESHOLDS
    _AVAILABILITY_FACTORS = AVAILABILITY_FACTORS
    _SLOT_BENCH = SLOT_BENCH
    _SLOT_IR = SLOT_IR
    _SEARCH_MIN_SCORE = SEARCH_MIN_SCORE
    _ABBREV_ALIASES = ABBREV_ALIASES

    @staticmethod
    def _availability(entry: RosterEntry) -> tuple[str, float]:
        return player_availability(entry)

    @staticmethod
    def _games_remaining_by_player(
        schedule: RosterScheduleSummary, now: datetime, window_end: date | None = None
    ) -> dict[int, int]:
        return games_remaining_by_player(schedule, now, window_end)

    @staticmethod
    def _date_for_scoring_period(
        scoring_period: int, anchor_period: int, anchor_date: date
    ) -> date:
        return date_for_scoring_period(scoring_period, anchor_period, anchor_date)

    @staticmethod
    def _matchup_period_window(
        matchup_period: int,
        season_start: date,
        matchup_periods: dict[str, list[int]],
        week_start_day: int = 0,
    ) -> tuple[date, date] | None:
        return matchup_period_window(matchup_period, season_start, matchup_periods, week_start_day)

    @staticmethod
    def _normalize_name(name: str) -> str:
        return normalize_name(name)

    @classmethod
    def _name_match_score(cls, query: str, full_name: str) -> float:
        return name_match_score(query, full_name)

    @staticmethod
    def _normalize_nba_abbrev(nba_abbrev: str) -> str:
        return normalize_nba_abbrev(nba_abbrev)

    @staticmethod
    def _get_stat_id_mapping() -> dict[str, str]:
        return dict(STAT_ID_TO_CATEGORY)

    @staticmethod
    def _get_lineup_slot_id_mapping() -> dict[int, str]:
        return dict(LINEUP_SLOT_NAMES)

    @staticmethod
    def _get_pro_team_id_to_abbrev() -> dict[int, str]:
        return dict(PRO_TEAM_ABBREVS)

    @staticmethod
    def _get_position_id_mapping() -> dict[int, str]:
        return dict(POSITION_NAMES)

    def _get_week_boundaries(self, date_str: str, week_start_day: int = 0) -> tuple[str, str]:
        return week_boundaries(date_str, week_start_day)

    async def analyze_matchup(
        self, team_id: int, matchup_period: int | None = None
    ) -> MatchupAnalysis:
        """Analyze a matchup: category projections, close categories, start/sit priorities and
        lineup warnings. See analysis.analyze_matchup for the full description."""
        return await analyze_matchup_impl(self, team_id, matchup_period)

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
            is_completed_matchup = (
                matchup_period_id is not None and matchup_period_id < current_matchup_period
            )

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
                leader_losses = float("inf")

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
                        games_back = (
                            (leader_wins - matchup_wins) + (matchup_losses - leader_losses)
                        ) / 2.0
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
            if re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                # Convert to YYYYMMDD format (no dashes) for API
                date_obj = datetime.strptime(date, "%Y-%m-%d")
                date_formatted = date_obj.strftime("%Y%m%d")
                # Use 'date' parameter (not 'dates') with YYYYMMDD format
                params["date"] = date_formatted
            elif re.match(r"^\d{8}$", date):
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

                game = NBAGame(id=event["id"], date=date_iso, competitions=event["competitions"])
                games.append(game)

            return games
        except httpx.HTTPError as e:
            # If explicit date fails, try without date parameter (defaults to today)
            if date and "400" in str(e):
                logger.debug(
                    f"NBA API rejected explicit date {date}, trying without date parameter"
                )
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
                    logger.warning(
                        f"NBA API doesn't accept explicit dates. Returned today's games instead of {date}"
                    )
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

        # The league's draft order tells us who nominates / picks next
        draft_type: str | None = None
        pick_order: list[int] = []
        try:
            settings = await self.get_league_settings()
            draft_type = settings.draftSettings.type
            pick_order = settings.draftSettings.pickOrder
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Draft order unavailable: {e}")

        current_pick_number = None
        current_nominating_team = None
        if draft_detail.get("inProgress", False):
            current_pick_number = len(picks) + 1
            current_nominating_team = self._team_on_the_clock(
                current_pick_number, pick_order, draft_type
            )

        return DraftStatus(
            inProgress=draft_detail.get("inProgress", False),
            drafted=draft_detail.get("drafted", False),
            completeDate=draft_detail.get("completeDate"),
            picks=picks,
            currentPickNumber=current_pick_number,
            currentNominatingTeam=current_nominating_team,
            draftType=draft_type,
        )

    @staticmethod
    def _team_on_the_clock(
        pick_number: int, pick_order: list[int], draft_type: str | None
    ) -> int | None:
        """Team ID that picks (snake) or nominates (auction) at an overall pick number.

        Auction nominations cycle through pickOrder every round; snake drafts reverse the
        order in even rounds. Returns None when the league's pick order is unknown.
        """
        if not pick_order or pick_number < 1:
            return None
        n = len(pick_order)
        index = (pick_number - 1) % n
        round_index = (pick_number - 1) // n
        if (draft_type or "").upper() == "SNAKE" and round_index % 2 == 1:
            index = n - 1 - index
        return pick_order[index]

    async def get_available_players(self, limit: int = 100) -> list[PlayerDraftInfo]:
        """Get undrafted players with ESPN's draft rank and auction value, best first.

        Asks ESPN for free agents sorted by its STANDARD draft rank (the filter must be sent
        as the x-fantasy-filter header); without it ESPN returns an arbitrary default slice.
        """
        if not isinstance(limit, int) or limit < 1 or limit > 500:
            raise ValueError(f"Invalid limit: {limit}. Must be between 1 and 500.")
        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        params = {"view": "kona_player_info"}
        filter_dict = {
            "players": {
                "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
                "limit": max(limit * 2, 50),  # headroom for drafted players filtered below
                "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": "STANDARD"},
            }
        }
        headers = {"x-fantasy-filter": json.dumps(filter_dict)}

        data = await self._make_request(url, params, headers)

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
                pro_team_id, player_data.get("proTeamAbbrev")
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
                eligible_slot_names = [
                    slot_mapping.get(slot_id, f"SLOT_{slot_id}") for slot_id in eligible_slots
                ]

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
        """Draft spending and roster progress for a team.

        Budget and roster size come from league settings (draftSettings.auctionBudget and
        rosterSettings.lineupSlotCounts); $200 and 13 are used only if settings are unavailable.
        """
        draft_status, teams = await asyncio.gather(self.get_draft_status(), self.get_league_teams())
        team_picks = [pick for pick in draft_status.picks if pick.teamId == team_id]
        team = next((t for t in teams if t.id == team_id), None)
        team_name = team.name if team else f"Team {team_id}"

        budget, roster_size = 200, 13
        draft_type: str | None = draft_status.draftType
        try:
            settings = await self.get_league_settings()
            if settings.draftSettings.auctionBudget:
                budget = settings.draftSettings.auctionBudget
            if settings.rosterSettings.rosterSize:
                roster_size = settings.rosterSettings.rosterSize
            draft_type = draft_type or settings.draftSettings.type
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"League settings unavailable; assuming ${budget} budget and {roster_size} roster spots: {e}"
            )

        total_spent = sum(pick.bidAmount for pick in team_picks)
        players_count = len(team_picks)

        # Drafted players by position, from the league's player pool
        position_counts: dict[str, int] = {}
        if team_picks:
            try:
                url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
                ids = [pick.playerId for pick in team_picks]
                headers = {
                    "x-fantasy-filter": json.dumps({"players": {"filterIds": {"value": ids}}})
                }
                data = await self._make_request(url, {"view": "kona_player_info"}, headers)
                position_map = self._get_position_id_mapping()
                for entry in data.get("players", []):
                    position = position_map.get(
                        entry.get("player", {}).get("defaultPositionId", -1), "UNK"
                    )
                    position_counts[position] = position_counts.get(position, 0) + 1
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Could not fetch drafted players' positions: {e}")

        return TeamDraftSummary(
            teamId=team_id,
            teamName=team_name,
            totalSpent=total_spent,
            playersCount=players_count,
            remainingBudget=budget - total_spent,
            budget=budget,
            rosterSize=roster_size,
            remainingSlots=max(0, roster_size - players_count),
            draftType=draft_type,
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

            # Simple bidding logic: keep $1 for every roster spot still to fill after this one
            player_value = current_player.auctionValue or 0
            slots_left = team_summary.remainingSlots
            if slots_left is None:
                slots_left = max(0, team_summary.rosterSize - team_summary.playersCount)
            reserve = max(0, slots_left - 1)
            max_affordable = min(team_summary.remainingBudget - reserve, player_value)

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
        slots_left = team_summary.remainingSlots
        if slots_left is None:
            slots_left = max(0, team_summary.rosterSize - team_summary.playersCount)
        return {
            "totalSpent": team_summary.totalSpent,
            "remainingBudget": team_summary.remainingBudget,
            "playersCount": team_summary.playersCount,
            "rosterSize": team_summary.rosterSize,
            "remainingSlots": slots_left,
            "strategy": "balanced" if team_summary.playersCount < 5 else "punt_detection_needed",
            "recommendation": f"You have ${team_summary.remainingBudget} for {slots_left} more players",
        }

    # ------------------------------------------------------------------ player search

    async def get_pro_players(self) -> list[dict[str, Any]]:
        """All active NBA players known to ESPN Fantasy for this season (league-independent).

        Uses the players list endpoint with the players_wl view, which returns id, fullName,
        defaultPositionId, proTeamId and injury status for roughly 500 players. Cached 6 hours.
        """
        url = f"{self.BASE_URL}/seasons/{self.year}/players"
        headers = {"x-fantasy-filter": json.dumps({"filterActive": {"value": True}})}
        data = await self._make_request(url, {"view": "players_wl"}, headers)
        if isinstance(data, dict):  # defensive: some ESPN endpoints wrap lists
            data = data.get("players", [])
        return [p for p in data if isinstance(p, dict) and "id" in p]

    async def search_players(
        self, query: str, limit: int = 5, include_league_status: bool = True
    ) -> list[PlayerSearchResult]:
        """Find players by (partial, misspelled, or accented) name.

        Args:
            query: Name or part of a name, e.g. "Jokic", "steph curry", "Dončić"
            limit: Maximum results (1-25)
            include_league_status: Also report whether each match is a free agent in this
                league or which fantasy team owns them (one extra request)

        Returns:
            Matches sorted by score, best first. Empty if nothing scores at least 0.6.
        """
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        if not isinstance(limit, int) or limit < 1 or limit > 25:
            raise ValueError(f"Invalid limit: {limit}. Must be between 1 and 25.")

        players = await self.get_pro_players()
        scored = sorted(
            (
                (self._name_match_score(query, p.get("fullName", "")), p)
                for p in players
                if p.get("fullName")
            ),
            key=lambda sp: (-sp[0], sp[1].get("fullName", "")),
        )
        top = [(score, p) for score, p in scored[:limit] if score >= self._SEARCH_MIN_SCORE]

        position_map = self._get_position_id_mapping()
        results = [
            PlayerSearchResult(
                playerId=p["id"],
                fullName=p.get("fullName", ""),
                matchScore=round(score, 3),
                defaultPosition=position_map.get(p.get("defaultPositionId", -1)),
                proTeamAbbrev=self._resolve_pro_team_abbrev(p.get("proTeamId")),
                injuryStatus=p.get("injuryStatus"),
            )
            for score, p in top
        ]

        if include_league_status and results:
            await self._attach_league_status(results)
        return results

    async def _attach_league_status(self, results: list[PlayerSearchResult]) -> None:
        """Fill isFreeAgent / fantasyTeamId / fantasyTeamName / percentOwned for matches."""
        ids = [r.playerId for r in results]
        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        headers = {"x-fantasy-filter": json.dumps({"players": {"filterIds": {"value": ids}}})}
        try:
            data, teams = await asyncio.gather(
                self._make_request(url, {"view": "kona_player_info"}, headers),
                self.get_league_teams(),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not fetch league status for player search: {e}")
            return
        team_names = {t.id: t.name for t in teams}
        by_id = {entry.get("id"): entry for entry in data.get("players", [])}
        for r in results:
            entry = by_id.get(r.playerId)
            if not entry:
                continue
            on_team = entry.get("onTeamId")
            r.isFreeAgent = on_team in (0, None)
            r.fantasyTeamId = on_team if on_team else None
            r.fantasyTeamName = team_names.get(on_team) if on_team else None
            r.percentOwned = (entry.get("ownership") or {}).get("percentOwned")
            r.injuryStatus = entry.get("player", {}).get("injuryStatus") or r.injuryStatus

    @overload
    async def get_player_stats(self, player_id: int, timeframe: str = ...) -> PlayerStats: ...

    @overload
    async def get_player_stats(
        self, player_id: list[int], timeframe: str = ...
    ) -> list[PlayerStats]: ...

    async def get_player_stats(
        self, player_id: int | list[int], timeframe: str = "season"
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
        player_ids: list[int] = [player_id] if isinstance(player_id, int) else list(player_id)

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
            raise ValueError(
                f"Invalid timeframe: {timeframe}. Must be one of {list(timeframe_map.keys())}"
            )

        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        stat_period = timeframe_map[timeframe]

        # Build filter to request players with stats
        filter_dict = {
            "players": {
                "filterIds": {"value": player_ids},
                "filterStatsForTopScoringPeriodIds": {"value": 5, "additionalValue": [stat_period]},
            }
        }

        import json

        headers = {"x-fantasy-filter": json.dumps(filter_dict)}
        params = {"view": "kona_player_info"}

        data = await self._make_request(url, params, headers)

        # Process all players returned in the response
        results: list[PlayerStats] = []
        found_player_ids: set[int] = set()

        for player_entry in data.get("players", []):
            player_info = player_entry.get("player", {})
            pid = player_info.get("id")

            if pid not in player_ids:
                continue  # Skip players not in our requested list

            found_player_ids.add(pid)

            # Parse stats for the requested timeframe
            stats_dict = self._parse_player_stats_for_timeframe(
                player_info.get("stats", []), timeframe
            )

            results.append(
                PlayerStats(
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
                    fieldGoalsMade=stats_dict.get("fgm"),
                    fieldGoalsAttempted=stats_dict.get("fga"),
                    freeThrowsMade=stats_dict.get("ftm"),
                    freeThrowsAttempted=stats_dict.get("fta"),
                    fantasyPoints=stats_dict.get("fantasyAvg"),
                )
            )

        # Log warning for any players not found
        missing_ids = set(player_ids) - found_player_ids
        if missing_ids:
            logger.warning(f"Players with IDs {missing_ids} not found in API response")

        if not results:
            raise ValueError("Player not found" if is_single else "No matching players found")

        # Return single PlayerStats if single ID was provided, otherwise return list
        if isinstance(player_id, int):
            return results[0]
        return results

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
                        "fg_pct": round(averages.get("19", 0) * 100, 1)
                        if averages.get("19")
                        else None,
                        "ft_pct": round(averages.get("20", 0) * 100, 1)
                        if averages.get("20")
                        else None,
                        # 13=FGM 14=FGA 15=FTM 16=FTA; per game, so percentages can be
                        # projected as made/attempted instead of estimated from points
                        "fgm": round(averages.get("13", 0), 2),
                        "fga": round(averages.get("14", 0), 2),
                        "ftm": round(averages.get("15", 0), 2),
                        "fta": round(averages.get("16", 0), 2),
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
                        "fgm": round(totals.get("13", 0) / gp, 2),
                        "fga": round(totals.get("14", 0) / gp, 2),
                        "ftm": round(totals.get("15", 0) / gp, 2),
                        "fta": round(totals.get("16", 0) / gp, 2),
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

    def _parse_todays_games(
        self, nba_data: dict[str, Any]
    ) -> tuple[dict[str, TodaysGame], dict[int, str]]:
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
                        utc_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        # Convert to ET timezone
                        et_dt = utc_dt.astimezone(ZoneInfo(self._get_timezone()))
                        # Format human-readable time
                        hour = et_dt.strftime("%I").lstrip("0") or "12"
                        minute = et_dt.strftime("%M")
                        am_pm = et_dt.strftime("%p")
                        game_time = f"{hour}:{minute} {am_pm}"  # e.g., "6:00 PM"
                        # Format ISO datetime (already in ET timezone)
                        game_time_iso = et_dt.isoformat()  # e.g., "2026-02-28T18:00:00-05:00"
                    except Exception:
                        pass

                # Create TodaysGame for both teams (using normalized ESPN Fantasy abbreviations)
                games_map[home_team_abbr] = TodaysGame(
                    opponent=away_team_abbr, time=game_time, timeISO=game_time_iso, home=True
                )
                games_map[away_team_abbr] = TodaysGame(
                    opponent=home_team_abbr, time=game_time, timeISO=game_time_iso, home=False
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

    def _resolve_pro_team_abbrev(
        self,
        pro_team_id: int | None,
        api_pro_team_abbrev: str | None = None,
        team_id_to_abbrev: dict[int, str] | None = None,
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
            Team abbreviation, "FA" for an unsigned player (proTeamId 0), or None if unknown
        """
        # Use API value if available (normalized so it matches our lookup keys)
        if api_pro_team_abbrev:
            return self._normalize_nba_abbrev(api_pro_team_abbrev)

        # ESPN uses proTeamId 0 for players not on any NBA roster (shown as "FA" in its UI).
        # Such a player cannot play, so no today's-game or schedule lookups will match "FA".
        if pro_team_id == 0:
            return "FA"

        # If no proTeamId at all, can't resolve
        if pro_team_id is None:
            return None

        # Try today's games mapping first (if provided)
        if team_id_to_abbrev and pro_team_id in team_id_to_abbrev:
            return team_id_to_abbrev[pro_team_id]

        # Fallback to static mapping
        pro_team_id_mapping = self._get_pro_team_id_to_abbrev()
        return pro_team_id_mapping.get(pro_team_id)

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
        stat_mapping: dict[str, str],
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
        your_players: list[PlayerStats] = []
        their_players: list[PlayerStats] = []

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
        """Get free agents trending up or down in ownership.

        Fetches a wide slice of free agents (ESPN's default slice is arbitrary without the
        x-fantasy-filter header), ranks them by ownership change, and returns the top `limit`.
        """
        if direction not in ("up", "down"):
            raise ValueError(f"Invalid direction: {direction}. Must be 'up' or 'down'.")
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise ValueError(f"Invalid limit: {limit}. Must be between 1 and 100.")
        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        params = {"view": "kona_player_info"}
        filter_dict = {
            "players": {
                "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
                "limit": max(200, limit * 10),
                "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
            }
        }
        headers = {"x-fantasy-filter": json.dumps(filter_dict)}

        data = await self._make_request(url, params, headers)

        trending_players: list[TrendingPlayer] = []

        for player_entry in data.get("players", []):
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
                pro_team_id, player_info.get("proTeamAbbrev")
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

        # Sort by trending strength, then cut to the requested size
        trending_players.sort(key=lambda x: abs(x.add_percentage - x.drop_percentage), reverse=True)

        return trending_players[:limit]

    # ------------------------------------------------------------------ matchup period dates

    async def _scoring_period_anchor(
        self, league_settings: LeagueSettings, today: date | None = None
    ) -> tuple[int, date] | None:
        """Find a (scoring period, calendar date) pair to anchor the mapping.

        During the season ESPN's status.latestScoringPeriod is today's period, where "today"
        is ESPN's day (Eastern time). Before or after the season that value is pinned to the
        first or final period, so fall back to opening night from the NBA schedule as period 1.
        """
        status = league_settings.status
        in_season = (
            status.firstScoringPeriod <= status.latestScoringPeriod < status.finalScoringPeriod
        )
        if in_season:
            if today is None:
                today = datetime.now(ZoneInfo("America/New_York")).date()
            return status.latestScoringPeriod, today
        first_game = await self._get_season_start_date()
        if first_game is not None:
            return status.firstScoringPeriod or 1, first_game.date()
        return None

    async def get_matchup_period_dates(
        self,
        matchup_period: int,
        league_settings: LeagueSettings | None = None,
        today: date | None = None,
    ) -> tuple[date, date] | None:
        """First and last calendar day of a matchup period.

        Opening night is found from the daily scoring-period counter (today is
        status.latestScoringPeriod during the season), and the period's length from
        scheduleSettings.matchupPeriods, so a short opening week or a two-week All-Star period
        comes out right.

        Args:
            matchup_period: Matchup period (week) number
            league_settings: Already-fetched settings, to avoid a lookup
            today: Override for the current date (tests)

        Returns:
            (first_day, last_day) inclusive, or None if it cannot be determined
        """
        if league_settings is None:
            try:
                league_settings = await self.get_league_settings()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Could not get league settings for matchup period dates: {e}")
                return None
        anchor = await self._scoring_period_anchor(league_settings, today)
        if anchor is None:
            return None
        anchor_period, anchor_date = anchor
        first_period = league_settings.status.firstScoringPeriod or 1
        season_start = self._date_for_scoring_period(first_period, anchor_period, anchor_date)
        return self._matchup_period_window(
            matchup_period,
            season_start,
            league_settings.scheduleSettings.matchupPeriods,
            self._infer_week_start_day(league_settings),
        )

    async def _get_season_start_date(self) -> datetime | None:
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

    async def get_player_schedule(
        self,
        player_id: int,
        nba_team_id: int,
        start_date: str,
        end_date: str,
        this_window: tuple[date, date] | None = None,
        next_window: tuple[date, date] | None = None,
    ) -> PlayerSchedule:
        """Get schedule for a specific player.

        Args:
            player_id: ESPN player ID
            nba_team_id: NBA team ID (proTeamId from player data)
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            this_window: Inclusive date range counted as gamesThisWeek (default: the
                Monday-to-Sunday week containing start_date)
            next_window: Inclusive date range counted as gamesNextWeek (default: the week
                after this_window)

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
        team_abbrev = self._normalize_nba_abbrev(data.get("team", {}).get("abbreviation", "UNK"))
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
                tip_off_iso: str | None = None
                try:
                    utc_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    et_dt = utc_dt.astimezone(ZoneInfo(self._get_timezone()))
                    game_date_str = et_dt.strftime("%Y-%m-%d")
                    game_dt = datetime.fromisoformat(game_date_str)
                    tip_off_iso = et_dt.isoformat()
                except (ImportError, ValueError):
                    # Fallback: parse UTC datetime and check if we need to adjust
                    # Only subtract 1 day if the UTC time is before ~5 AM (midnight ET)
                    # This handles games that occur late at night ET but are the next day UTC
                    try:
                        utc_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        # If UTC time is before 5 AM, the game is likely the previous day in ET
                        # Otherwise, use the UTC date as-is
                        if utc_dt.hour < 5:
                            game_dt = utc_dt - timedelta(days=1)
                        else:
                            game_dt = utc_dt
                        game_date_str = game_dt.strftime("%Y-%m-%d")
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
                        opponent = self._normalize_nba_abbrev(comp_team.get("abbreviation", "UNK"))

                game = PlayerScheduleGame(
                    date=game_date_str,
                    opponent=opponent,
                    is_home=is_home,
                    game_id=event.get("id"),
                    datetimeISO=tip_off_iso,
                )
                games.append(game)

        # Count games in this and next window. Callers that know the matchup period pass the
        # windows in; otherwise fall back to the Monday-to-Sunday week containing start_date.
        if this_window is None:
            try:
                league_settings = await self.get_league_settings()
                week_start_day = self._infer_week_start_day(league_settings)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Could not get league settings for week boundaries: {e}")
                week_start_day = 0  # Monday
            week_start, week_end = self._get_week_boundaries(start_date, week_start_day)
            this_window = (date.fromisoformat(week_start), date.fromisoformat(week_end))
        if next_window is None:
            next_window = (this_window[1] + timedelta(days=1), this_window[1] + timedelta(days=7))

        games_this_week = 0
        games_next_week = 0
        for game in games:
            game_day = date.fromisoformat(game.date)
            if this_window[0] <= game_day <= this_window[1]:
                games_this_week += 1
            elif next_window[0] <= game_day <= next_window[1]:
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
        self,
        team_id: int,
        start_date: str | None = None,
        end_date: str | None = None,
        matchup_period: int | None = None,
    ) -> RosterScheduleSummary:
        """Get schedule summary for all players on a fantasy roster.

        When a matchup period is given, "this week" and "next week" are that period and the
        next one, using ESPN's matchupPeriods mapping (so uneven weeks are handled). Otherwise
        they are the Monday-to-Sunday week containing start_date and the week after.

        Args:
            team_id: Fantasy team ID
            start_date: Start date in YYYY-MM-DD format (default: today)
            end_date: End date in YYYY-MM-DD format (default: start + 7 days)
            matchup_period: Matchup period (week) to summarize; overrides the dates

        Returns:
            RosterScheduleSummary with schedule data for all rostered players

        Raises:
            ValueError: If team_id or dates are invalid
        """
        # Validate inputs
        self._validate_positive_int(team_id, "team_id")

        try:
            league_settings: LeagueSettings | None = await self.get_league_settings()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to get league settings, using date-based calculation: {e}")
            league_settings = None

        this_window: tuple[date, date] | None = None
        next_window: tuple[date, date] | None = None
        if matchup_period:
            this_window = await self.get_matchup_period_dates(matchup_period, league_settings)
            if this_window is not None:
                next_window = await self.get_matchup_period_dates(
                    matchup_period + 1, league_settings
                )
                if next_window is None:
                    next_window = (
                        this_window[1] + timedelta(days=1),
                        this_window[1] + timedelta(days=7),
                    )
                # Fetch enough schedule to cover both windows
                start_date = this_window[0].isoformat()
                end_date = next_window[1].isoformat()

        if not start_date:
            start_date = datetime.now(ZoneInfo(self._get_timezone())).date().isoformat()
        if not end_date:
            end_date = (date.fromisoformat(start_date) + timedelta(days=7)).isoformat()

        if this_window is None:
            week_start_day = self._infer_week_start_day(league_settings)
            week_start, week_end = self._get_week_boundaries(start_date, week_start_day)
            this_window = (date.fromisoformat(week_start), date.fromisoformat(week_end))
            next_window = (this_window[1] + timedelta(days=1), this_window[1] + timedelta(days=7))

        # Get the roster first
        roster = await self.get_team_roster(team_id)

        player_schedules = []
        total_games_this_week = 0
        total_games_next_week = 0

        # Get every player's schedule concurrently. Players without an NBA team (proTeamId 0,
        # i.e. unsigned) are skipped. Teammates share one cached/in-flight schedule request.
        async def fetch_schedule(entry: RosterEntry) -> PlayerSchedule:
            player = entry.playerPoolEntry.player
            assert player.proTeamId is not None  # filtered below
            schedule = await self.get_player_schedule(
                player.id, player.proTeamId, start_date, end_date, this_window, next_window
            )
            schedule.playerName = player.fullName  # use the roster's name
            return schedule

        with_team = [e for e in roster.entries if e.playerPoolEntry.player.proTeamId]
        results = await asyncio.gather(
            *(fetch_schedule(e) for e in with_team), return_exceptions=True
        )
        for entry, result in zip(with_team, results, strict=True):
            if isinstance(result, BaseException):
                name = entry.playerPoolEntry.player.fullName
                logger.warning(f"Failed to get schedule for player {name}: {result}")
                continue
            player_schedules.append(result)
            total_games_this_week += result.gamesThisWeek
            total_games_next_week += result.gamesNextWeek

        # Calculate average
        avg_games = total_games_this_week / len(player_schedules) if player_schedules else 0.0

        # Determine scoring period if not provided
        determined_scoring_period = matchup_period
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

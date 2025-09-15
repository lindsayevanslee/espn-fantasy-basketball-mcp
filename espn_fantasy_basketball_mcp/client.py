"""ESPN Fantasy Basketball API client."""

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
    PlayerStats,
    Roster,
    RosterEntry,
    Team,
    TeamDraftSummary,
    TradeAnalysis,
    TrendingPlayer,
)


class ESPNFantasyBasketballClient:
    """Client for ESPN Fantasy Basketball API."""

    BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba"
    NBA_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"

    def __init__(self, league_id: int, year: int, espn_s2: str | None = None, swid: str | None = None):
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

    async def _make_request(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make HTTP request to ESPN API."""
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, cookies=self.cookies)
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

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
                record=team_data.get("record")
            )
            teams.append(team)

        return teams

    async def get_team_roster(self, team_id: int, scoring_period: int | None = None) -> Roster:
        """Get roster for a specific team."""
        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        params = {"view": "mRoster"}

        if scoring_period:
            params["scoringPeriodId"] = str(scoring_period)

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

    async def get_free_agents(self, size: int = 50, position_id: int | None = None) -> list[Player]:
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

    async def get_nba_schedule(self, date: str | None = None) -> list[NBAGame]:
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
                keeper=pick_data.get("keeper", False)
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
            currentNominatingTeam=current_nominating_team
        )

    async def get_available_players(self, limit: int = 100) -> list[PlayerDraftInfo]:
        """Get available players for draft with auction values."""
        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        params = {"view": "kona_player_info"}

        data = await self._make_request(url, params)

        # Get current draft status to see who's been drafted
        draft_status = await self.get_draft_status()
        drafted_players = {pick.playerId: (pick.teamId, pick.bidAmount) for pick in draft_status.picks}

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
                injuryStatus=player_data.get("injuryStatus")
            )

            # Get auction value from draft rankings
            auction_value = None
            rank = None
            if player_data.get("draftRanksByRankType", {}).get("STANDARD"):
                auction_value = player_data["draftRanksByRankType"]["STANDARD"].get("auctionValue", 0)
                rank = player_data["draftRanksByRankType"]["STANDARD"].get("rank")

            player_draft_info = PlayerDraftInfo(
                playerId=player_id,
                player=player,
                draftAuctionValue=player_entry.get("draftAuctionValue", 0),
                auctionValue=auction_value,
                rank=rank,
                isDrafted=False
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
        position_counts: dict[str, int] = {}
        for _pick in team_picks:
            # This would need player data to get actual positions
            # For now, just count total players
            pass

        return TeamDraftSummary(
            teamId=team_id,
            teamName=team_name,
            totalSpent=total_spent,
            playersCount=players_count,
            remainingBudget=remaining_budget,
            positionCounts=position_counts
        )

    async def get_draft_recommendation(self, team_id: int, current_player_id: int | None = None) -> DraftRecommendation:
        """Get draft recommendation for current situation."""
        # Get team's current status
        team_summary = await self.get_team_draft_summary(team_id)

        # Get available players
        available_players = await self.get_available_players(50)

        if current_player_id:
            # Player is currently being nominated - should we bid?
            current_player = next((p for p in available_players if p.playerId == current_player_id), None)

            if not current_player:
                return DraftRecommendation(
                    action="pass",
                    reasoning="Player not found in available players list",
                    priority=1
                )

            # Simple bidding logic
            player_value = current_player.auctionValue or 0
            max_affordable = min(team_summary.remainingBudget - (13 - team_summary.playersCount), player_value)

            if player_value >= 10 and max_affordable >= player_value * 0.8:
                return DraftRecommendation(
                    action="bid",
                    playerId=current_player_id,
                    playerName=current_player.player.fullName,
                    suggestedBid=min(player_value, max_affordable),
                    maxBid=max_affordable,
                    reasoning=f"Good value player worth ${player_value}. You can afford up to ${max_affordable}.",
                    priority=7,
                    category_impact={"value": "positive"}
                )
            else:
                return DraftRecommendation(
                    action="pass",
                    playerName=current_player.player.fullName,
                    reasoning=f"Player value (${player_value}) too high for remaining budget (${team_summary.remainingBudget})",
                    priority=3
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
                    category_impact={"overall": "strong positive"}
                )

            return DraftRecommendation(
                action="pass",
                reasoning="No quality players available",
                priority=1
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
            "recommendation": f"You have ${team_summary.remainingBudget} for {13 - team_summary.playersCount} more players"
        }

    async def get_player_stats(self, player_id: int, timeframe: str = "season") -> PlayerStats:
        """Get comprehensive player statistics for specified timeframe."""
        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"

        # Determine the appropriate view and parameters based on timeframe
        if timeframe == "projections":
            params = {"view": "kona_player_info"}
        else:
            params = {"view": "mPlayer"}

        data = await self._make_request(url, params)

        # Find the specific player in the response
        player_data = None
        for player_entry in data.get("players", []):
            if player_entry["player"]["id"] == player_id:
                player_data = player_entry
                break

        if not player_data:
            raise ValueError(f"Player {player_id} not found")

        player_info = player_data["player"]

        # Extract stats based on timeframe
        stats = self._extract_player_stats(player_data, timeframe)

        return PlayerStats(
            playerId=player_id,
            playerName=player_info.get("fullName", "Unknown Player"),
            timeframe=timeframe,
            **stats
        )

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
            "0": "points",          # Points
            "1": "rebounds",        # Rebounds
            "2": "assists",         # Assists
            "3": "steals",          # Steals
            "4": "blocks",          # Blocks
            "17": "threePointMade", # 3PM
            "19": "fieldGoalPercentage",  # FG%
            "20": "freeThrowPercentage",  # FT%
            "11": "turnovers",      # Turnovers
            "40": "minutes",        # Minutes
            "gamesPlayed": "gamesPlayed"
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

    async def compare_players(self, player_ids: list[int], categories: list[str] | None = None) -> PlayerComparison:
        """Compare multiple players across specified statistical categories."""
        if categories is None:
            categories = ["points", "rebounds", "assists", "steals", "blocks", "threePointMade",
                         "fieldGoalPercentage", "freeThrowPercentage", "turnovers"]

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
                        (value > best_value and not reverse) or
                        (value < best_value and reverse)
                    ):
                        best_value = value
                        best_player_id = player_stats.playerId

            if best_player_id:
                winner_by_category[category] = best_player_id

        # Generate overall recommendation
        category_wins = {}
        for player_stats in players_stats:
            category_wins[player_stats.playerId] = sum(
                1 for winner in winner_by_category.values()
                if winner == player_stats.playerId
            )

        best_overall = max(category_wins.items(), key=lambda x: x[1])
        best_player_name = next(
            p.playerName for p in players_stats if p.playerId == best_overall[0]
        )

        overall_recommendation = f"{best_player_name} wins {best_overall[1]}/{len(categories)} categories"
        analysis = f"Detailed comparison across {len(categories)} statistical categories. " \
                  f"{best_player_name} provides the most balanced production."

        return PlayerComparison(
            players=players_stats,
            categories=categories,
            winner_by_category=winner_by_category,
            overall_recommendation=overall_recommendation,
            analysis=analysis
        )

    async def analyze_trade_proposal(
        self,
        your_player_ids: list[int],
        their_player_ids: list[int]
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
                reasoning = f"You lose some value ({value_difference:.1f} fantasy points), try to get more"

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
            confidence=confidence
        )

    def _analyze_category_impact(self, your_players: list[PlayerStats], their_players: list[PlayerStats]) -> dict[str, str]:
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

    async def get_trending_players(self, direction: str = "up", limit: int = 20) -> list[TrendingPlayer]:
        """Get players trending up or down in adds/drops."""
        url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
        params = {"view": "kona_player_info"}

        data = await self._make_request(url, params)

        trending_players = []

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
                defaultPositionId=player_info["defaultPositionId"]
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
                trend_direction="up" if is_trending_up else "down" if is_trending_down else "stable",
                add_percentage=max(0, add_percentage),
                drop_percentage=max(0, -add_percentage),
                net_adds=int(add_percentage * 100),  # Approximate
                reason=reason
            )

            trending_players.append(trending_player)

        # Sort by trending strength
        trending_players.sort(key=lambda x: abs(x.add_percentage - x.drop_percentage), reverse=True)

        return trending_players

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
    PlayerDraftInfo,
    PlayerPoolEntry,
    Roster,
    RosterEntry,
    Team,
    TeamDraftSummary,
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

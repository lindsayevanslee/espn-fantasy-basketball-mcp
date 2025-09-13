"""ESPN Fantasy Basketball MCP Server."""

import asyncio
import json
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from .client import ESPNFantasyBasketballClient

server = Server("espn-fantasy-basketball")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools."""
    return [
        types.Tool(
            name="get_league_teams",
            description="Get all teams in an ESPN Fantasy Basketball league",
            inputSchema={
                "type": "object",
                "properties": {
                    "league_id": {
                        "type": "integer",
                        "description": "ESPN Fantasy Basketball league ID"
                    },
                    "year": {
                        "type": "integer",
                        "description": "Season year (e.g., 2025)"
                    },
                    "espn_s2": {
                        "type": "string",
                        "description": "ESPN authentication cookie for private leagues (optional)"
                    },
                    "swid": {
                        "type": "string",
                        "description": "ESPN SWID cookie for private leagues (optional)"
                    }
                },
                "required": ["league_id", "year"]
            }
        ),
        types.Tool(
            name="get_team_roster",
            description="Get roster for a specific team in an ESPN Fantasy Basketball league",
            inputSchema={
                "type": "object",
                "properties": {
                    "league_id": {
                        "type": "integer",
                        "description": "ESPN Fantasy Basketball league ID"
                    },
                    "year": {
                        "type": "integer",
                        "description": "Season year (e.g., 2025)"
                    },
                    "team_id": {
                        "type": "integer",
                        "description": "Team ID to get roster for"
                    },
                    "scoring_period": {
                        "type": "integer",
                        "description": "Specific scoring period (optional)"
                    },
                    "espn_s2": {
                        "type": "string",
                        "description": "ESPN authentication cookie for private leagues (optional)"
                    },
                    "swid": {
                        "type": "string",
                        "description": "ESPN SWID cookie for private leagues (optional)"
                    }
                },
                "required": ["league_id", "year", "team_id"]
            }
        ),
        types.Tool(
            name="get_free_agents",
            description="Get free agents/waiver wire players from an ESPN Fantasy Basketball league",
            inputSchema={
                "type": "object",
                "properties": {
                    "league_id": {
                        "type": "integer",
                        "description": "ESPN Fantasy Basketball league ID"
                    },
                    "year": {
                        "type": "integer",
                        "description": "Season year (e.g., 2025)"
                    },
                    "size": {
                        "type": "integer",
                        "description": "Number of players to return (max 50, default 50)",
                        "default": 50
                    },
                    "position_id": {
                        "type": "integer",
                        "description": "Filter by position ID (optional)"
                    },
                    "espn_s2": {
                        "type": "string",
                        "description": "ESPN authentication cookie for private leagues (optional)"
                    },
                    "swid": {
                        "type": "string",
                        "description": "ESPN SWID cookie for private leagues (optional)"
                    }
                },
                "required": ["league_id", "year"]
            }
        ),
        types.Tool(
            name="get_matchups",
            description="Get matchups/schedule for an ESPN Fantasy Basketball league",
            inputSchema={
                "type": "object",
                "properties": {
                    "league_id": {
                        "type": "integer",
                        "description": "ESPN Fantasy Basketball league ID"
                    },
                    "year": {
                        "type": "integer",
                        "description": "Season year (e.g., 2025)"
                    },
                    "scoring_period": {
                        "type": "integer",
                        "description": "Specific scoring period to get matchups for (optional)"
                    },
                    "espn_s2": {
                        "type": "string",
                        "description": "ESPN authentication cookie for private leagues (optional)"
                    },
                    "swid": {
                        "type": "string",
                        "description": "ESPN SWID cookie for private leagues (optional)"
                    }
                },
                "required": ["league_id", "year"]
            }
        ),
        types.Tool(
            name="get_nba_schedule",
            description="Get NBA schedule for a specific date",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format (optional, defaults to today)"
                    }
                },
                "required": []
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    """Handle tool calls."""

    if name == "get_league_teams":
        league_id = arguments["league_id"]
        year = arguments["year"]
        espn_s2 = arguments.get("espn_s2")
        swid = arguments.get("swid")

        client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
        teams = await client.get_league_teams()

        return [
            types.TextContent(
                type="text",
                text=json.dumps([team.model_dump() for team in teams], indent=2)
            )
        ]

    elif name == "get_team_roster":
        league_id = arguments["league_id"]
        year = arguments["year"]
        team_id = arguments["team_id"]
        scoring_period = arguments.get("scoring_period")
        espn_s2 = arguments.get("espn_s2")
        swid = arguments.get("swid")

        client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
        roster = await client.get_team_roster(team_id, scoring_period)

        return [
            types.TextContent(
                type="text",
                text=json.dumps(roster.model_dump(), indent=2)
            )
        ]

    elif name == "get_free_agents":
        league_id = arguments["league_id"]
        year = arguments["year"]
        size = arguments.get("size", 50)
        position_id = arguments.get("position_id")
        espn_s2 = arguments.get("espn_s2")
        swid = arguments.get("swid")

        client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
        players = await client.get_free_agents(size, position_id)

        return [
            types.TextContent(
                type="text",
                text=json.dumps([player.model_dump() for player in players], indent=2)
            )
        ]

    elif name == "get_matchups":
        league_id = arguments["league_id"]
        year = arguments["year"]
        scoring_period = arguments.get("scoring_period")
        espn_s2 = arguments.get("espn_s2")
        swid = arguments.get("swid")

        client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
        matchups = await client.get_matchups(scoring_period)

        return [
            types.TextContent(
                type="text",
                text=json.dumps([matchup.model_dump() for matchup in matchups], indent=2)
            )
        ]

    elif name == "get_nba_schedule":
        date = arguments.get("date")

        # Create a temporary client just for NBA API access
        client = ESPNFantasyBasketballClient(1, 2025)  # Dummy values for NBA API
        games = await client.get_nba_schedule(date)

        return [
            types.TextContent(
                type="text",
                text=json.dumps([game.model_dump() for game in games], indent=2)
            )
        ]

    else:
        raise ValueError(f"Unknown tool: {name}")


async def main() -> None:
    """Main entry point for the server."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="espn-fantasy-basketball",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())

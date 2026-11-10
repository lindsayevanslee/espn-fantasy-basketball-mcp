"""Serve recorded ESPN responses from tests/fixtures instead of the network.

`fixture_name` maps one ESPN request (URL, query, x-fantasy-filter) to a fixture file name.
It is shared by the tests (to look fixtures up) and by scripts/record_fixtures.py (to write
them), so a recorded set is a drop-in replacement for the synthetic one.

`FixtureESPN` is an async callable with the signature of
ESPNFantasyBasketballClient._make_request; `use_fixtures` installs it on the class, freezes
"now" at the scenario date (Sunday 2026-11-01, Eastern) and clears the response cache.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

# The synthetic scenario: last day of matchup period 2 of the 2026-27 season, noon Eastern.
FROZEN_NOW = datetime(2026, 11, 1, 12, 0, tzinfo=ZoneInfo("America/New_York"))

_TEAM_SCHEDULE = re.compile(r"/teams/(\d+)/schedule$")


def fixture_name(
    url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
) -> str | None:
    """Fixture file for an ESPN request, or None if the request is not one we record."""
    if url.endswith("/injuries"):
        return "nba_injuries.json"
    if url.endswith("/scoreboard"):
        day = (params or {}).get("dates")
        if day and day != "20261101":
            # a date with no fixture is a day with no games, never today's slate
            return f"nba_scoreboard_{day}.json"
        return "nba_scoreboard.json"
    match = _TEAM_SCHEDULE.search(url)
    if match:
        return f"nba_team_schedule_{match.group(1)}.json"
    if url.endswith("/players"):
        return "players_wl.json"
    view = (params or {}).get("view")
    views = set(view) if isinstance(view, list) else ({view} if view else set())
    fantasy_filter = (headers or {}).get("x-fantasy-filter") or ""
    if "kona_player_info" in views:
        if "filterStatus" in fantasy_filter:
            return "league_kona_free_agents.json"
        return "league_kona_player_info.json"
    if "mTransactions2" in views:
        return "league_mTransactions.json"
    if "mMatchup" in views:
        return "league_mMatchup.json"
    if "mRoster" in views:
        return "league_mRoster.json"
    if "mSettings" in views:
        return "league_mSettings.json"
    if "mTeam" in views:
        return "league_mTeam.json"
    return None


class FixtureESPN:
    """Stand-in for ESPNFantasyBasketballClient._make_request backed by fixture files."""

    def __init__(self, directory: Path = FIXTURE_DIR):
        self.directory = directory
        self.requests: list[tuple[str, dict[str, Any] | None, dict[str, str] | None]] = []
        self._cache: dict[str, Any] = {}
        self.echo_scoring_period = True

    def load(self, name: str) -> Any:
        if name not in self._cache:
            self._cache[name] = json.loads((self.directory / name).read_text())
        return copy.deepcopy(self._cache[name])

    async def __call__(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        self.requests.append((url, params, headers))
        name = fixture_name(url, params, headers)
        if name and name.startswith("nba_scoreboard_") and not (self.directory / name).is_file():
            return {"day": {"date": (params or {}).get("dates")}, "events": []}
        if name is None or not (self.directory / name).is_file():
            raise httpx.HTTPError(f"no fixture for {url} {params} ({name})")
        data = self.load(name)
        # Like ESPN (verified live 2026-11-10), echo the requested scoring period back
        requested = (params or {}).get("scoringPeriodId")
        if self.echo_scoring_period and requested and isinstance(data, dict):
            data["scoringPeriodId"] = int(requested)
        return data

    def requests_for(self, fixture: str) -> list[tuple[str, dict[str, Any] | None, dict | None]]:
        return [r for r in self.requests if fixture_name(*r) == fixture]


class FrozenDatetime(datetime):
    """datetime whose now() is pinned to FROZEN_NOW; everything else is inherited."""

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        if tz is None:
            return FROZEN_NOW.replace(tzinfo=None)
        return FROZEN_NOW.astimezone(tz)


def use_fixtures(monkeypatch, directory: Path = FIXTURE_DIR) -> FixtureESPN:
    """Route every ESPN request to fixtures and freeze the clock. Returns the router."""
    from espn_fantasy_basketball_mcp import analysis as analysis_module
    from espn_fantasy_basketball_mcp import client as client_module
    from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient

    router = FixtureESPN(directory)

    async def fake_make_request(self, url, params=None, headers=None):
        return await router(url, params, headers)

    monkeypatch.setenv("MY_TIMEZONE", "America/New_York")
    monkeypatch.setattr(ESPNFantasyBasketballClient, "_make_request", fake_make_request)
    monkeypatch.setattr(client_module, "datetime", FrozenDatetime)
    monkeypatch.setattr(analysis_module, "datetime", FrozenDatetime)
    ESPNFantasyBasketballClient.clear_cache()
    return router

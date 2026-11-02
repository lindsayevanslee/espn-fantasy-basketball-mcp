#!/usr/bin/env python3
"""Record real ESPN responses for your league into tests/fixtures/recorded/, identifiers stripped.

Runs the same client calls the MCP tools make, captures every ESPN response on the way, and
writes each one under the name tests/fixture_espn.py would look it up by. The recorded set is
therefore a drop-in replacement for the synthetic fixtures in tests/fixtures/ (point
FixtureESPN at the directory) and a faithful record of what ESPN actually sends.

Before anything is written it is sanitised:
- `members` blocks and cookie-like keys are removed entirely
- `owners`, `primaryOwner` and `memberId` values are replaced
- every GUID-shaped string (ESPN SWIDs are GUIDs) and every espn_s2-shaped token anywhere in
  the payload is replaced
Team names, league name and player data are kept; pass --redact-names to replace team and
league names too. Cookie values are never printed or written. tests/test_fixture_hygiene.py
checks every file under tests/fixtures for leaks on each test run.

Usage (from the repository root):

    uv run python scripts/record_fixtures.py [--out DIR] [--redact-names] [--year 2027]

Credentials come from the environment (ESPN_LEAGUE_ID, ESPN_TEAM_ID, ESPN_S2, ESPN_SWID,
ESPN_YEAR, MY_TIMEZONE) or, when missing, from your Claude Desktop config like verify_live.py.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from espn_fantasy_basketball import _default_season  # noqa: E402
from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient  # noqa: E402
from scripts.verify_live import load_claude_desktop_env  # noqa: E402
from tests.fixture_espn import fixture_name  # noqa: E402

GUID_RE = re.compile(
    r"\{?[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}?"
)
# espn_s2 cookies are long URL-safe tokens starting with "AE"
ESPN_S2_RE = re.compile(r"AE[A-Za-z0-9%+/=_-]{60,}")
DROP_KEYS = {"members", "cookie", "cookies", "set-cookie", "espn_s2", "swid"}
REDACT_KEYS = {"owners", "primaryowner", "memberid"}
NAME_KEYS = {"name", "location", "nickname", "abbrev"}

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "recorded"


def sanitize(obj: Any, redact_names: bool = False, _in_team: bool = False) -> Any:
    """Return a copy of `obj` with account identifiers removed. Pure; never logs."""
    if isinstance(obj, dict):
        is_team = "abbrev" in obj and "id" in obj and "owners" in obj
        out: dict[str, Any] = {}
        for key, value in obj.items():
            lowered = key.lower()
            if lowered in DROP_KEYS:
                continue
            if lowered in REDACT_KEYS:
                out[key] = (
                    ["REDACTED-ID"] * len(value) if isinstance(value, list) else "REDACTED-ID"
                )
                continue
            if redact_names and is_team and lowered in NAME_KEYS and isinstance(value, str):
                out[key] = f"Team {obj.get('id')}" if lowered == "name" else "REDACTED"
                continue
            if redact_names and lowered == "name" and "scoringSettings" in obj:
                out[key] = "Redacted League"
                continue
            out[key] = sanitize(value, redact_names, is_team)
        return out
    if isinstance(obj, list):
        return [sanitize(v, redact_names, _in_team) for v in obj]
    if isinstance(obj, str):
        return ESPN_S2_RE.sub("REDACTED-TOKEN", GUID_RE.sub("REDACTED-ID", obj))
    return obj


def merge_players(existing: Any, incoming: Any) -> Any:
    """kona_player_info requests for different ID sets share one file: union their players."""
    if not (isinstance(existing, dict) and isinstance(incoming, dict)):
        return incoming
    if "players" not in existing or "players" not in incoming:
        return incoming
    by_id = {p.get("id"): p for p in existing["players"] if isinstance(p, dict)}
    for p in incoming["players"]:
        if isinstance(p, dict):
            by_id[p.get("id")] = p
    merged = dict(incoming)
    merged["players"] = list(by_id.values())
    return merged


class Recorder:
    def __init__(self, out: Path, redact_names: bool):
        self.out = out
        self.redact_names = redact_names
        self.written: dict[str, Any] = {}
        self.unmapped: list[str] = []
        self.failures: list[str] = []

    def capture(self, url: str, params: Any, headers: Any, data: Any) -> None:
        name = fixture_name(url, params, headers)
        if name is None:
            self.unmapped.append(f"{url} {params}")
            return
        clean = sanitize(data, self.redact_names)
        if name in self.written and name.startswith("league_kona_player_info"):
            clean = merge_players(self.written[name], clean)
        self.written[name] = clean

    def flush(self) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        for name, data in self.written.items():
            (self.out / name).write_text(json.dumps(data, indent=1) + "\n")
        (self.out / "README.md").write_text(
            "Recorded ESPN responses for this league, sanitised by scripts/record_fixtures.py.\n"
            "Re-record with `uv run python scripts/record_fixtures.py`. Do not edit by hand.\n"
        )


async def record(client: ESPNFantasyBasketballClient, team_id: int, recorder: Recorder) -> None:
    original = client._make_request

    async def recording_request(url, params=None, headers=None):
        data = await original(url, params, headers)
        recorder.capture(url, params, headers, data)
        return data

    client._make_request = recording_request  # type: ignore[method-assign]

    settings = await client.get_league_settings()
    current = settings.status.currentMatchupPeriod
    print(f"league '{settings.leagueName}', matchup period {current}")

    async def step(name: str, coro: Any) -> Any:
        """Run one tool call; a failure is reported and recorded, never fatal."""
        try:
            result = await coro
            print(f"  ok   {name}")
            return result
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
            recorder.failures.append(f"{name}: {type(exc).__name__}: {exc}")
            return None

    await step("get_league_teams", client.get_league_teams())
    await step("get_matchups(current)", client.get_matchups(matchup_period=current))
    roster = await step("get_team_roster", client.get_team_roster(team_id))
    await step("get_free_agents(verbose)", client.get_free_agents(size=50, verbose=True))
    await step("get_my_current_matchup", client.get_my_current_matchup(team_id, verbose=True))
    await step("analyze_matchup(current)", client.analyze_matchup(team_id, current))
    await step("analyze_matchup(next)", client.analyze_matchup(team_id, current + 1))
    await step(
        "get_roster_schedule_summary",
        client.get_roster_schedule_summary(team_id, matchup_period=current),
    )
    if roster is not None and roster.entries:
        surname = roster.entries[0].playerPoolEntry.player.lastName or "a"
        await step("search_players", client.search_players(surname, 3))


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory")
    parser.add_argument("--redact-names", action="store_true", help="also redact team names")
    parser.add_argument("--year", type=int, help="ESPN season ID, overriding ESPN_YEAR")
    parser.add_argument("--config", help="path to claude_desktop_config.json")
    parser.add_argument("--server", help="mcpServers entry to read env from")
    args = parser.parse_args()

    load_claude_desktop_env(args.config, args.server)
    league_id = os.getenv("ESPN_LEAGUE_ID")
    team_id = os.getenv("ESPN_TEAM_ID")
    if not league_id or not team_id:
        print("ESPN_LEAGUE_ID and ESPN_TEAM_ID are required (environment or Claude config).")
        return 2
    year = args.year or int(os.getenv("ESPN_YEAR") or _default_season())
    client = ESPNFantasyBasketballClient(
        int(league_id), year, os.getenv("ESPN_S2"), os.getenv("ESPN_SWID")
    )
    recorder = Recorder(args.out, args.redact_names)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is noise
    try:
        await record(client, int(team_id), recorder)
    finally:
        recorder.flush()  # keep whatever was captured even if a step blew up
    if recorder.failures:
        print("steps that failed (responses captured before the failure were still written):")
        for item in recorder.failures:
            print(f"  {item}")
    print(f"wrote {len(recorder.written)} fixtures to {args.out}")
    for name in sorted(recorder.written):
        print(f"  {name}")
    if recorder.unmapped:
        print("requests with no fixture name (not written):")
        for item in recorder.unmapped:
            print(f"  {item}")
    print("run `uv run pytest tests/test_fixture_hygiene.py` to confirm nothing leaked")
    return 1 if recorder.failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

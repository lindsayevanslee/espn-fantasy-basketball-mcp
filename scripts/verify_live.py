#!/usr/bin/env python3
"""Verify the MCP server against your live ESPN league. Read-only.

Runs a handful of real requests through the same client the MCP tools use and prints a
PASS / FAIL / SKIP report. Nothing is written to ESPN. Cookie values are never printed.

Usage (from the repository root):

    uv run python scripts/verify_live.py

Credentials are taken from the environment (ESPN_LEAGUE_ID, ESPN_TEAM_ID, ESPN_S2, ESPN_SWID,
and optionally ESPN_YEAR, MY_TIMEZONE). Anything not set there is read from the `env` block of
this server's entry in your Claude Desktop config, so if Claude Desktop already works you need
no extra setup. Override the config location with --config PATH, or pick a specific server entry
with --server NAME.

Exit code: 0 if no check failed, 1 if any failed, 2 if configuration is missing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from espn_fantasy_basketball import _default_season  # noqa: E402
from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient  # noqa: E402

ENV_KEYS = ("ESPN_LEAGUE_ID", "ESPN_TEAM_ID", "ESPN_S2", "ESPN_SWID", "ESPN_YEAR", "MY_TIMEZONE")


def default_claude_config_paths() -> list[Path]:
    """Where Claude Desktop keeps claude_desktop_config.json on each platform."""
    home = Path.home()
    return [
        home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
        Path(os.getenv("APPDATA", home / "AppData" / "Roaming"))
        / "Claude"
        / "claude_desktop_config.json",
        home / ".config" / "Claude" / "claude_desktop_config.json",
    ]


def pick_server(
    servers: dict[str, Any], preferred: str | None
) -> tuple[str, dict[str, str]] | None:
    """Choose the MCP server entry whose env block configures this project.

    Preference: an explicitly named server; otherwise the entry whose args mention this
    repository; otherwise the first entry with ESPN_LEAGUE_ID in its env.
    """
    if preferred:
        entry = servers.get(preferred)
        return (preferred, dict(entry.get("env", {}))) if isinstance(entry, dict) else None
    repo_dir = str(Path(__file__).resolve().parent.parent)
    with_league = [
        (name, dict(entry.get("env", {})))
        for name, entry in servers.items()
        if isinstance(entry, dict) and "ESPN_LEAGUE_ID" in entry.get("env", {})
    ]
    for name, env in with_league:
        args = " ".join(str(a) for a in servers[name].get("args", []))
        if repo_dir in args or "espn_fantasy_basketball" in args:
            return name, env
    return with_league[0] if with_league else None


def load_claude_desktop_env(config_path: str | None, server: str | None) -> str | None:
    """Fill missing ESPN_* / MY_TIMEZONE variables from the Claude Desktop config.

    Existing environment variables always win. Returns a description of what was used
    (file, server name, variable names), or None if nothing was loaded. Never logs values.
    """
    missing = [k for k in ENV_KEYS if not os.getenv(k)]
    if not missing:
        return None
    paths = [Path(config_path).expanduser()] if config_path else default_claude_config_paths()
    for path in paths:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            print(f"       could not read {path}: {exc}")
            continue
        chosen = pick_server(data.get("mcpServers", {}), server)
        if not chosen:
            continue
        name, env = chosen
        loaded = [k for k in missing if env.get(k)]
        for k in loaded:
            os.environ[k] = str(env[k])
        return f"{path} -> mcpServers['{name}'] supplied {loaded}"
    return None


# Teams whose abbreviations differ between ESPN endpoints. These are the ones the
# abbreviation bug affected; the rest of the league was already fine.
TRICKY_TEAMS = {9: "GSW", 26: "UTA", 27: "WAS", 3: "NOP", 18: "NYK", 24: "SAS"}


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def _add(self, status: str, name: str, detail: str = "") -> None:
        self.rows.append((status, name, detail))
        line = f"[{status}] {name}"
        if detail:
            line += f"\n       {detail}"
        print(line)

    def check(self, ok: bool, name: str, detail: str = "") -> bool:
        self._add("PASS" if ok else "FAIL", name, detail)
        return ok

    def skip(self, name: str, detail: str = "") -> None:
        self._add("SKIP", name, detail)

    def info(self, text: str) -> None:
        print(f"       {text}")

    def error(self, name: str, exc: BaseException) -> None:
        self._add("FAIL", name, f"{type(exc).__name__}: {exc}")

    @property
    def failed(self) -> int:
        return sum(1 for s, _, _ in self.rows if s == "FAIL")

    def summary(self) -> None:
        counts = {s: sum(1 for r in self.rows if r[0] == s) for s in ("PASS", "FAIL", "SKIP")}
        print("\n" + "=" * 72)
        print(f"PASS {counts['PASS']}   FAIL {counts['FAIL']}   SKIP {counts['SKIP']}")
        if counts["FAIL"]:
            print("Failed checks:")
            for s, name, detail in self.rows:
                if s == "FAIL":
                    print(f"  - {name}" + (f": {detail}" if detail else ""))


def section(title: str) -> None:
    print("\n" + "-" * 72)
    print(title)
    print("-" * 72)


def _scoreboard_abbrevs(raw: dict[str, Any]) -> list[str]:
    codes: set[str] = set()
    for event in raw.get("events", []):
        for comp in event.get("competitions", [{}])[0].get("competitors", []):
            codes.add(comp.get("team", {}).get("abbreviation", "?"))
    return sorted(codes)


async def next_game_dates(
    client: ESPNFantasyBasketballClient, teams: dict[int, str], days: int = 10
) -> dict[str, str]:
    """Find the next date (within `days`) each team plays, via the daily scoreboard."""
    found: dict[str, str] = {}
    wanted = set(teams.values())
    for offset in range(1, days + 1):
        day = (date.today() + timedelta(days=offset)).isoformat()
        games = await client.get_nba_schedule(day)
        for game in games:
            for competitor in game.competitions[0].competitors:
                code = client._normalize_nba_abbrev(competitor.team.abbreviation)
                if code in wanted and code not in found:
                    found[code] = day
        if wanted <= set(found):
            break
    return found


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--config", help="path to claude_desktop_config.json (default: platform location)"
    )
    parser.add_argument("--server", help="name of the mcpServers entry to read env from")
    args = parser.parse_args()

    report = Report()

    section("Configuration")
    source = load_claude_desktop_env(args.config, args.server)
    report.info(
        source or "all variables taken from the environment; Claude Desktop config not read"
    )

    league_id = os.getenv("ESPN_LEAGUE_ID")
    team_id_raw = os.getenv("ESPN_TEAM_ID")
    espn_s2 = os.getenv("ESPN_S2")
    swid = os.getenv("ESPN_SWID")
    if not league_id or not team_id_raw:
        print(__doc__)
        print(
            "ESPN_LEAGUE_ID and ESPN_TEAM_ID are required, in the environment or in your Claude Desktop config."
        )
        print("Looked for the config at:")
        for path in (
            [Path(args.config).expanduser()] if args.config else default_claude_config_paths()
        ):
            print(f"  {'found' if path.is_file() else 'missing'}: {path}")
        return 2
    team_id = int(team_id_raw)

    year_env = os.getenv("ESPN_YEAR")
    year = int(year_env) if year_env else _default_season()

    report.info(
        f"league_id={league_id} team_id={team_id} timezone={os.getenv('MY_TIMEZONE', 'America/New_York (default)')}"
    )
    report.info(f"season={year} ({'from ESPN_YEAR' if year_env else 'computed default'})")
    report.info(
        f"cookies: espn_s2={'set' if espn_s2 else 'NOT SET'} swid={'set' if swid else 'NOT SET'}"
    )

    client = ESPNFantasyBasketballClient(int(league_id), year, espn_s2, swid)

    # ------------------------------------------------------------------ 1. season
    section("1. Season default -> league settings")
    settings = None
    try:
        settings = await client.get_league_settings()
        st = settings.status
        report.info(
            f"league='{settings.leagueName}' size={settings.size} seasonId={settings.seasonId} "
            f"scoring={settings.scoringSettings.scoringType}"
        )
        report.info(
            f"currentMatchupPeriod={st.currentMatchupPeriod} latestScoringPeriod={st.latestScoringPeriod} "
            f"isActive={st.isActive}"
        )
        report.check(
            settings.seasonId == year, "League settings come back for the requested season"
        )
        report.check(
            st.isActive,
            "Season is active",
            "" if st.isActive else "isActive=False usually means the season/year is wrong",
        )
        cats = [i.categoryName for i in settings.scoringSettings.scoringItems]
        report.info(f"scoring categories: {cats}")
    except Exception as exc:  # noqa: BLE001
        report.error("Fetch league settings", exc)
        traceback.print_exc()
        report.summary()
        return 1

    # ------------------------------------------------------------------ 2. scoreboard
    section("2. Today's NBA scoreboard -> canonical abbreviations")
    games: dict[str, Any] = {}
    team_map: dict[int, str] = {}
    try:
        raw = await client._make_request(f"{client.NBA_BASE_URL}/scoreboard")
        raw_codes = _scoreboard_abbrevs(raw)
        games, team_map = client._parse_todays_games(raw)
        static = client._get_pro_team_id_to_abbrev()
        report.info(f"{len(raw.get('events', []))} games today")
        report.info(f"raw ESPN codes:        {raw_codes}")
        report.info(f"canonical cache keys:  {sorted(games)}")
        report.check(
            len(games) == 2 * len(raw.get("events", [])),
            "Every game produced two cache entries (home and away)",
        )
        unmapped = sorted(k for k in games if k not in static.values())
        report.check(
            not unmapped,
            "Every team on today's scoreboard maps to a code in the static proTeamId map",
            f"unmapped: {unmapped}" if unmapped else "",
        )
        playing = {pid: code for pid, code in TRICKY_TEAMS.items() if code in games}
        if playing:
            for pid, code in playing.items():
                with_map = client._resolve_pro_team_abbrev(pid, None, team_map)
                static_only = client._resolve_pro_team_abbrev(pid)
                report.check(
                    with_map in games and static_only in games,
                    f"Formerly-broken team {code} (proTeamId {pid}) resolves to a cache key",
                    f"with today's map -> {with_map}, static -> {static_only}, game: {games.get(code)}",
                )
        else:
            upcoming = await next_game_dates(client, TRICKY_TEAMS)
            when = (
                ", ".join(f"{c} on {d}" for c, d in sorted(upcoming.items()))
                or "none found in 10 days"
            )
            report.skip(
                "None of GSW/UTA/WAS/NOP/NYK/SAS play today; re-run on a day one does",
                f"next games: {when}",
            )
    except Exception as exc:  # noqa: BLE001
        report.error("Fetch and parse today's scoreboard", exc)
        traceback.print_exc()

    # ------------------------------------------------------------------ 3. roster
    section("3. Your roster -> todaysGame consistency")
    try:
        roster = await client.get_team_roster(team_id)
        static_codes = set(client._get_pro_team_id_to_abbrev().values())
        mismatches: list[str] = []
        bad_codes: list[str] = []
        print(f"       {'player':<26}{'team':<6}{'slot':<7}{'injury':<12}today")
        for entry in roster.entries:
            p = entry.playerPoolEntry.player
            code = p.proTeamAbbrev
            expected = code in games if code else False
            actual = entry.todaysGame is not None
            if expected != actual:
                mismatches.append(
                    f"{p.fullName} ({code}): scoreboard={expected} todaysGame={actual}"
                )
            if p.proTeamId and code not in static_codes:
                bad_codes.append(f"{p.fullName}: proTeamId={p.proTeamId} abbrev={code}")
            tg = entry.todaysGame
            today_txt = f"{'vs' if tg.home else '@'} {tg.opponent} {tg.time}" if tg else "-"
            print(
                f"       {p.fullName[:25]:<26}{(code or '?'):<6}{(entry.lineupSlotName or ''):<7}"
                f"{(entry.injuryStatus or ''):<12}{today_txt}"
            )
        report.check(
            not mismatches,
            "Every roster player has todaysGame exactly when their team is on the scoreboard",
            "; ".join(mismatches),
        )
        report.check(
            not bad_codes,
            "Every roster player's team code is canonical",
            "; ".join(bad_codes),
        )
    except Exception as exc:  # noqa: BLE001
        report.error("Fetch roster", exc)
        traceback.print_exc()

    # ------------------------------------------------------------------ 4. analyze_matchup
    section("4. analyze_matchup (current week) -> games remaining and projections")
    try:
        current = settings.status.currentMatchupPeriod
        report.info("this makes many requests; allow 30-90 seconds")
        analysis = await client.analyze_matchup(team_id, current)
        start, end = await client._get_scoring_period_dates(current)
        if start and end:
            end = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        schedule = await client.get_roster_schedule_summary(team_id, start, end, current)
        week_games = {ps.playerId: ps.gamesThisWeek for ps in schedule.playerSchedules}

        report.info(
            f"{analysis.yourTeamName} vs {analysis.opponentTeamName}, matchup period {current}, "
            f"week {start}..{end}"
        )
        report.info(
            f"games remaining: you={analysis.yourGamesRemaining} "
            f"(of {schedule.totalGamesThisWeek} this week) opp={analysis.opponentGamesRemaining}"
        )
        report.check(
            (analysis.yourGamesRemaining or 0) <= schedule.totalGamesThisWeek,
            "Team games remaining <= games this week",
        )
        over = [
            f"{r.playerName}: remaining={r.gamesRemaining} week={week_games.get(r.playerId)}"
            for r in analysis.playerRecommendations
            if r.gamesRemaining is not None
            and week_games.get(r.playerId) is not None
            and r.gamesRemaining > week_games[r.playerId]
        ]
        report.check(
            not over, "Each player's games remaining <= their games this week", "; ".join(over)
        )

        print(
            f"\n       {'category':<22}{'you':>10}{'opp':>10}{'you proj':>10}{'opp proj':>10}  result"
        )
        regress: list[str] = []
        for c in analysis.categoryProjections:
            pct = c.category in ("fieldGoalPercentage", "freeThrowPercentage")
            fmt = (lambda v: f"{v:.3f}") if pct else (lambda v: f"{v:.0f}")
            yp = fmt(c.yourProjected) if c.yourProjected is not None else "-"
            op = fmt(c.opponentProjected) if c.opponentProjected is not None else "-"
            print(
                f"       {c.category:<22}{fmt(c.yourCurrent):>10}{fmt(c.opponentCurrent):>10}"
                f"{yp:>10}{op:>10}  {c.projectedResult}{' (close)' if c.isClose else ''}"
            )
            if not pct and c.yourProjected is not None and c.yourProjected < c.yourCurrent - 1e-6:
                regress.append(c.category)
        report.check(
            not regress,
            "Counting-category projections never fall below the current score",
            f"regressed: {regress}",
        )

        print(f"\n       {'player':<26}{'left':>5}  helped / hurt")
        for r in analysis.playerRecommendations[:15]:
            print(
                f"       {r.playerName[:25]:<26}{r.gamesRemaining or 0:>5}  "
                f"{', '.join(r.categoriesHelped) or '-'} / {', '.join(r.categoriesHurt) or '-'}"
            )
        for note in analysis.strategyNotes:
            report.info(f"note: {note}")
    except Exception as exc:  # noqa: BLE001
        report.error("analyze_matchup", exc)
        traceback.print_exc()

    report.summary()
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

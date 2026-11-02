# How This MCP Server Works: A Tutorial

This tutorial explains the ESPN Fantasy Basketball MCP server from the inside: what happens
between you asking Claude "who should I start tonight?" and the answer coming back, how the code
is organised, how it talks to ESPN, and how to extend and test it. The [README](README.md) is the
reference for installation and the tool list; this document is the explanation of the mechanism.

Everything below describes the code as it is in this repository as of version 1.3 (November
2026). Line references are approximate and may drift; function names are stable.

## Contents

1. [The 60-second mental model](#1-the-60-second-mental-model)
2. [What MCP is and what this server provides](#2-what-mcp-is-and-what-this-server-provides)
3. [The life of one request](#3-the-life-of-one-request)
4. [Layer by layer](#4-layer-by-layer)
   - 4.1 [The entry point: `espn_fantasy_basketball.py`](#41-the-entry-point-espn_fantasy_basketballpy)
   - 4.2 [Credentials and the season default](#42-credentials-and-the-season-default)
   - 4.3 [The client: talking to ESPN](#43-the-client-talking-to-espn)
   - 4.4 [The response cache](#44-the-response-cache)
   - 4.5 [Models: shaping what Claude sees](#45-models-shaping-what-claude-sees)
   - 4.6 [Constants: ESPN's three numbering schemes](#46-constants-espns-three-numbering-schemes)
   - 4.7 [Dates: scoring periods vs matchup periods](#47-dates-scoring-periods-vs-matchup-periods)
   - 4.8 [Search: finding a player ID from a name](#48-search-finding-a-player-id-from-a-name)
   - 4.9 [Analysis: how `analyze_matchup` projects a week](#49-analysis-how-analyze_matchup-projects-a-week)
5. [How ESPN's API is shaped](#5-how-espns-api-is-shaped)
6. [Worked example: a simple tool end to end](#6-worked-example-a-simple-tool-end-to-end)
7. [Worked example: a composite tool end to end](#7-worked-example-a-composite-tool-end-to-end)
8. [Using the server well from Claude](#8-using-the-server-well-from-claude)
9. [Adding a new tool](#9-adding-a-new-tool)
10. [Testing and verification](#10-testing-and-verification)
11. [Security model](#11-security-model)
12. [Known limits and where the data stops](#12-known-limits-and-where-the-data-stops)

---

## 1. The 60-second mental model

The server is a thin translation layer with one job: turn a question Claude can ask ("get my
roster") into one or more HTTPS requests to ESPN's undocumented fantasy API, and turn ESPN's
sprawling JSON into a compact, named, typed answer.

```
 Claude Desktop ──(JSON-RPC over stdio)──▶ FastMCP server ──▶ tool function
                                                                  │
                                                     resolve league/team/cookies
                                                                  │
                                                        ESPNFantasyBasketballClient
                                                                  │
                                                         response cache (in memory)
                                                                  │
                                                           httpx GET (HTTPS only)
                                                                  │
                                              lm-api-reads.fantasy.espn.com  /  site.api.espn.com
                                                                  │
                                                      raw JSON ──▶ Pydantic model ──▶ dict
                                                                  │
 Claude Desktop ◀──────────────────────────────────────── JSON result
```

Three ideas carry most of the weight:

- **One process, many tools.** The server exposes 22 tools. Each is an `async` Python function
  decorated with `@mcp.tool()`. Claude picks a tool, the function runs, the return value goes
  back as JSON.
- **The client does the real work.** Every tool creates an `ESPNFantasyBasketballClient` and
  calls one method on it. The client knows ESPN's URLs, query "views", the `x-fantasy-filter`
  header, cookies, and how to parse what comes back.
- **ESPN speaks in numeric IDs; the server speaks in names.** Stat `0` becomes `points`, slot
  `11` becomes `UTIL`, pro team `9` becomes `GSW`. The constants module holds those tables, and
  every response carries names next to the IDs.

## 2. What MCP is and what this server provides

The Model Context Protocol (MCP) is a standard way for an AI client such as Claude Desktop to
discover and call tools that live in a separate process. The client starts the server as a
subprocess, speaks JSON-RPC to it over the server's standard input and output, asks it to list
its tools, and later calls them with JSON arguments.

This server implements the **stdio** transport only. The last lines of
`espn_fantasy_basketball.py` are:

```python
if __name__ == "__main__":
    mcp.run(transport="stdio")
```

That has one practical consequence worth knowing: **stdout belongs to the protocol.** Anything
printed to stdout would corrupt the JSON-RPC stream. That is why logging is configured with
`logging.basicConfig(...)`, which writes to stderr by default, and why nothing in the codebase
uses `print()` outside of `scripts/verify_live.py`, which is not the server.

The server provides **tools only**. It does not expose MCP resources or prompts. All 22 tools
are read-only against ESPN: the server never changes a lineup, makes a trade, or places a bid.

## 3. The life of one request

Suppose you ask Claude: "How is my matchup going?" Here is what happens, step by step.

1. **Claude chooses a tool.** When Claude Desktop started the server, FastMCP sent back a list
   of tools with their names, descriptions, and JSON schemas for their parameters. FastMCP
   builds those from the Python function signature and docstring. Claude reads the description
   of `get_my_current_matchup` ("Get your current matchup with complete information in a single
   call") and decides it fits.

2. **Claude calls it with (probably) no arguments.** Every tool parameter is optional except
   where a value cannot be inferred (a `player_id`, a `query`). Claude usually sends `{}`.

3. **The tool resolves configuration.** `_get_espn_credentials()` fills in league ID, season,
   and the two cookies from environment variables. `_get_team_id()` fills in your team from
   `ESPN_TEAM_ID`. If the team is missing, the tool raises a `ValueError` with a message telling
   you how to fix it; FastMCP turns that into a tool error Claude can read and relay.

4. **A client is created.** `ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)` is
   constructed fresh for each tool call. It validates the league ID and year and stores the
   cookies. Creating a client is cheap because the cache is shared at the class level, not held
   per instance.

5. **The client makes requests.** For this tool it fetches league settings (to learn the current
   matchup period), the schedule view (to find your matchup), the team list (for names), today's
   NBA scoreboard (to annotate each player with their game tonight), ESPN's public NBA injury
   report (for the reason behind each injury status), and both rosters. Many of these are
   served from cache if another tool asked recently.

6. **Raw JSON becomes a model.** The client assembles a `CurrentMatchup` Pydantic model. The
   model declares which fields exist, and the client fills them with named categories, slot
   names, timezone-converted times, and so on.

7. **The model becomes a dict.** The tool returns `matchup.model_dump()`. FastMCP serialises it
   to JSON and sends it back over stdout.

8. **Claude reads the JSON** and writes you a sentence about it.

## 4. Layer by layer

### 4.1 The entry point: `espn_fantasy_basketball.py`

This file is the whole MCP surface. It is deliberately boring: about 800 lines, almost all of it
docstrings. Each tool follows the same five-line shape:

```python
@mcp.tool()
async def get_league_teams(
    league_id: int | None = None,
    year: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> list[dict]:
    """Get all teams in an ESPN Fantasy Basketball league.
    ... (docstring describing each arg and the return shape) ...
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    teams = await client.get_league_teams()
    return [team.model_dump() for team in teams]
```

Why the docstrings are so long: **they are the user interface.** FastMCP sends the docstring to
Claude as the tool description, and the type hints become the parameter schema. A good docstring
is what lets Claude pick the right tool and pass the right arguments without being told. If you
change what a tool does, change its docstring; that is the part Claude sees.

A few tools do slightly more than the five-line shape:

- `get_matchups` and `analyze_matchup` coerce `matchup_period` from a string to an int, because
  some MCP clients send numbers as strings; `get_player_schedule` and `get_roster_schedule` do
  the same for `player_ids`.
- `get_nba_schedule` needs no league at all, so it builds a client with a dummy league ID of `1`.
- `get_player_stats` accepts either one ID or a list and returns a dict or a list accordingly.
- `analyze_my_draft_strategy` combines two client calls and computes `budget_per_remaining_player`
  itself.

Everything else is delegation.

### 4.2 Credentials and the season default

`_get_espn_credentials()` applies a simple rule: **an explicit argument wins; otherwise read the
environment.** The environment variables are `ESPN_LEAGUE_ID`, `ESPN_YEAR`, `ESPN_S2`, and
`ESPN_SWID`. `_get_team_id()` does the same for `ESPN_TEAM_ID`.

The season default deserves a note because it trips people up. ESPN labels a season by the
calendar year it **ends** in: the 2026-27 season is `2027`. `_default_season()` encodes that:

```python
def _default_season(today: date | None = None) -> int:
    today = today or date.today()
    return today.year + 1 if today.month >= 10 else today.year
```

October through December map to next year; January through September map to this year. The one
awkward window is September draft prep, when you want next season but the function still returns
this one. Set `ESPN_YEAR` explicitly then. The function takes an injectable `today` so the tests
in `tests/test_server.py` can pin the date.

### 4.3 The client: talking to ESPN

`espn_fantasy_basketball_mcp/client.py` is the largest file. It is a single class,
`ESPNFantasyBasketballClient`, organised in sections: construction and validation, timezone
helpers, the cache, the request layer, and then one or more methods per tool.

**Two base URLs.** The fantasy API lives at
`https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba` and is where league, roster, matchup,
player, transaction, and draft data come from. The public NBA site API at
`https://site.api.espn.com/apis/site/v2/sports/basketball/nba` supplies today's scoreboard
(`/scoreboard?dates=YYYYMMDD`; the singular `date` is silently ignored), each NBA team's season
schedule, and the league-wide injury report (`/injuries`). The second one needs no cookies and
no league.

**One league URL, many views.** Almost every fantasy request hits the same URL,
`/seasons/{year}/segments/0/leagues/{league_id}`, and selects what to get back with a `view`
query parameter: `mTeam`, `mSettings`, `mRoster`, `mMatchup`, `mTransactions2`, `mDraftDetail`,
or `kona_player_info`. The section below on ESPN's API has the full table.

**Player queries use a header, not a query string.** When you ask for players (free agents, stats
for specific IDs, draft rankings), ESPN expects a JSON filter in an `x-fantasy-filter` request
header. For example `get_free_agents` builds:

```python
filter_dict = {
    "players": {
        "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
        "limit": size,
        "sortPercOwned": {"sortAsc": False, "sortPriority": 1},
        "filterStatsForTopScoringPeriodIds": {
            "value": 5,
            "additionalValue": [f"00{self.year}", f"10{self.year}"],
        },
    }
}
headers = {"x-fantasy-filter": json.dumps(filter_dict)}
```

The `additionalValue` strings name which stat "splits" to include; `00YYYY` is season actuals and
`10YYYY` is projections. The last-7/15/30-day splits are `01`, `02`, and `03`. If a tool
returns a player with empty stats, the first thing to check is whether the right split was
requested in the filter.

**Cookies.** For private leagues, `espn_s2` and `SWID` are sent as cookies on every fantasy
request. The client stores them in `self.cookies` and passes them to `httpx`. They are never
logged.

**The request layer.** `_make_request()` enforces HTTPS, consults the cache, and otherwise calls
`_fetch()`, which does a 30-second-timeout GET with `httpx.AsyncClient` and raises on any
non-2xx status. Errors are logged at error level (URL and status only) and re-raised; the tool
call fails loudly rather than returning partial data.

**Parsing is defensive.** ESPN sends explicit `null`s where you would expect omitted keys
(`"cumulativeScore": null`, a `null` away side for a bye). The parsing code is full of
`(x.get("foo") or {})` for that reason. When you add parsing, follow that pattern.

**Thin aliases.** Partway through the file you will find small static methods such as
`_availability` and `_matchup_period_window` that do nothing but call a function in another
module. During a refactor the matchup analysis,
calendar math, name matching, and constants were moved into their own modules. These aliases
keep the old class attribute names working so the tests and any external callers did not break.
New code should import from the modules directly.

### 4.4 The response cache

A single `analyze_matchup` call can trigger dozens of ESPN requests: league settings are needed
in several places, each of 26 players needs their NBA team's schedule, and so on. Without a
cache, the same bytes would be fetched over and over inside one tool call.

The cache is a **class-level dictionary** on the client, shared by every client instance in the
process. That matters because the server creates a new client per tool call; a per-instance cache
would never be reused.

Each entry is keyed by the URL, the query parameters, the `x-fantasy-filter` header, and your
`SWID` cookie. Including `SWID` means two different accounts in one process could never see each
other's data. Entries expire per endpoint:

| Request | Lifetime | Reason |
|---|---|---|
| NBA team season schedule | 6 hours | Almost never changes |
| All active players list (`players_wl`) | 6 hours | Changes a few times a week |
| League settings (`mSettings`) | 10 minutes | Commissioner edits are rare |
| League team list (`mTeam`) | 5 minutes | Names and records move slowly |
| Today's scoreboard | 60 seconds | Games tip off and finish |
| NBA injury report | 10 minutes | Updated a few times a day |
| Everything else (rosters, matchups, players, transactions, draft) | 15 seconds | Live data |

The 15-second lifetime is the key design choice. It is long enough to collapse the burst of
identical requests inside one tool call, and short enough that a roster move you just made shows
up on your next question.

Two more properties: **concurrent identical requests share one in-flight fetch** (a second caller
awaits the first caller's task rather than starting its own), and **failures are never cached**
(only a successful `_fetch` reaches `_store`). The cache is capped at 512 entries and evicts
expired entries first, then the oldest. Set `ESPN_MCP_DISABLE_CACHE=1` to bypass it entirely,
which is useful when debugging a parsing problem and you want to be sure you are seeing fresh
data. `tests/test_cache.py` covers all of this.

### 4.5 Models: shaping what Claude sees

`espn_fantasy_basketball_mcp/models.py` holds about 50 Pydantic models. They serve two purposes.

First, **they are the contract.** `Roster`, `CurrentMatchup`, `MatchupAnalysis`,
`LeagueSettings`, and the rest define exactly which fields a tool returns. When a client method
builds one, Pydantic validates the types. When a tool calls `.model_dump()`, the field names
become the JSON keys Claude reads.

Second, **they document ESPN.** Many fields carry comments explaining what ESPN actually sends.
For example in `MatchupTeam`:

```python
cumulativeScore: dict[str, Any] | None = None   # Original stat IDs (deprecated, use categoryScores)
categoryScores: dict[str, float] | None = None  # Scoring categories only (human-readable names)
componentStats: dict[str, float] | None = None  # FGM, FGA, FTM, FTA that aren't scoring categories
```

That trio shows the server's general approach: keep the raw thing (`cumulativeScore`), add the
readable thing (`categoryScores`), and separate out the supporting numbers (`componentStats`)
that the analysis needs to compute percentages correctly.

A detail worth knowing: several tools have a `verbose` flag that defaults to `False`. For
rosters, `_make_roster_slim()` keeps every player's per-game averages, injury detail, lock state
and today's game, and drops only the season `totals` block; for free agents, `verbose=false`
omits stats entirely. Ask for `verbose=true` when you want season totals or free-agent stats.

Several models also carry fields that exist only to prevent misreading: a team's `recordType`
says whether its record counts categories or matchups; a roster's `scoringPeriodId`,
`scoringPeriodDate` and `lockedSlots` say which day it is for and what can still be changed;
`staleEntriesRemoved` names players ESPN still listed under a team after they were dropped; and
settings carry `acquisitionLimitDescription` and `matchupPeriodsNote` in plain English.

### 4.6 Constants: ESPN's three numbering schemes

`espn_fantasy_basketball_mcp/constants.py` is small but important. ESPN uses **three different
numberings** for what sound like the same thing, and getting them confused produces answers that
are confidently wrong.

- **Stat IDs** (`STAT_ID_TO_CATEGORY`): `0` points, `1` blocks, `2` steals, `3` assists, `6`
  rebounds, `11` turnovers, `13`–`16` FGM/FGA/FTM/FTA, `17` threes, `19` FG%, `20` FT%, `40`
  minutes. Used in scoring settings, matchup scores, and player stats.
- **Lineup slot IDs** (`LINEUP_SLOT_NAMES`): `0` PG through `4` C, `5` G, `6` F, `11` UTIL, `12`
  Bench, `13` IR. Slots 7 through 10 (SG/SF, G/F, PF/C, F/C) are inferred from ESPN's settings
  page order and have not been seen in live data. Used in `lineupSlotId` and `eligibleSlots`.
- **Player position IDs** (`POSITION_NAMES`): `1` PG through `5` C. One-based, unlike slots. Used
  in `defaultPositionId`.
- **Position-limit keys** (`POSITION_LIMIT_NAMES`): `1` PG through `5` C, the same as position
  IDs, plus an unexplained key `0`. Used only in `rosterSettings.positionLimits`. (An earlier
  version assumed keys 2 through 6; a recorded league with a four-center limit showed `{"5": 4}`.)

The file also holds `PRO_TEAM_ABBREVS` (fantasy `proTeamId` 1–30 to a canonical three-letter
code, with `0` meaning unsigned) and `ABBREV_ALIASES`, which reconciles the codes ESPN's two APIs
disagree on. The site API says `GS`, `NO`, `NY`, `SA`, `UTAH`, and `WSH`; the fantasy API says
`GSW`, `NOP`, `NYK`, `SAS`, `UTA`, and `WAS`. `normalize_nba_abbrev()` maps everything to the
long form so that "does this player have a game today?" lookups do not miss six teams.

Two tuning tables live here as well: `AVAILABILITY_FACTORS` (how much of their remaining games a
player with a given injury status is expected to play) and `SHOOTING_THRESHOLDS` (what counts as
a good or poor FG% and FT%).

### 4.7 Dates: scoring periods vs matchup periods

ESPN counts time two ways, and `espn_fantasy_basketball_mcp/dates.py` exists to convert between
them and the calendar.

- A **scoring period** is one calendar day. Period 1 is opening night. ESPN's
  `status.latestScoringPeriod` is today's period number during the season.
- A **matchup period** is one head-to-head week. Period 1 is usually short (opening night through
  the following Sunday), and the All-Star week is often two weeks long.

`scheduleSettings.matchupPeriods` in the league settings maps each matchup period to the week
number(s) it covers. It is **week-indexed**, not day-indexed; a normal period has one entry and a
two-week period has two. That was once misread as daily and produced wrong "games remaining"
counts, which is why the README's changelog mentions it.

The conversion works like this:

1. `_scoring_period_anchor()` finds a known (period, date) pair. In season, that is
   (`latestScoringPeriod`, today in Eastern time). Out of season, it falls back to (first period,
   opening night from the NBA schedule).
2. `date_for_scoring_period()` places any other period by adding days.
3. `matchup_period_window()` walks the week map from opening night to produce the first and last
   calendar day of a matchup period.
4. `games_remaining_by_player()` counts a player's games inside that window that have not tipped
   off yet, using the game's tip-off time when known and its date otherwise.

`get_matchup_period_dates()` on the client ties these together, and
`get_league_settings` exposes the result as `scheduleSettings.matchupPeriodDates` so you can see
each week's boundaries directly. That mapping is the authoritative one; the raw `matchupPeriods`
is easy to misread as days, which is why the settings also carry a `matchupPeriodsNote`,
`status.currentMatchupPeriodDates` and `status.latestScoringPeriodDate`.

Which day's roster a tool fetches follows from the same arithmetic. `get_matchup_for_period`
asks ESPN for today's roster for the current week (its default), the first day's for a future
week (ESPN returns the lineup as set for that day) and the last day's for a past week. Per-day
acquisition limits use the window length too: a limit of one per day allows six adds in a
six-day opening week and seven in a normal one (`effectiveLimitByMatchupPeriod`).

### 4.8 Search: finding a player ID from a name

Every stats tool takes an ESPN numeric player ID, which nobody knows by heart.
`search_players` solves that. The client fetches the league-independent list of all active NBA
players (`/seasons/{year}/players?view=players_wl`, about 500 entries, cached six hours) and
scores each name against your query with `name_match_score()` in
`espn_fantasy_basketball_mcp/search.py`.

The scoring is tiered so that structural matches always beat fuzzy ones:

| Match | Score | Example |
|---|---|---|
| Exact normalized name | 1.0 | "Nikola Jokic" |
| Query equals one name token | 0.95 | "Jokic" |
| Each query token is a prefix of a name token, in order | 0.9 | "steph curry" |
| Query is a substring | 0.85 | "okic" |
| Otherwise, difflib similarity | up to 0.8 | "Jokich" |

Normalization strips accents and punctuation and case-folds, so "Dončić" and "doncic" match.
Anything below 0.6 is discarded; live testing showed "Jokic" scoring 0.5 against unrelated names
like "Josh Okogie", which is where that floor comes from.

With `include_league_status=true` (the default), one extra request against your league fills in
whether each match is a free agent, which fantasy team owns them, their ownership percentage,
whether they are on waivers (and until when), and the injury detail from ESPN's injury report.

### 4.9 Analysis: how `analyze_matchup` projects a week

`espn_fantasy_basketball_mcp/analysis.py` holds the one piece of real logic in the project. It
is worth understanding because its output drives the start/sit advice Claude gives.

The inputs are: the matchup (both rosters and current category scores), both teams' roster
schedules for the matchup window, every player's ESPN **projections** and **last-7-day** stats,
and the league's scoring categories.

**Step 1: how many games does each player have left?** `games_remaining_by_player()` counts games
in the window that have not tipped off. Games already played are already in the current scores,
so counting them again would double count.

**Step 2: discount by availability.** `player_availability()` returns a label and a factor for
each roster entry. OUT, suspended, in the IR slot, or not on an NBA roster gives 0.0; DOUBTFUL
gives 0.5; everything else gives 1.0. Expected games = remaining games × factor. This is why a
player on the bench with an injury does not inflate your projected totals.

**Step 3: project each category.** For counting categories (points, rebounds, and so on),
projected = current + Σ(player's projected per-game × expected games). For FG% and FT%, the code
instead projects made and attempted separately and divides at the end, because averaging
percentages is wrong. It reads current FGM/FGA from `componentStats`, falling back to the raw
`scoreByStat` entries for stat IDs 13–16, and it validates that the numbers look like counts (≥ 1)
rather than fractions before trusting them. If ESPN has no per-game made/attempted for a player,
there is a rough fallback from points and FG%.

**Step 4: classify.** A category is "winning", "losing", or "tied" by projected lead, with a
small tolerance (0.1 for counts, 0.002 for percentages). It is "close" if the current margin is
within 5% or 2.0, whichever is larger (a tighter band for percentages).

**Step 5: rank your players.** For each player who can play and has games left, start from a
priority of 5 and adjust: +2 per close or losing category they are strong in (using per-category
thresholds such as 15 points or 6 rebounds), −1 per category they hurt, +1 or +2 for two or three
games remaining, −1 or −2 for questionable or doubtful status, and a bonus for helping in several
categories. Cap at 1–10 and sort.

**Step 6: warn about dead slots.** Any starter (not bench, not IR) with a factor of 0.0 and games
left produces a `lineupWarnings` entry naming them, the slot, and ESPN's injury note when there
is one ("is OUT (Knee - Sprain (left); expected return 2026-11-10 ...)"). Starters who are
questionable get a softer "check status before tip-off" warning.

**Step 7: write strategy notes.** Projected record, which categories to focus on, the expected
games edge between the two teams, and which losing categories to prioritise.

The thresholds are heuristics, not learned values. They live in the code and in
`constants.py` and are easy to tune. `tests/test_matchup_analysis.py` exercises each step with
mocked data.

## 5. How ESPN's API is shaped

ESPN does not document this API. What the server knows was learned by observation, and this
section collects it so you do not have to rediscover it.

**League endpoint views.** All against `/seasons/{year}/segments/0/leagues/{league_id}`:

| `view` | Returns | Used by |
|---|---|---|
| `mTeam` | Teams, owners, records | `get_league_teams`, everything that needs names |
| `mSettings` | Scoring, roster, schedule, acquisition, trade, draft settings and `status` | `get_league_settings`, and internally almost everywhere |
| `mRoster` (with `mTeam`) | Each team's roster entries with nested player objects | `get_team_roster` and everything built on it |
| `mMatchup` | The `schedule` array: every matchup of every period with cumulative scores | `get_matchups`, `get_team_season_stats`, matchup tools |
| `mTransactions2` | The `transactions` array: adds, drops, waiver claims, trades, and every lineup save | `get_transactions` |
| `mDraftDetail` | `draftDetail.picks`, draft state | draft tools |
| `kona_player_info` | Players matching the `x-fantasy-filter` header | free agents, stats, trending, draft rankings, search status |

**The `status` block** (from `mSettings`) carries `currentMatchupPeriod`,
`latestScoringPeriod`, `firstScoringPeriod`, `finalScoringPeriod`, and `isActive`. The server
leans on these for "what week is it" and for the date anchoring described in section 4.7.

**Stat splits.** A player's `stats` array holds several entries distinguished by `id`:
`00YYYY` season actuals, `10YYYY` projections, `01YYYY` last 7 days, `02YYYY` last 15,
`03YYYY` last 30. Each has `stats` (totals) and `averageStats` (per game), keyed by stat ID.
Stat 42 (games played) is sometimes missing, so the client can derive it from a total divided
by its average. The FT% key is absent from the per-game block but present in totals; FG% and
FT% are null exactly when a player has no attempts, with the attempt counts alongside.

**Where injury status hides.** It can be on the player object, on the roster entry, or inside an
`injury` sub-object. The client checks all three, player-level first, because entry-level often
says `NORMAL` when the player-level says `DAY_TO_DAY`. The fantasy player object carries no
reason or timeline, only `injuryStatus`, `injured` and `lastNewsDate`; those come from the site
API's injury report, matched by athlete ID, by the ID inside the athlete's player-card link, or
by name (a live payload had no athlete ID at all).

**Other fields the tools lean on.** `players[].player.ownership` (not the entry level) holds
ownership percentages; `players[].status` is `FREEAGENT`, `WAIVERS` or `ONTEAM`, with
`waiverProcessDate` while on waivers; `teams[].waiverRank` and `teams[].transactionCounter`
give the waiver order and adds used; `playerPoolEntry.lineupLocked` is the per-slot lock;
`playerPoolEntry.onTeamId` is the player's *current* team even in a roster list, which is how a
dropped player can still appear under his old team for a locked day. ESPN's
`waiverProcessHour` is UTC (a league reporting 8 had every process date at 08:00Z).

**Quirks the server works around.**

- Explicit `null` values instead of missing keys, especially for a week that has not started.
- `scoringPeriodId` as a query parameter is a **day** index. Sending a week number there returns
  nonsense, which an earlier version of `get_matchups` did.
- A matchup that has not started has `cumulativeScore: {wins: 0, losses: 0, ties: 0,
  scoreByStat: null}`, a non-null object with a null inside, not a null `cumulativeScore`.
- Every lineup save is logged as a `ROSTER` or `FUTURE_ROSTER` transaction, and a drop made
  from the roster page arrives as `ROSTER` with a `DROP` item. `get_transactions` hides pure
  lineup saves unless asked.
- The free-agent query returns at most 50 players per request.
- Team `location` is not provided.
- The two APIs disagree on six team abbreviations (section 4.6).

## 6. Worked example: a simple tool end to end

Let us trace `search_players(query="jokic")`, which is simple but touches most layers.

1. **Tool.** `search_players` in `espn_fantasy_basketball.py` resolves credentials, builds a
   client, and calls `client.search_players("jokic", 5, True)`.
2. **Client, request one.** `get_pro_players()` requests
   `/seasons/2027/players?view=players_wl` with a filter header of `{"filterActive": {"value":
   true}}`. The cache key for this request has a six-hour lifetime, so after the first search of
   the day this step costs nothing.
3. **Search.** Each of roughly 500 names is scored. "jokic" equals the surname token of
   "Nikola Jokic", so that scores 0.95. Everything below 0.6 is dropped. The top five survive.
4. **Client, request two and three.** Because `include_league_status` is true, the client
   concurrently fetches `kona_player_info` filtered to those five IDs (for `onTeamId` and
   ownership) and `mTeam` (for team names). `asyncio.gather` runs them together.
5. **Model.** Five `PlayerSearchResult` objects are built with `playerId`, `fullName`,
   `matchScore`, position, NBA team, injury status and detail, waiver state, and the league
   fields.
6. **Return.** The tool returns `[r.model_dump() for r in results]`. Claude sees a list and can
   now call `get_player_stats` with the right ID.

Four ESPN requests at most (the injury report is the fourth), two of which are almost always
cached.

## 7. Worked example: a composite tool end to end

Now `analyze_matchup()` with no arguments, for a 13-player roster on each side.

1. **Settings.** `get_league_settings()` → `mSettings`. Learns the current matchup period, the
   scoring stat IDs, the week map, and `latestScoringPeriod`. Target period defaults to current
   + 1 (next week), because the tool is designed for planning.
2. **Matchup.** `get_matchup_for_period()` → `get_matchups()` → `mMatchup`, plus `mTeam` for
   names. Finds the one schedule item for your team in that period, decides which side is you,
   and extracts named category scores. Then both rosters are fetched concurrently with
   `mRoster` for the first day of the target week, each of which also hits the NBA scoreboard
   (cached 60 seconds) to annotate `todaysGame` and the injury report (cached 10 minutes) for
   `injuryDetails`.
3. **Window.** `get_matchup_period_dates()` turns the target period into first and last calendar
   days using the anchoring in section 4.7. If that fails for any reason, it falls back to seven
   days from today and logs a warning.
4. **Schedules.** `get_roster_schedule_summary()` for both teams, concurrently. For each
   rostered player with an NBA team, it fetches that team's season schedule
   (`/teams/{proTeamId}/schedule`, cached six hours) and filters to the window. Players on the
   same NBA team share one request through the in-flight de-duplication.
5. **Stats.** Two batched `kona_player_info` requests for all 26 players: one for projections
   (`10YYYY`), one for last 7 days (`01YYYY`).
6. **Analysis.** The seven steps in section 4.9 run on this data and build a `MatchupAnalysis`.
7. **Return.** `analysis.model_dump()`.

Roughly 35 ESPN requests the first time, most of which are served from cache on any follow-up
question within the same minute. That is the burst the 15-second live lifetime exists to
collapse.

## 8. Using the server well from Claude

Some patterns make the tools work better.

- **Set `ESPN_TEAM_ID` once.** Every tool about *your* team needs it. With it set, Claude can
  call most tools with no arguments at all.
- **Names before IDs.** Ask about players by name; Claude should call `search_players` first and
  pass the resulting ID to `get_player_stats`, `compare_players`, or `analyze_trade_proposal`.
- **Reach for the composite tools.** `get_my_current_matchup` replaces three calls;
  `analyze_matchup` replaces about a dozen and adds the reasoning. `get_roster_schedule` is the
  right tool for "who has four games this week?", and `get_player_schedule` answers the same
  question for a free agent you are thinking of streaming.
- **Use `verbose=true` only when you want season totals or free-agent stats.** Rosters keep
  per-game averages either way.
- **Waivers and adds have their own tools.** `get_free_agents` says whether a player is addable
  now or on waivers until a given time; `get_league_teams` shows the waiver order and adds used
  this matchup; `get_transactions` shows who dropped whom and when.
- **Specify the week when it matters.** `analyze_matchup` defaults to **next** week.
  `get_matchups` and `get_roster_schedule` default to the **current** week. Pass
  `matchup_period` to pin either.
- **Know what is ESPN and what is Claude.** Everything in a tool response comes from ESPN's
  data: stats, projections, injury status codes and ESPN's injury notes, ownership, schedules,
  transactions. Trade rumours, advanced metrics and anything beyond ESPN's injury blurb are not
  in these APIs, so Claude is supplying them from general knowledge. The projections in
  `analyze_matchup` are ESPN's per-game projections multiplied out by this server; the
  thresholds and priorities are this server's heuristics.
- **If a tool errors,** the message is usually precise: a missing team ID, an invalid timeframe
  string, a player not found. An HTTP 401 or 403 almost always means the cookies have expired;
  refresh them from your browser.

## 9. Adding a new tool

Suppose you want a tool that returns a team's transaction count this season. (The real server
now exposes these counters on `get_league_teams`; the example stays because it is small.) The
pattern has four parts.

**1. Add a model** in `models.py` for the return shape:

```python
class TeamActivity(BaseModel):
    teamId: int
    teamName: str | None = None
    acquisitions: int
    drops: int
    trades: int
```

**2. Add a client method** in `client.py`. Use `_make_request`, parse defensively, return the
model. ESPN's `mTeam` view carries a `transactionCounter` object per team (confirmed in a
recorded response; for a new field, record one with `scripts/record_fixtures.py` first):

```python
async def get_team_activity(self, team_id: int) -> TeamActivity:
    self._validate_positive_int(team_id, "team_id")
    url = f"{self.BASE_URL}/seasons/{self.year}/segments/0/leagues/{self.league_id}"
    data = await self._make_request(url, {"view": "mTeam"})
    for team in data.get("teams") or []:
        if team.get("id") == team_id:
            counters = team.get("transactionCounter") or {}
            return TeamActivity(
                teamId=team_id,
                teamName=team.get("name"),
                acquisitions=counters.get("acquisitions", 0),
                drops=counters.get("drops", 0),
                trades=counters.get("trades", 0),
            )
    raise ValueError(f"Team {team_id} not found in league {self.league_id}")
```

**3. Add the tool** in `espn_fantasy_basketball.py`, following the standard shape. Write the
docstring for Claude, not for yourself:

```python
@mcp.tool()
async def get_team_activity(
    team_id: int | None = None,
    league_id: int | None = None,
    year: int | None = None,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> dict:
    """Count a team's adds, drops, and trades so far this season.

    Args:
        team_id: Team ID (optional, uses ESPN_TEAM_ID env var)
        league_id: ESPN Fantasy Basketball league ID (optional, uses ESPN_LEAGUE_ID env var)
        year: ESPN season ID, the year the season ends in (optional, defaults to current season)
        espn_s2: ESPN authentication cookie for private leagues (optional, uses ESPN_S2 env var)
        swid: ESPN SWID cookie for private leagues (optional, uses ESPN_SWID env var)

    Returns:
        Dictionary with teamId, teamName, acquisitions, drops, trades
    """
    league_id, year, espn_s2, swid = _get_espn_credentials(league_id, year, espn_s2, swid)
    team_id = _get_team_id(team_id)
    if team_id is None:
        raise ValueError(
            "team_id is required. Provide it as a parameter or set ESPN_TEAM_ID environment variable."
        )
    client = ESPNFantasyBasketballClient(league_id, year, espn_s2, swid)
    return (await client.get_team_activity(team_id)).model_dump()
```

**4. Add tests.** Three kinds, mirroring the existing suite:

- A fixture-backed end-to-end test in `tests/test_fixtures_e2e.py`: add the field to the
  synthetic payload in `tests/fixtures/build_synthetic.py`, regenerate, and assert on the tool's
  output. This is the preferred style because it runs the real request path.
- A client test that patches `_make_request` to return a small fake payload and asserts the
  model is built correctly (see `tests/test_client.py` for the style).
- A server test that patches `ESPNFantasyBasketballClient` in the `espn_fantasy_basketball`
  module and asserts the tool resolves credentials and raises on a missing team ID (see
  `tests/test_server.py`).

Then update the tool list in the README, run `./scripts/check.sh`, and restart Claude Desktop so
it re-reads the tool list.

Things to keep in mind: pick a sensible cache lifetime (the default 15 seconds is right for live
data; add a branch in `_cache_ttl` if your endpoint is slow-changing); never log cookies; keep
stdout clean; and coerce string arguments to int where an MCP client might send them as strings.

## 10. Testing and verification

The project has four distinct testing layers, and it helps to know which one answers which
question.

**Unit tests (`tests/`, about 260 of them, run in about three seconds).** Every ESPN call is
mocked or served from a fixture. Nothing touches the network. They answer: *does the code do
what it says with the data shapes we have seen?* Run them with:

```bash
uv run pytest
```

Notable files: `test_cache.py` proves the lifetimes, de-duplication, and never-cache-failures
behaviour; `test_matchup_analysis.py` proves the projection and availability rules;
`test_matchup_periods.py` proves the calendar math against ESPN's week map;
`test_pro_teams.py` proves the abbreviation reconciliation; `test_server.py` proves credential
resolution and the season default. Coverage is enforced at 78% by `fail_under` in
`pyproject.toml`, and the comment there asks that it only ever be raised.

**Fixture-backed end-to-end tests (`tests/test_fixtures_e2e.py`).** `tests/fixture_espn.py`
maps each ESPN request (URL, view, filter header) to a JSON file in `tests/fixtures/` and
installs itself in place of `_make_request`, with the clock frozen on the last day of a matchup
period. The committed fixtures are synthetic but ESPN-shaped (regenerate them with
`tests/fixtures/build_synthetic.py`), and each file corresponds to one request. These tests run
the real request path, so a parser reading the wrong key fails here rather than against ESPN.
`scripts/record_fixtures.py` records your own league into the gitignored
`tests/fixtures/recorded/` under the same file names, after stripping `members`, owner IDs,
every GUID (SWIDs) and cookie-shaped tokens; `tests/test_fixture_hygiene.py` scans every fixture
for credentials on each run. Several bugs in this project were found by comparing a recording
with the synthetic fixture.

**The full local check (`./scripts/check.sh`).** Runs the same four steps as CI: `ruff check`,
`ruff format --check`, `mypy` on the package and entry point, and `pytest` with coverage. mypy
runs in a strict configuration (`disallow_untyped_defs`, `warn_return_any`, and more), which is
why every function in the package has full type annotations.

**Live verification (`scripts/verify_live.py`).** Read-only, against your real league. It answers
the question unit tests cannot: *does ESPN still send what we think it sends?* It checks the
season your settings resolve to, today's scoreboard against the team codes on your roster, a
current-week `analyze_matchup` for sane games-remaining and projection numbers, and player
search. It reads
credentials from the environment or from the `env` block of your Claude Desktop config, never
prints cookie values, and exits non-zero on failure. Run it when ESPN changes something, when a
tool starts returning odd numbers, or after a season rollover:

```bash
uv run python scripts/verify_live.py
```

**CI (`.github/workflows/test.yml`).** Runs the full check on every push and on pull requests to
`main`, across Python 3.10, 3.11, and 3.12, installing from `uv.lock` so versions match exactly.
The workflow has read-only repository permissions and uses no secrets. Dependabot keeps the
actions themselves current.

## 11. Security model

The server handles one secret: your ESPN session cookies. Here is how it treats them and what
remains your responsibility.

**What the code does.**

- Only HTTPS URLs are accepted; `_make_request` raises on anything else.
- Cookies are sent only to the two ESPN hosts the client knows about, as request cookies, never
  in URLs or logs. Error logs include the URL and status code only.
- The cache key includes your `SWID`, so cached responses are scoped to your account.
- All tools are read-only. There is no code path that writes to ESPN.
- Inputs are validated: league ID and year ranges, positive integers for IDs, size limits,
  date formats, and allowed timeframe strings.
- CI runs with read-only permissions and no secrets; `.env` and `tests/fixtures/recorded/` are
  gitignored, and a test scans every committed fixture for `espn_s2`, `SWID`, GUIDs and
  cookie-shaped tokens.

**What you need to do.**

- The `espn_s2` and `SWID` cookies grant full access to your ESPN account, not just read access
  to fantasy data. Treat them like a password.
- Store them in the Claude Desktop config `env` block and restrict that file's permissions
  (`chmod 600`). Never commit them.
- They expire. When tools start failing with 401 or 403, refresh them from your browser.
- Passing cookies as tool arguments works, but it puts them into the conversation transcript.
  Prefer the environment variables.

**A note on trust.** Everything the server returns is data from ESPN relayed to Claude. Player
names, team names, and injury notes are text controlled by ESPN and, in the case of fantasy team
names, by your league mates. None of it is executed, but it is shown to a language model. The
server does not sanitise it beyond type validation.

## 12. Known limits and where the data stops

Knowing what the server cannot tell you is as useful as knowing what it can, especially so you
can tell when Claude has switched from ESPN data to its own knowledge.

**Not available from ESPN's APIs, so not available here:**

- Player news beyond ESPN's injury blurb (body part, severity, side, expected return date, and
  a one-line note come from the public injury report; anything more is not available).
- Advanced or per-possession metrics, play-by-play, or shot charts.
- Daily fantasy or betting data.
- Team `location` (ESPN simply does not send it).
- More than 50 free agents per request.

**Approximations the server makes:**

- `analyze_matchup` uses ESPN's own projections and a set of fixed heuristic thresholds.
- Lineup slots 7–10 have names inferred from ESPN's settings page, not confirmed by data.
- Position-limit key `0` is reported as `POS_0` because nothing in the UI matches it.
- Week start day is inferred from waiver processing days and defaults to Monday.
- The meaning of `waiverOrderReset` (true = order resets, false = claimant moves to last) is
  from ESPN's settings page wording, not observed behaviour.
- Season start, out of season, is inferred from the Lakers' schedule as a stand-in for any team.

**Operational limits:**

- ESPN rate limiting is undocumented. The cache is the main defence.
- The API is undocumented and can change without notice. `scripts/verify_live.py` is the early
  warning system.
- The server runs over stdio only; there is no HTTP or SSE transport.

If you hit a question the tools cannot answer, that is the signal to add a tool. Section 9 shows
how.

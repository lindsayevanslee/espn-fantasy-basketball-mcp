# Changelog

## [Unreleased]

### Added
- Fixture-backed end-to-end tests (`tests/fixtures/`, `tests/test_fixtures_e2e.py`): every
  ESPN request is answered from an ESPN-shaped JSON file and the clock is frozen on the last
  day of a matchup period, so `analyze_matchup`, `get_matchups`, rosters, free agents,
  schedules and settings are exercised through the real request path without the network.
  `scripts/record_fixtures.py` records your own league into `tests/fixtures/recorded/` with
  `members`, owner IDs, every GUID (SWIDs) and every cookie-shaped token stripped, and
  `tests/test_fixture_hygiene.py` scans all fixtures for `espn_s2`, `SWID`, GUIDs and cookie
  tokens on every run.
- `get_player_schedule` tool: games this matchup period and next for arbitrary ESPN player IDs
  (streaming candidates, trade targets), and a `player_ids` parameter on `get_roster_schedule`
  that lists extras next to your roster (`includedInTotals: false`). Both report the
  `thisWeek` / `nextWeek` date windows they counted.
- Injury detail. ESPN's public NBA injury report is fetched once (cached 10 minutes); its
  athlete blocks carry an ID, a player-card link with the ID, or only names, and all three are
  matched (the fantasy player object itself has no injury fields, confirmed live). Each
  player's `injuryDetails` ("Knee - Sprain (left); expected return 2026-11-10. <ESPN note>")
  and `injuryReturnDate` appear on rosters, free agents, search results and in
  `analyze_matchup` lineup warnings. Any `injuryDetails` / `injuries` fields ESPN puts on the
  fantasy player object itself are used first.
- `get_league_settings`: `acquisitionSettings.acquisitionLimitDescription` ("1 acquisition per
  matchup period; no season-long limit."), `scheduleSettings.matchupPeriodsNote` explaining
  that `matchupPeriods` is week-indexed and `matchupPeriodDates` is authoritative, and
  `status.currentMatchupPeriodDates` / `status.latestScoringPeriodDate`.
- `get_league_teams`: `recordType` ("categories" or "matchups") and `recordDescription`, so a
  record in an H2H Each Category league is not misread as matchup wins; `record.overall.ties`.
- `get_team_roster`: `scoringPeriodId` and `scoringPeriodDate` say which day the roster is
  for, `lineupLocked` whether that day's lineup can still be changed, and a `note` points at
  `scoring_period + 1` for the next day's lineup when it cannot.

### Fixed
- `analyze_matchup` still crashed for a matchup that has not started. Live data shows ESPN
  sends `cumulativeScore: {wins: 0, losses: 0, ties: 0, scoreByStat: null}`, a non-null object
  with a null inside, which the earlier null-safety pass (and its fixture) did not cover. The
  percentage-category lookups now treat a null `scoreByStat` (and null entries in it) as empty,
  and the fixture carries the live shape.
- `rosterSettings.positionLimitNames` was off by one. Recorded live, `positionLimits` is keyed
  by defaultPositionId (1=PG ... 5=C, plus an unused key 0); a league with a maximum of 4
  centers returns `{"5": 4}`. The 1.2.0 note claiming keys 2-6 was wrong, and the limit was
  reported on PF.
- Free agents all showed `percentOwned: 0.0`. ESPN nests ownership under
  `players[].player.ownership`; the code read `players[].ownership`, which does not exist.
  Affects `get_free_agents`, `get_trending_players` and `search_players`.
- `get_my_current_matchup` dropped every stat when `verbose=False`. Rosters now keep the
  per-game averages `get_team_roster` returns (plus injury details and today's game); only
  the season `totals` block needs `verbose=True`.
- `gamesPlayed` was 0 for players with a full stat line: ESPN sometimes omits stat 42. It is
  now derived from season totals / per-game averages, and `null` (not 0) when unknown.
- `ft_pct` / `fg_pct` were `null` for players with games played: a 0.0 percentage from ESPN was
  treated as missing, and a missing percentage key was never computed. Percentages now come
  from ESPN's value when present, else from made / attempted (stat IDs 13-16); per-game `fgm`,
  `fga`, `ftm`, `fta` are returned alongside, so a null FT% always comes with `fta: 0`.
- Rosters listed players ESPN still had under the team but who had been dropped after their
  slot locked (`onTeamId` 0 or another team). Today's roster now excludes them and names them
  in `staleEntriesRemoved`; a roster requested for an explicit past scoring period is kept as
  stored, since `onTeamId` is always the player's current team.
- `get_my_current_matchup` / `analyze_matchup` no longer send `scoringPeriodId` for the current
  or a future week (ESPN's default is today), so the stale-entry filter applies to the rosters
  they analyse. A past week still requests its final day.
- `analyze_matchup` (and `get_matchups`) crashed with `'NoneType' object has no attribute 'get'`
  for a matchup period that had not started: ESPN sends explicit nulls (`cumulativeScore: null`,
  sometimes a null side) rather than omitting keys. Every nested lookup now treats null as empty.
- `get_matchups` took a `scoring_period` argument that was really a matchup period, and also sent
  it to ESPN as a scoring-period (day) index. Renamed to `matchup_period`; the day index is no
  longer sent. Rosters inside `get_my_current_matchup`/`analyze_matchup` are today's for the
  current or a future week and the final day's for a past week, instead of a per-week guess.
- `get_roster_schedule` silently dropped players not on an NBA roster; they are now listed with
  zero games, team `FA`, and a note, and are excluded from the average.

## [1.2.0] - 2026-10-26

### Fixed
- Lineup slot 7 was labelled UTIL. Live data confirmed UTIL is slot 11; slots 7-10 are named
  SG/SF, G/F, PF/C, F/C from the order of ESPN's roster-settings table (unverified by data, as no
  league seen uses them). `scripts/verify_live.py` prints raw slot IDs beside names.
- `rosterSettings.positionLimitNames` uses ESPN's actual key scheme for position limits, which is
  one higher than player position IDs (2=PG ... 6=C), confirmed against a league UI showing a
  maximum of 4 centers.

### Added
- `get_league_settings` is easier to read correctly: `scheduleSettings.matchupPeriodDates` gives
  each matchup period's first and last calendar day (the raw `matchupPeriods` is week-indexed and
  was being misread as daily), `rosterSettings.positionLimitNames` keys the position limits by
  name, and `acquisitionSettings.waiverProcessTimeLocal` converts ESPN's Eastern-time waiver hour
  to `MY_TIMEZONE`.

### Removed
- The legacy low-level `espn_fantasy_basketball_mcp/server.py`, unused since the FastMCP entry
  point replaced it.

### Changed
- `client.py` split: matchup analysis moved to `analysis.py`, calendar math to `dates.py`, name
  matching to `search.py`, and all ID-to-name tables and thresholds to `constants.py`. The client
  class keeps thin aliases to every helper, so its public and test-facing API is unchanged.
- Dependabot keeps the GitHub Actions used by CI current (weekly, grouped).
- Coverage gate raised to 70%.

### Fixed
- Draft tools no longer assume a 12-team, $200, 13-spot league. Budget comes from
  `draftSettings.auctionBudget`, roster size from `rosterSettings.lineupSlotCounts` (IR excluded),
  and the team on the clock from `draftSettings.pickOrder` (auction nominations cycle; snake
  drafts reverse in even rounds). `TeamDraftSummary` reports `budget`, `rosterSize`,
  `remainingSlots`, `draftType`, and real `positionCounts`; league settings expose
  `draftSettings` and `rosterSettings.rosterSize`. The bid reserve now keeps $1 per *other*
  unfilled slot rather than one too many.
- `get_available_players` and `get_trending_players` send the `x-fantasy-filter` header (free
  agents only, sorted by ESPN draft rank / ownership) instead of receiving ESPN's arbitrary
  default slice. Trending players are ranked by ownership change before the limit is applied.

### Changed
- Matchup period dates are now derived from ESPN's own data instead of 7-day weeks counted
  from a Lakers game: opening night comes from the daily scoring-period counter
  (`status.latestScoringPeriod` is today's period), and each period's length in weeks from
  `scheduleSettings.matchupPeriods` (week-indexed; a two-week All-Star period has two entries).
  A six-day opening week and multi-week periods are now measured correctly in `analyze_matchup`
  and `get_roster_schedule`. `get_roster_schedule`'s `scoring_period` parameter is renamed
  `matchup_period`, which is what it always was.

### Added
- New tool `search_players`: find ESPN player IDs by name. Forgiving matching (surname only,
  partial first names, accents, typos) over ESPN's league-independent active player list, cached
  6 hours; optionally reports whether each match is a free agent in your league or which fantasy
  team owns them. Every tool that takes a `player_id` now has a way to get one.
- `get_player_stats` (and everything built on it) now returns per-game `fieldGoalsMade`,
  `fieldGoalsAttempted`, `freeThrowsMade`, and `freeThrowsAttempted` from ESPN stat IDs 13–16.
  `analyze_matchup` uses them to project FG% and FT% as made/attempted; the points-based estimate
  is now only a fallback when ESPN has no projection for a player.
- `analyze_matchup` is availability-aware. Players who are OUT, suspended, in the IR slot, or
  not on an NBA roster (`FA`) contribute no games to projections and are never recommended;
  DOUBTFUL players count for half. New fields: `yourExpectedGames`/`opponentExpectedGames`,
  per-player `availability` and `expectedGames`, and `lineupWarnings` naming starters who cannot
  play or whose status should be checked before tip-off. The games-edge strategy note now uses
  expected games.

### Changed
- ESPN responses are cached in memory, process-wide, with per-endpoint lifetimes (NBA team
  schedules 6h, league settings 10m, team list 5m, scoreboard 60s, live data 15s). Concurrent
  identical requests share one fetch; errors are never cached. `ESPN_MCP_DISABLE_CACHE=1` turns
  it off. Rosters, roster schedules, and player stats inside a matchup analysis are now fetched
  concurrently. A live `analyze_matchup` run went from about 107 requests to a handful.

### Fixed
- The default season is now computed from today's date instead of being hard-coded to 2025.
  ESPN labels a season by the year it ends in, so October–December map to the next year.
  `ESPN_YEAR` still overrides.
- Players on the Warriors, Jazz, and Wizards never received `todaysGame`: the scoreboard feed's
  abbreviations (GS, UTAH, WSH) were normalized to one spelling while the static proTeamId map
  used another. All abbreviations now go through one canonical set (GSW, NOP, NYK, SAS, UTA,
  WAS, ...), including those in `get_player_schedule`.
- `analyze_matchup` for the current week no longer double counts games already played:
  projections, `yourGamesRemaining`/`opponentGamesRemaining`, and per-player `gamesRemaining`
  now count only games that have not tipped off yet and that fall inside the matchup period.
  (The roster schedule deliberately spans an extra week for `gamesNextWeek`; those games were
  previously being projected into the current matchup.) `PlayerScheduleGame` gains
  `datetimeISO` so tip-off time is available.
- `analyze_matchup` compared FG% and FT% against 0.45/0.40 while `PlayerStats` stores
  percentages on a 0–100 scale, so every player counted as a good shooter. Thresholds are now
  48/43 for FG% and 80/70 for FT%.
- CI is green again: 5 stale tests updated to the current tool signatures and batched player-stats call,
  20 mypy errors resolved, ruff lint and formatting applied.
- Tools that act on your team (`get_team_roster`, `should_i_bid`, `who_should_i_target_next`,
  `analyze_my_draft_strategy`) now raise a clear `team_id is required` error instead of passing `None`
  to the ESPN client.
- `get_matchups` no longer fetches league settings twice.

### Added
- Players with no NBA team (ESPN `proTeamId` 0, shown as "FA" in the ESPN UI) now get
  `proTeamAbbrev` "FA" instead of null, so an unsigned player sitting in a lineup slot is visible.
- `scripts/verify_live.py`: read-only PASS/FAIL verification against your real league (season,
  today's-game lookups, current-week matchup projections). Reads credentials from the
  environment or, when unset, from your Claude Desktop config. `.env.example` as an alternative.

### Changed
- CI runs on every branch, installs from `uv.lock`, checks formatting, type-checks the server entry
  point, and runs with read-only repository permissions. The Codecov upload step was removed.
- Coverage gate lowered from 80% to 40% as a ratchet, because the 2025 feature work had no tests;
  raised to 55% with the regression tests below.
- README documents all 19 tools, the `ESPN_YEAR` convention, and the CI setup. The badge now points
  at this repository.
- `uv.lock` and `.python-version` are no longer gitignored (they were already tracked).

## [1.1.0] - 2025-12-21 (branch `mcp-improvements`, merged to main 2026-10-25)
- New tools: `get_league_settings`, `get_team_season_stats`, `get_my_current_matchup`,
  `analyze_matchup`, `get_roster_schedule`.
- Corrected ESPN stat ID mapping (1=BLK, 2=STL, 3=AST, 6=REB) and stat split IDs so `last_7`,
  `last_15`, `last_30`, and `projections` return the right data.
- `x-fantasy-filter` sent as a request header; free agents filtered with ESPN's `FREEAGENT`/`WAIVERS`
  status; `get_player_stats` accepts a list of IDs and makes one request.
- Human-readable position, lineup slot, pro team, and scoring category names; ISO timestamps in the
  `MY_TIMEZONE` timezone; today's game attached to roster entries; accurate injury status.
- HTTPS enforced, 30s request timeout, input validation, generic error messages, security notes in README.
- Compiled `.pyc` files removed from version control.

## [1.0.0] - 2025-09-12
- Initial release
- ESPN Fantasy Basketball API integration
- Live draft assistant tools
- Comprehensive test suite

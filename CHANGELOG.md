# Changelog

## [Unreleased]

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

# Changelog

## [Unreleased]

### Fixed
- A roster requested for another scoring period still carried today's games in each entry's
  `todaysGame`, which made a Wednesday roster look like a frozen Monday payload (live report).
  The scoreboard is now fetched for the roster's own date; `Roster.gamesDate` and
  `todaysGame.date` say which day the games are for.
- ESPN also uses `INDIVIDUAL_FIRSTGAME_WEEKLY` for lineup locks (each player's slot locks at
  his first game of the week), seen live; it is now described and treated as a weekly lock in
  every roster note, lineup warning and simulation caveat. An unknown rule gets an explicit
  "not recognised, trust the per-slot flags" note instead of daily-lock advice.

### Added
- Rosters carry `requestedScoringPeriod` and `espnScoringPeriodId` (what ESPN echoed), and the
  note flags a mismatch, so "did I get the day I asked for" is answerable from the response.
  Each scoring period is its own ESPN request and cache entry (the cache key includes the
  query parameters); a test pins that.
- Lineup-lock awareness. Rosters and `analyze_matchup` report the league's `lineupLockRule`
  and description, and every lineup message is written for the rule in force: with daily
  locks (INDIVIDUAL_GAME) the roster note points at tomorrow's scoring period and warnings say
  "move to bench"; with weekly locks (FIRSTGAME_WEEKLY) the note says the lineup is locked
  until the next matchup period and when that starts, warnings for the week in progress say
  nothing can change, warnings for next week say to act before the first game, and
  `simulate_roster_move` notes that an added player cannot start until next period.

### Added
- `simulate_roster_move` tool: re-runs the matchup projection before and after hypothetical
  drops and adds, on one basis for both teams, and returns per-category deltas, which
  categories flip, the change in expected games, how the added players project, and a
  roster-legality check. No more mixing bases by hand.
- `can_add_player` tool and `check_roster_move`: roster size against the league limit,
  position counts against the position limits (by primary position for the verdict, by slot
  eligibility as a warning, since ESPN does not document which it enforces), acquisitions
  left this matchup, and each player's availability (free agent, on waivers, owned).
- `analyze_matchup` takes `basis` (projections, season, last_7, last_15, last_30, blend) and
  applies it to both teams; the response states the basis, lists players who fell back to
  projections, and gives every player's basis, season and projected per-game lines side by
  side. Every non-IR rostered player is listed in `playerRecommendations` (those who cannot
  play at priority 1), so the list matches `get_team_roster`.
- Closeness has a "near" band: `closeness` is close, near (within 1.5x the close threshold)
  or clear, with `nearThreshold`; `nearCategories` is returned and the strategy notes name the
  close and near categories to prioritise and the far-behind ones not worth chasing.
- `get_free_agents(verbose=true)` returns `projections` beside `stats`; `compare_players`
  takes `timeframe` and returns `bases` with the same players on season, projections and the
  requested timeframe, plus `winners_by_basis`.
- Injury context: `injuryReturnDateType` says whether ESPN's return date is a reported timeline
  or its next-game placeholder for day-to-day players; roster and free-agent stats carry
  `teamGamesPlayed` and `gamesMissed` so "2 of 10" is visible.
- `status.transactionMatchupPeriod`, `transactionScoringPeriodDate` and `transactionNote`
  say which matchup period an add made now counts against.

### Fixed
- `analyze_matchup` for a future week read the roster ESPN stores for that week's first day,
  which can lag an add made today. Players now come from today's roster (the same source as
  `get_team_roster`); only lineup slots come from the planned lineup. `rosterSource` says so.
- `strategyNotes` told you to prioritise the categories you were losing by most; they now
  follow the closeness classification.

### Changed
- Tools that return several items (`get_league_teams`, `get_free_agents`, `get_matchups`,
  `get_nba_schedule`, `get_transactions`, `get_available_players`, `get_trending_players`,
  `search_players`, and `get_player_stats` with a list of IDs) now return one object,
  `{"count": N, "<items>": [...]}`, instead of a bare list. FastMCP turns a returned list into
  one content block per element, so Claude was receiving each free agent as a separate
  top-level object. A test asserts no tool is annotated to return a list.

### Security
- The ESPN cookies (`espn_s2`, `swid`) are no longer tool parameters on any of the 22 tools.
  They are read from `ESPN_S2` / `ESPN_SWID` only. A cookie passed as a tool argument would have
  been written into the conversation transcript; a test now fails if any tool schema exposes
  them.

### Fixed
- `get_team_season_stats` reported ESPN's record as `matchupWins` / `matchupLosses`. In an H2H
  Each Category league that record counts categories (4-12 after two weeks of eight categories),
  so it was a category record relabelled. The matchup W-L-T is now derived from the schedule's
  decided results (`completedMatchupPeriods` says how many it covers, ties are a count, not
  null), ESPN's record is alongside as `espnRecord` with `espnRecordType` /
  `espnRecordDescription`, and `gamesBack` is on the matchup record with a description.
  `totalGamesPlayed`, which ESPN always sends as 0, is gone.
- Roster lock notes said "pass scoring_period=N", a parameter `get_my_current_matchup` does not
  have. The note now names the tool that has it (`get_team_roster`), and a test checks that
  every parameter named in a response note exists on the tool it names.
- A player ESPN sends no stat line for had `stats: null`; it now has `gamesPlayed: 0` with a
  note.
- `get_player_stats(timeframe="projections")` could pick a previous season's projection set
  when ESPN sent both; the requested season's set is preferred.

### Added
- `get_league_teams`: `isMyTeam`, `standingsRank` (teams are returned in standings order),
  ESPN's `playoffSeed`, and `matchupRecord` (matchup-level W-L-T from completed periods). A
  `matchupAcquisitionTotalsNote` explains an acquisition entry for a period that has not
  started.
- `injuryStatusNote` on roster and free-agent players when ESPN fantasy's status and ESPN's
  NBA injury report disagree by two steps or more (OUT vs. "probable"), saying which is which.
- `get_league_settings`: `lineupLocktimeDescription` explains `INDIVIDUAL_GAME` and
  `FIRSTGAME_WEEKLY`, and says plainly when a code (such as `INDIVIDUAL_FIRSTGAME_WEEKLY`) is
  not recognised, pointing at the per-slot `lineupLocked` flags.
- Matchup sides carry `categoryWins` / `categoryLosses` / `categoryTies` for the week so far.
- `analyze_matchup`: `projectionMethod` states how projections are built; `expectedGamesBreakdown`
  itemises why expected games are below games remaining (one line per discounted player, with
  the arithmetic); `opponentPlayers` shows the opponent's roster as the projection sees it;
  each category projection carries `closeThreshold` and a `closenessRule`; each recommendation
  carries `closeCategoriesHelped` / `closeCategoriesHurt` and `injuryDetails`.

### Changed
- `analyze_matchup` closeness is per category: counting stats use a per-category margin
  (`CLOSE_MARGINS`, roughly two strong player-games, so blocks at 0.4 and points at 0.4 are not
  judged on one scale) and percentages are judged in made shots over the projected attempts
  (`CLOSE_PERCENTAGE_MAKES`), so an FG% lead worth one basket is close; the flat 0.002 was not.
- `analyze_matchup` start/sit priority is driven by close categories. Helping a close category
  is worth most, hurting one costs, helping a category you trail by a wide margin earns a little,
  and hurting a category already projected lost by a mile costs nothing (a shot-blocker is no
  longer ranked last for hurting points, assists and threes you were losing anyway). The
  "helps" thresholds were tightened (blocks 1.0, threes 2.0, steals 1.2, points 18, rebounds 7,
  assists 5) and every claim in `reasoning` shows the per-game number behind it.
- Tool output leaves out null fields and the raw `cumulativeScore` stat-ID block (category
  scores, component stats and category W/L/T carry the same data by name). Slim rosters
  (`get_my_current_matchup` without `verbose`) also drop numeric `eligibleSlots` (names are
  kept), `jersey`, keeper values and the millisecond acquisition date. A current-matchup
  response is roughly half the size it was.
- Synthetic fixtures: team records now sum to one completed period of nine categories and match
  the period-1 cumulative scores, so the category-record invariant holds on the fixture league.

### Fixed (earlier in this release)
- `get_nba_schedule(date=...)` always returned today's games: ESPN's scoreboard reads the
  `dates` query parameter and silently ignores `date`. (Ported from the unmerged PR #14.)
- Per-game stats were read from a key ESPN does not send (`averages`); the real key is
  `averageStats`, confirmed in recorded payloads. The code had been recomputing per-game numbers
  from season totals and games played, which failed whenever ESPN omitted stat 42 and was the
  root cause of the "gamesPlayed 0 with 76 FTA" report. Both keys are now read, ESPN's first.
  (Ported from PR #14.)

### Added
- `get_transactions` tool (ESPN `mTransactions2` view): recent adds, drops, waiver claims and
  trades, newest first, with player and team names and a one-line summary, filterable by team
  or scoring period. Answers "who dropped this player and when". ESPN logs every lineup save
  as a `ROSTER` / `FUTURE_ROSTER` transaction; those are hidden unless
  `include_lineup_changes=true`, while a drop made from the roster page (a `ROSTER`
  transaction with a `DROP` item) is always shown as a "roster move".
- Waiver state on free agents and search results: `availabilityStatus` (FREEAGENT = addable
  now, WAIVERS = ESPN's "WA" flag), `waiverProcessDateISO` and an `availabilityNote`.
- `get_league_teams`: `waiverRank`, ESPN's `transactionCounter`, and `acquisitionsThisMatchup`
  / `acquisitionLimitThisMatchup` / `acquisitionsRemainingThisMatchup`.
- `get_league_settings`: when `matchupLimitPerScoringPeriod` is true the allowance for a
  matchup period is the per-day limit times its length; `effectiveLimitByMatchupPeriod` (6 for
  a six-day opening week, 7 for a normal week, 14 for the All-Star fortnight),
  `effectiveLimitCurrentMatchup`, and the description reads "1 per day (scoring period), so 7
  for matchup period 2 (7 days)". `waiverOrderReset` with a `waiverOrderDescription`.
- Per-slot lock state on rosters: each entry's `lineupLocked`, plus `lockedSlots` and
  `unlockedSlots` ("SLOT: player") for the roster's scoring period.
- `teamAbbrev` on matchup sides and `yourTeamAbbrev` / `opponentTeamAbbrev` on the analysis,
  so a team renamed mid-week can still be identified.

### Fixed
- `acquisitionSettings.waiverProcessTimeLocal` treated ESPN's `waiverProcessHour` as Eastern
  time. Recorded live, a league with hour 8 had every on-waivers player's `waiverProcessDate`
  at 08:00Z (03:00 ET, 02:00 CT), so the hour is UTC; the 1.2.0 conversion reported 07:00 CT.
  `waiverProcessHourTimezone` now says `UTC`, and each free agent's `waiverProcessDateISO` is
  the authoritative time.

### Changed
- `analyze_matchup` / `get_my_current_matchup` for a *future* matchup period now request the
  roster for that period's first scoring period (the lineup as set for that day) instead of
  today's. The stale-entry filter applies to today's and future rosters alike.
- A player with zero attempts now has `ft_pct` / `fg_pct` null even when ESPN sends 0.0 for the
  percentage (the docstring promised null; the code returned 0.0). Attempts are alongside.
- `scripts/record_fixtures.py` also records the transactions view.

### Added (merged in #15)
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

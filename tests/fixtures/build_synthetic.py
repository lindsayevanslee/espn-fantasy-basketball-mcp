#!/usr/bin/env python3
"""Regenerate the synthetic ESPN fixtures in this directory.

The fixtures mirror the shape of real ESPN Fantasy Basketball and ESPN site API responses but
contain invented teams, players and numbers, so they can be committed without exposing a
league. The scenario is frozen at Sunday 2026-11-01 (Eastern), the last day of matchup
period 2 of the 2026-27 season (ESPN season 2027):

- scoring period 1 = opening night Tue 2026-10-20, so 2026-11-01 is scoring period 13
- matchup period 2 = Oct 26 - Nov 1 (current), 3 = Nov 2 - 8 (next, not started), ...
- team 8 "Statistical Anomalies" is "us", team 12 is the period-3 opponent, team 3 the
  period-2 opponent

Each file corresponds to one request, named by tests/fixture_espn.py::fixture_name.
Run from the repository root:  uv run python tests/fixtures/build_synthetic.py

Real responses recorded with scripts/record_fixtures.py land in ./recorded/ instead.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parent
ET = ZoneInfo("America/New_York")
SEASON = 2027
LEAGUE_ID = 12345

# ----------------------------------------------------------------------------- settings
MATCHUP_PERIODS = (
    {str(k): [k] for k in range(1, 17)}
    | {"17": [17, 18]}
    | {str(k): [k + 1] for k in range(18, 24)}
)
SCORING_STATS = [0, 1, 2, 3, 6, 11, 17, 19, 20]  # PTS BLK STL AST REB TO 3PM FG% FT%

settings = {
    "id": LEAGUE_ID,
    "seasonId": SEASON,
    "segmentId": 0,
    "scoringPeriodId": 13,
    "gameId": 3,
    "members": [{"id": "REDACTED-ID", "displayName": "REDACTED", "isLeagueManager": True}],
    "settings": {
        "name": "Fixture League",
        "size": 12,
        "isPublic": False,
        "scoringSettings": {
            "scoringType": "H2H_CATEGORY",
            "playerRankType": "STANDARD",
            "matchupTieRule": "NONE",
            "allowOutOfPositionScoring": False,
            "scoringItems": [
                {"statId": sid, "points": 1.0, "isReverseItem": sid == 11, "pointsOverrides": {}}
                for sid in SCORING_STATS
            ],
        },
        "scheduleSettings": {
            "matchupPeriodCount": 23,
            "matchupPeriodLength": 1,
            "matchupPeriods": MATCHUP_PERIODS,
            "periodTypeId": 2,
            "playoffTeamCount": 6,
            "playoffMatchupPeriodLength": 1,
            "playoffSeedingRule": "TOTAL_POINTS_SCORED",
        },
        "rosterSettings": {
            "lineupSlotCounts": {
                "0": 1,
                "1": 1,
                "2": 1,
                "3": 1,
                "4": 1,
                "5": 1,
                "6": 1,
                "11": 3,
                "12": 3,
                "13": 1,
            },
            "positionLimits": {"0": 0, "1": -1, "2": -1, "3": -1, "4": -1, "5": 4},
            "lineupLocktimeType": "INDIVIDUAL_GAME",
            "rosterLocktimeType": "INDIVIDUAL_GAME",
            "isBenchUnlimited": False,
            "moveLimit": -1,
        },
        "acquisitionSettings": {
            "acquisitionType": "WAIVERS_TRADITIONAL",
            "waiverHours": 24,
            "waiverProcessDays": ["SUNDAY"],
            "waiverProcessHour": 8,  # UTC: live process dates were all 08:00Z (03:00 ET)
            "matchupAcquisitionLimit": 1.0,
            "matchupLimitPerScoringPeriod": True,  # 1 per day: 6 in the opening week, 7 after
            "acquisitionLimit": -1,
            "minimumBid": 0,
            "waiverOrderReset": False,  # a successful claim sends the team to the back
            "isUsingAcquisitionBudget": False,
        },
        "tradeSettings": {
            "deadlineDate": 1772514000000,
            "vetoVotesRequired": 4,
            "revisionHours": 48,
            "max": -1,
            "allowOutOfUniverse": False,
        },
        "draftSettings": {
            "type": "AUCTION",
            "auctionBudget": 200,
            "pickOrder": list(range(1, 13)),
            "keeperCount": 0,
            "date": 1760400000000,
        },
    },
    "status": {
        "currentMatchupPeriod": 2,
        "latestScoringPeriod": 13,
        "firstScoringPeriod": 1,
        "finalScoringPeriod": 174,
        "isActive": True,
        "transactionScoringPeriod": 14,
        "previousSeasons": [2026],
    },
}

# ----------------------------------------------------------------------------- teams
TEAMS = {
    8: ("SA", "Statistical Anomalies", 11, 6, 1),
    3: ("RR", "Rim Runners", 9, 8, 1),
    12: ("WW", "Waiver Wire Warriors", 7, 10, 1),
    5: ("FT", "Fifth Team", 8, 9, 1),
}
# waiver order (1 = first claim) and ESPN's transaction counter per team
WAIVER_RANK = {8: 12, 3: 1, 12: 5, 5: 7}
TRANSACTIONS = {
    8: (3, 3, 0, 1, {"1": 2, "2": 1}),  # acquisitions, drops, trades, moveToIR, by period
    3: (1, 1, 0, 0, {"2": 1}),
    12: (5, 5, 1, 0, {"1": 2, "2": 3}),
    5: (2, 2, 0, 0, {"1": 1, "2": 1}),
}


def team_block(team_id: int) -> dict:
    abbrev, name, w, losses, t = TEAMS[team_id]
    return {
        "id": team_id,
        "abbrev": abbrev,
        "name": name,
        "logo": f"https://example.invalid/logo{team_id}.png",
        "owners": ["REDACTED-ID"],
        "primaryOwner": "REDACTED-ID",
        "playoffSeed": 1,
        "waiverRank": WAIVER_RANK[team_id],
        "transactionCounter": {
            "acquisitionBudgetSpent": 0,
            "acquisitions": TRANSACTIONS[team_id][0],
            "drops": TRANSACTIONS[team_id][1],
            "trades": TRANSACTIONS[team_id][2],
            "moveToIR": TRANSACTIONS[team_id][3],
            "moveToActive": 4,
            "misc": 0,
            "paid": 0,
            "teamCharges": 0,
            "matchupAcquisitionTotals": TRANSACTIONS[team_id][4],
        },
        "record": {
            "overall": {
                "wins": w,
                "losses": losses,
                "ties": t,
                "percentage": round((w + 0.5 * t) / (w + losses + t), 3),
                "pointsFor": 0.0,
                "pointsAgainst": 0.0,
                "gamesBack": 0.0,
                "streakLength": 1,
                "streakType": "WIN",
            }
        },
    }


teams_response = {
    "id": LEAGUE_ID,
    "seasonId": SEASON,
    "scoringPeriodId": 13,
    "members": [{"id": "REDACTED-ID", "displayName": "REDACTED"}],
    "teams": [team_block(t) for t in TEAMS],
    "status": settings["status"],
}

# ----------------------------------------------------------------------------- players
# (id, name, defaultPositionId, eligibleSlots, proTeamId, injuryStatus)
PLAYERS = {
    # team 8
    1001: ("Ava Guard", 1, [0, 5, 11, 12], 2, "ACTIVE"),
    1002: ("Jon Collins", 4, [3, 6, 11, 12], 6, "OUT"),
    1003: ("Cason Wallace", 2, [1, 5, 11, 12], 25, "ACTIVE"),
    1004: ("Benched Guy", 5, [4, 11, 12], 0, "ACTIVE"),
    # team 3
    2001: ("Max Center", 5, [4, 11, 12], 14, "ACTIVE"),
    2002: ("Dee Wing", 3, [2, 6, 11, 12], 18, "DAY_TO_DAY"),
    2003: ("Rook Guard", 1, [0, 5, 11, 12], 14, "ACTIVE"),
    # team 12
    3001: ("Stale Center", 5, [4, 11, 12], 28, "ACTIVE"),
    3002: ("Loyal Forward", 4, [3, 6, 11, 12], 1, "ACTIVE"),
    3003: ("Traded Guard", 1, [0, 5, 11, 12], 30, "ACTIVE"),
    3004: ("Solid Wing", 3, [2, 6, 11, 12], 16, "ACTIVE"),
    # team 5
    5001: ("Lone Star", 2, [1, 5, 11, 12], 10, "ACTIVE"),
    # free agents / streamers
    7001: ("Drew Wing", 3, [2, 6, 11, 12], 9, "ACTIVE"),
    7002: ("Kris Big", 5, [4, 11, 12], 12, "DAY_TO_DAY"),
    7003: ("Zed Streamer", 2, [1, 5, 11, 12], 21, "ACTIVE"),
    9001: ("Streamer One", 1, [0, 5, 11, 12], 7, "ACTIVE"),
    9002: ("Streamer Two", 3, [2, 6, 11, 12], 13, "ACTIVE"),
    9003: ("List Only", 4, [3, 6, 11, 12], 16, "ACTIVE"),
}

PRO_ABBREV = {
    0: "FA",
    1: "ATL",
    2: "BOS",
    6: "DAL",
    7: "DEN",
    9: "GSW",
    10: "HOU",
    12: "LAC",
    13: "LAL",
    14: "MIA",
    16: "MIN",
    18: "NYK",
    21: "PHX",
    25: "OKC",
    28: "TOR",
    30: "CHA",
}


def player_obj(pid: int) -> dict:
    name, pos, slots, pro, injury = PLAYERS[pid]
    first, last = name.split(" ", 1)
    return {
        "id": pid,
        "fullName": name,
        "firstName": first,
        "lastName": last,
        "jersey": str(pid % 100),
        "defaultPositionId": pos,
        "eligibleSlots": slots,
        "proTeamId": pro,
        "injured": injury == "OUT",
        "injuryStatus": injury,
        "active": True,
        "droppable": True,
        "universeId": 2,
    }


def stat_set(
    stat_id: str, gp: int | None, per_game: dict[str, float], omit: set[str] = frozenset()
) -> dict:
    """One ESPN stat set: `averages` per game and `stats` totals (= averages * games).

    Keys: 0 PTS, 1 BLK, 2 STL, 3 AST, 6 REB, 11 TO, 13 FGM, 14 FGA, 15 FTM, 16 FTA, 17 3PM,
    40 MIN, 19 FG%, 20 FT%, 42 GP. Percentages are derived from made/attempted unless omitted.
    """
    games = gp or 0
    averages = {k: v for k, v in per_game.items() if k not in omit}
    totals = {k: round(v * games, 1) for k, v in per_game.items() if k not in omit}
    if per_game.get("14"):
        pct = round(per_game["13"] / per_game["14"], 3)
        if "19" not in omit:
            averages["19"] = pct
            totals["19"] = pct
    if per_game.get("16"):
        pct = round(per_game["15"] / per_game["16"], 3)
        if "20" not in omit:
            averages["20"] = pct
            totals["20"] = pct
    if gp is not None and "42" not in omit:
        totals["42"] = float(gp)
    return {
        "id": stat_id,
        "seasonId": SEASON,
        "statSourceId": int(stat_id[0]),
        "statSplitTypeId": int(stat_id[1]),
        "proTeamId": 0,
        "scoringPeriodId": 0,
        "externalId": str(SEASON),
        "averageStats": averages,  # ESPN's key (recorded live); not "averages"
        "stats": totals,
        "appliedAverage": round(
            sum(per_game.get(k, 0) for k in ("0", "1", "2", "3", "6", "17")), 1
        ),
        "appliedTotal": 0.0,
    }


def line(pts, reb, ast, stl, blk, to, tpm, fgm, fga, ftm, fta, mins) -> dict[str, float]:
    return {
        "0": pts,
        "6": reb,
        "3": ast,
        "2": stl,
        "1": blk,
        "11": to,
        "17": tpm,
        "13": fgm,
        "14": fga,
        "15": ftm,
        "16": fta,
        "40": mins,
    }


# Season actuals: (games, per-game line, keys ESPN happened to omit)
SEASON_STATS: dict[int, tuple[int | None, dict[str, float], set[str]]] = {
    # no stat 42 -> games must be derived from totals / averages (272 min / 34.0 = 8)
    1001: (8, line(22.0, 5.0, 7.0, 1.5, 0.5, 2.5, 2.5, 8.0, 17.5, 3.5, 4.0, 34.0), {"42"}),
    # no FT% key -> FT% must come from FTM/FTA (28 / 35 = 80.0%)
    1002: (7, line(18.0, 9.0, 2.0, 0.6, 1.1, 1.4, 1.0, 7.0, 13.5, 4.0, 5.0, 30.0), {"20"}),
    # zero free-throw attempts: FT% is genuinely undefined, and fta must say 0
    1003: (9, line(9.0, 3.0, 2.0, 1.2, 0.3, 1.0, 1.5, 3.5, 8.0, 0.0, 0.0, 26.0), {"20"}),
    2001: (8, line(16.0, 11.0, 1.5, 0.5, 1.8, 1.9, 0.0, 6.5, 11.0, 3.0, 4.5, 29.0), set()),
    2002: (6, line(14.0, 4.5, 2.5, 1.0, 0.4, 1.2, 2.2, 5.0, 11.5, 1.8, 2.0, 27.0), set()),
    2003: (8, line(7.0, 2.0, 3.0, 0.8, 0.1, 1.1, 1.0, 2.5, 6.0, 1.0, 1.2, 18.0), set()),
    3001: (8, line(10.0, 9.0, 2.0, 0.6, 1.3, 1.2, 0.0, 4.5, 7.0, 1.0, 2.0, 25.0), set()),
    3002: (8, line(13.0, 6.5, 1.5, 0.7, 0.6, 1.0, 1.2, 5.0, 10.0, 1.8, 2.3, 28.0), set()),
    3003: (8, line(11.0, 3.0, 4.0, 1.0, 0.2, 1.6, 1.3, 4.0, 9.5, 1.7, 2.1, 24.0), set()),
    3004: (8, line(15.0, 5.0, 2.0, 1.1, 0.5, 1.3, 2.0, 5.5, 12.0, 2.0, 2.4, 30.0), set()),
    5001: (8, line(12.0, 3.0, 2.0, 0.9, 0.2, 1.1, 1.8, 4.5, 10.0, 1.3, 1.5, 25.0), set()),
    7001: (8, line(14.5, 4.5, 2.3, 1.1, 0.4, 1.5, 2.1, 5.3, 11.8, 1.8, 2.2, 28.5), {"42"}),
    7002: (7, line(11.0, 8.5, 1.2, 0.4, 1.5, 1.3, 0.1, 4.6, 8.0, 1.7, 2.6, 24.0), set()),
    7003: (8, line(8.0, 2.5, 3.5, 1.3, 0.2, 1.4, 1.1, 3.0, 7.0, 1.0, 1.2, 20.0), set()),
    9001: (8, line(13.0, 3.5, 5.5, 1.4, 0.2, 2.0, 1.6, 4.8, 10.5, 1.8, 2.0, 27.0), set()),
    9002: (8, line(12.0, 5.5, 1.8, 0.8, 0.7, 1.1, 1.9, 4.4, 9.5, 1.3, 1.6, 26.0), set()),
    9003: (8, line(9.5, 6.0, 1.0, 0.5, 0.9, 0.8, 0.6, 3.8, 7.5, 1.3, 1.8, 22.0), set()),
}


def projection(pid: int) -> dict[str, float]:
    """Rest-of-season per-game projection: the season line nudged toward the mean."""
    _, per_game, _ = SEASON_STATS[pid]
    return {k: round(v * 0.97 + (0.3 if k == "0" else 0.0), 2) for k, v in per_game.items()}


def full_stats(pid: int) -> list[dict]:
    if pid not in SEASON_STATS:
        return []  # unsigned: nothing this season
    gp, per_game, omit = SEASON_STATS[pid]
    season = stat_set(f"00{SEASON}", gp, per_game, omit)
    if pid == 1003:  # live: ESPN reports FT% 0.0 for a player with 0 FTA
        season["averageStats"]["20"] = 0.0
        season["stats"]["20"] = 0.0
    return [
        season,
        stat_set(f"10{SEASON}", 82, projection(pid)),
        stat_set(f"01{SEASON}", 3, {k: round(v * 1.05, 2) for k, v in per_game.items()}),
    ]


ROSTERS: dict[int, list[tuple[int, int, int, bool]]] = {
    # team: [(playerId, lineupSlotId, onTeamId, lineupLocked)]
    8: [(1001, 0, 8, True), (1002, 3, 8, False), (1003, 1, 8, False), (1004, 12, 8, False)],
    3: [(2001, 4, 3, False), (2002, 2, 3, False), (2003, 12, 3, False)],
    # 3001 was dropped after his slot locked (onTeamId 0 = free agent pool); 3003 was traded
    12: [(3001, 4, 0, True), (3002, 3, 12, True), (3003, 12, 5, True), (3004, 2, 12, True)],
    5: [(5001, 1, 5, False)],
}
ACQUIRED = 1760900000000  # epoch ms, draft day


def roster_entry(pid: int, slot: int, on_team: int, locked: bool) -> dict:
    return {
        "playerId": pid,
        "lineupSlotId": slot,
        "acquisitionDate": ACQUIRED,
        "acquisitionType": "DRAFT",
        "injuryStatus": "NORMAL",
        "status": "ONTEAM",
        "playerPoolEntry": {
            "id": pid,
            "onTeamId": on_team,
            "keeperValue": 0,
            "keeperValueFuture": 0,
            "lineupLocked": locked,
            "rosterLocked": locked,
            "tradeLocked": False,
            "status": "ONTEAM" if on_team else "FREEAGENT",
            "player": {**player_obj(pid), "stats": full_stats(pid)},
        },
    }


roster_response = {
    "id": LEAGUE_ID,
    "seasonId": SEASON,
    "scoringPeriodId": 13,
    "members": [{"id": "REDACTED-ID", "displayName": "REDACTED"}],
    "teams": [
        {**team_block(t), "roster": {"entries": [roster_entry(*e) for e in ROSTERS[t]]}}
        for t in TEAMS
    ],
    "status": settings["status"],
}


# ----------------------------------------------------------------------------- matchups
def side(
    team_id: int, totals: dict[str, float] | None, wins=0, losses=0, ties=0, null_score=False
) -> dict:
    if totals is None:
        # Observed live for a matchup that has not started: cumulativeScore is an object whose
        # scoreByStat is null (not a null cumulativeScore). null_score=True gives the other
        # variant some leagues send.
        return {
            "teamId": team_id,
            "totalPoints": 0.0,
            "totalProjectedPoints": 0.0,
            "gamesPlayed": 0,
            "cumulativeScore": None
            if null_score
            else {"wins": 0, "losses": 0, "ties": 0, "statBySlot": None, "scoreByStat": None},
            "pointsByScoringPeriod": None,
            "rosterForCurrentScoringPeriod": None,
        }
    return {
        "teamId": team_id,
        "totalPoints": 0.0,
        "totalProjectedPoints": 0.0,
        "gamesPlayed": int(totals.pop("games", 0)),
        "cumulativeScore": {
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "statBySlot": None,
            "scoreByStat": {
                k: {"score": v, "ineligible": False, "rank": 0, "result": None}
                for k, v in totals.items()
            },
        },
    }


def week_totals(pts, reb, ast, stl, blk, to, tpm, fgm, fga, ftm, fta, games) -> dict[str, float]:
    return {
        "0": pts,
        "6": reb,
        "3": ast,
        "2": stl,
        "1": blk,
        "11": to,
        "17": tpm,
        "13": fgm,
        "14": fga,
        "15": ftm,
        "16": fta,
        "19": round(fgm / fga, 4),
        "20": round(ftm / fta, 4),
        "games": games,
    }


schedule = [
    # period 1: complete
    {
        "id": 1,
        "matchupPeriodId": 1,
        "playoffTierType": "NONE",
        "winner": "HOME",
        "home": side(8, week_totals(560, 230, 140, 38, 22, 66, 58, 210, 460, 88, 115, 29), 6, 3, 0),
        "away": side(3, week_totals(540, 250, 120, 40, 28, 60, 50, 205, 450, 76, 104, 28), 3, 6, 0),
    },
    {
        "id": 2,
        "matchupPeriodId": 1,
        "playoffTierType": "NONE",
        "winner": "AWAY",
        "home": side(
            12, week_totals(500, 220, 110, 35, 20, 70, 45, 190, 430, 70, 100, 27), 4, 5, 0
        ),
        "away": side(5, week_totals(520, 215, 125, 36, 24, 62, 52, 200, 440, 75, 98, 28), 5, 4, 0),
    },
    # period 2: in progress (today is its last day)
    {
        "id": 3,
        "matchupPeriodId": 2,
        "playoffTierType": "NONE",
        "winner": "UNDECIDED",
        "home": side(3, week_totals(580, 260, 130, 45, 30, 65, 55, 220, 470, 80, 110, 30), 4, 5, 0),
        "away": side(8, week_totals(612, 240, 150, 40, 25, 70, 60, 230, 500, 92, 120, 31), 5, 4, 0),
    },
    {
        "id": 4,
        "matchupPeriodId": 2,
        "playoffTierType": "NONE",
        "winner": "UNDECIDED",
        "home": side(5, week_totals(530, 225, 120, 37, 23, 61, 50, 205, 445, 72, 96, 28), 5, 4, 0),
        "away": side(
            12, week_totals(515, 235, 115, 33, 26, 68, 47, 195, 440, 74, 102, 28), 4, 5, 0
        ),
    },
    # period 3: not started -> ESPN sends explicit nulls
    {
        "id": 5,
        "matchupPeriodId": 3,
        "playoffTierType": "NONE",
        "winner": "UNDECIDED",
        "home": side(8, None),
        "away": side(12, None),
    },
    {
        "id": 6,
        "matchupPeriodId": 3,
        "playoffTierType": "NONE",
        "winner": "UNDECIDED",
        "home": side(3, None),
        "away": side(5, None),
    },
    # period 14 (January): also not started
    {
        "id": 27,
        "matchupPeriodId": 14,
        "playoffTierType": "NONE",
        "winner": "UNDECIDED",
        "home": side(8, None, null_score=True),
        "away": side(5, None, null_score=True),
    },
]
matchup_response = {
    "id": LEAGUE_ID,
    "seasonId": SEASON,
    "scoringPeriodId": 13,
    "schedule": schedule,
    "status": settings["status"],
}

# ----------------------------------------------------------------------------- kona views
OWNERSHIP = {
    7001: (61.2, 3.4, 40.1),
    7002: (48.9, -1.2, 30.0),
    7003: (5.5, 0.8, 2.1),
    9001: (12.0, 4.5, 6.0),
    9002: (33.3, -0.5, 20.0),
}


WAIVER_PROCESS = int(
    datetime.fromisoformat("2026-11-03T03:00:00").replace(tzinfo=ET).timestamp() * 1000
)  # 08:00Z, as recorded live
ON_WAIVERS = {7003: WAIVER_PROCESS}  # dropped by team 5 on Nov 1


def kona_entry(pid: int, on_team: int) -> dict:
    owned, change, started = OWNERSHIP.get(pid, (99.0, 0.0, 90.0))
    status = "ONTEAM" if on_team else ("WAIVERS" if pid in ON_WAIVERS else "FREEAGENT")
    return {
        "id": pid,
        "onTeamId": on_team,
        "status": status,
        **({"waiverProcessDate": ON_WAIVERS[pid]} if pid in ON_WAIVERS else {}),
        "keeperValue": 0,
        "keeperValueFuture": 0,
        "lineupLocked": False,
        "rosterLocked": False,
        "tradeLocked": False,
        "draftAuctionValue": 0,
        "player": {
            **player_obj(pid),
            # ESPN nests ownership under player, not at the entry level
            "ownership": {
                "percentOwned": owned,
                "percentChange": change,
                "percentStarted": started,
                "auctionValueAverage": 0.0,
                "averageDraftPosition": 0.0,
            },
            "stats": full_stats(pid),
            "draftRanksByRankType": {"STANDARD": {"rank": pid % 200, "auctionValue": 3}},
        },
        "ratings": {},
    }


ON_TEAM = {pid: t for t, entries in ROSTERS.items() for pid, _, on, _ in entries}
free_agents_response = {
    "id": LEAGUE_ID,
    "seasonId": SEASON,
    "scoringPeriodId": 13,
    "players": [kona_entry(pid, 0) for pid in (7001, 7002, 7003)],
    "status": settings["status"],
}
player_info_response = {
    "id": LEAGUE_ID,
    "seasonId": SEASON,
    "scoringPeriodId": 13,
    "players": [
        kona_entry(pid, ON_TEAM.get(pid, 0))
        for pid in PLAYERS
        if pid != 9003  # 9003 is only in the league-independent player list
    ],
    "status": settings["status"],
}


def ms(day: str, hour: int, minute: int = 0) -> int:
    return int(
        datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00").replace(tzinfo=ET).timestamp()
        * 1000
    )


transactions_response = {
    "id": LEAGUE_ID,
    "seasonId": SEASON,
    "scoringPeriodId": 13,
    "transactions": [
        {
            "id": "t-100",
            "type": "FREEAGENT",
            "status": "EXECUTED",
            "executionType": "PROCESS",
            "teamId": 5,
            "memberId": "REDACTED-ID",
            "scoringPeriodId": 13,
            "proposedDate": ms("2026-11-01", 9, 15),
            "processDate": ms("2026-11-01", 9, 15),
            "isPending": False,
            "rating": 0,
            "items": [
                {
                    "playerId": 7003,
                    "type": "DROP",
                    "fromTeamId": 5,
                    "toTeamId": 0,
                    "fromLineupSlotId": 12,
                    "toLineupSlotId": -1,
                },
                {
                    "playerId": 7001,
                    "type": "ADD",
                    "fromTeamId": 0,
                    "toTeamId": 5,
                    "fromLineupSlotId": -1,
                    "toLineupSlotId": 12,
                },
            ],
        },
        {
            "id": "t-101",
            "type": "WAIVER",
            "status": "PENDING",
            "executionType": "PROCESS",
            "teamId": 8,
            "memberId": "REDACTED-ID",
            "scoringPeriodId": 15,
            "proposedDate": ms("2026-11-01", 11, 40),
            "bidAmount": 0,
            "isPending": True,
            "items": [
                {
                    "playerId": 7003,
                    "type": "ADD",
                    "fromTeamId": 0,
                    "toTeamId": 8,
                    "fromLineupSlotId": -1,
                    "toLineupSlotId": 12,
                },
                {
                    "playerId": 1004,
                    "type": "DROP",
                    "fromTeamId": 8,
                    "toTeamId": 0,
                    "fromLineupSlotId": 12,
                    "toLineupSlotId": -1,
                },
            ],
        },
        # a drop made from the roster page: ESPN logs it as ROSTER with a DROP item
        {
            "id": "t-98",
            "type": "ROSTER",
            "status": "EXECUTED",
            "executionType": "EXECUTE",
            "teamId": 12,
            "memberId": "REDACTED-ID",
            "scoringPeriodId": 13,
            "proposedDate": ms("2026-11-01", 8, 30),
            "isPending": False,
            "items": [
                {
                    "playerId": 3001,
                    "type": "DROP",
                    "fromTeamId": 12,
                    "toTeamId": 0,
                    "fromLineupSlotId": 4,
                    "toLineupSlotId": -1,
                },
            ],
        },
        # plain lineup saves (today's and a future day's); hidden unless asked for
        {
            "id": "t-99",
            "type": "ROSTER",
            "status": "EXECUTED",
            "executionType": "EXECUTE",
            "teamId": 12,
            "memberId": "REDACTED-ID",
            "scoringPeriodId": 12,
            "proposedDate": ms("2026-10-31", 17, 5),
            "processDate": ms("2026-10-31", 17, 5),
            "items": [
                {
                    "playerId": 3004,
                    "type": "LINEUP",
                    "fromTeamId": 12,
                    "toTeamId": 12,
                    "fromLineupSlotId": 12,
                    "toLineupSlotId": 2,
                },
            ],
        },
        {
            "id": "t-102",
            "type": "FUTURE_ROSTER",
            "status": "EXECUTED",
            "executionType": "EXECUTE",
            "teamId": 8,
            "memberId": "REDACTED-ID",
            "scoringPeriodId": 14,
            "proposedDate": ms("2026-11-01", 11, 50),
            "items": [
                {
                    "playerId": 1003,
                    "type": "LINEUP",
                    "fromTeamId": 8,
                    "toTeamId": 8,
                    "fromLineupSlotId": 1,
                    "toLineupSlotId": 12,
                },
            ],
        },
    ],
}

players_wl_response = [
    {
        "id": pid,
        "fullName": PLAYERS[pid][0],
        "defaultPositionId": PLAYERS[pid][1],
        "proTeamId": PLAYERS[pid][3],
        "injuryStatus": PLAYERS[pid][4],
        "active": True,
    }
    for pid in PLAYERS
]


# ----------------------------------------------------------------------------- NBA site API
def tip(day: str, hour: int = 19, minute: int = 0) -> str:
    local = datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00").replace(tzinfo=ET)
    return local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%MZ")


# ET game dates per NBA team for the end of period 2, all of period 3 (Nov 2-8) and 4 (Nov 9-15)
GAMES = {
    2: [
        "2026-10-30",
        "2026-11-01",
        "2026-11-02",
        "2026-11-04",
        "2026-11-06",
        "2026-11-08",
        "2026-11-10",
        "2026-11-12",
        "2026-11-14",
    ],  # BOS: 4 in period 3, 3 in period 4
    6: [
        "2026-11-01",
        "2026-11-03",
        "2026-11-05",
        "2026-11-07",
        "2026-11-09",
        "2026-11-11",
        "2026-11-13",
        "2026-11-15",
    ],  # DAL: 3 / 4
    25: [
        "2026-11-02",
        "2026-11-03",
        "2026-11-05",
        "2026-11-08",
        "2026-11-10",
        "2026-11-12",
    ],  # OKC 4/2
    7: [
        "2026-11-02",
        "2026-11-04",
        "2026-11-05",
        "2026-11-07",
        "2026-11-09",
        "2026-11-11",
    ],  # DEN 4/2
    13: ["2026-11-03", "2026-11-06", "2026-11-10", "2026-11-12", "2026-11-13"],  # LAL 2/3
    14: ["2026-11-02", "2026-11-04", "2026-11-07", "2026-11-09", "2026-11-10"],  # MIA 3/2
    18: [
        "2026-11-03",
        "2026-11-05",
        "2026-11-06",
        "2026-11-08",
        "2026-11-11",
        "2026-11-14",
    ],  # NYK 4/2
    1: [
        "2026-11-03",
        "2026-11-05",
        "2026-11-07",
        "2026-11-09",
        "2026-11-11",
        "2026-11-13",
    ],  # ATL 3/3
    16: [
        "2026-11-02",
        "2026-11-04",
        "2026-11-06",
        "2026-11-08",
        "2026-11-10",
        "2026-11-12",
    ],  # MIN 4/2
    28: ["2026-11-02", "2026-11-05", "2026-11-09"],  # TOR 2/1
    10: ["2026-11-03", "2026-11-06", "2026-11-10"],  # HOU 2/1
    9: ["2026-11-02", "2026-11-04", "2026-11-07", "2026-11-09"],  # GSW 3/1
    12: ["2026-11-03", "2026-11-05", "2026-11-08", "2026-11-10"],  # LAC 3/1
    21: ["2026-11-02", "2026-11-06", "2026-11-11"],  # PHX 2/1
    30: ["2026-11-04", "2026-11-11"],  # CHA 1/1
}


def team_schedule(team_id: int) -> dict:
    abbrev = PRO_ABBREV[team_id]
    opp_id = 30 if team_id != 30 else 1
    events = []
    for i, day in enumerate(GAMES[team_id]):
        home = i % 2 == 0
        events.append(
            {
                "id": f"{team_id}{day.replace('-', '')}",
                "date": tip(day),
                "name": f"{abbrev} vs {PRO_ABBREV[opp_id]}",
                "competitions": [
                    {
                        "id": f"c{team_id}{i}",
                        "date": tip(day),
                        "competitors": [
                            {
                                "id": str(team_id),
                                "homeAway": "home" if home else "away",
                                "team": {"id": str(team_id), "abbreviation": abbrev},
                            },
                            {
                                "id": str(opp_id),
                                "homeAway": "away" if home else "home",
                                "team": {"id": str(opp_id), "abbreviation": PRO_ABBREV[opp_id]},
                            },
                        ],
                    }
                ],
            }
        )
    return {
        "team": {"id": str(team_id), "abbreviation": abbrev, "displayName": abbrev},
        "season": {"year": SEASON, "type": 2},
        "events": events,
    }


scoreboard_response = {
    "leagues": [{"id": "46", "abbreviation": "NBA"}],
    "day": {"date": "2026-11-01"},
    "events": [
        {
            "id": "401800001",
            "date": tip("2026-11-01", 15, 0),
            "name": "Boston Celtics at Dallas Mavericks",
            "competitions": [
                {
                    "id": "401800001",
                    "competitors": [
                        {
                            "id": "6",
                            "homeAway": "home",
                            "team": {
                                "id": "6",
                                "abbreviation": "DAL",
                                "displayName": "Dallas Mavericks",
                            },
                        },
                        {
                            "id": "2",
                            "homeAway": "away",
                            "team": {
                                "id": "2",
                                "abbreviation": "BOS",
                                "displayName": "Boston Celtics",
                            },
                        },
                    ],
                }
            ],
        }
    ],
}


def injury(
    athlete_id: int,
    status: str,
    short: str,
    long_: str,
    body: str,
    detail: str,
    side_: str,
    return_date: str,
    athlete_shape: str = "id",
) -> dict:
    """One injury-report item. athlete_shape mirrors what ESPN has been seen to send:
    "id" (athlete.id present), "link" (live 2026-11-01: names and links only, ID in the
    href), or "name" (names only)."""
    first, last = PLAYERS[athlete_id][0].split(" ", 1)
    athlete: dict = {
        "firstName": first,
        "lastName": last,
        "displayName": PLAYERS[athlete_id][0],
        "shortName": f"{first[0]}. {last}",
    }
    if athlete_shape == "id":
        athlete["id"] = str(athlete_id)
    if athlete_shape in ("id", "link"):
        athlete["links"] = [
            {
                "rel": ["playercard", "desktop", "athlete"],
                "href": f"https://www.espn.com/nba/player/_/id/{athlete_id}/x",
            }
        ]
    return {
        "id": str(900000 + athlete_id),
        "longComment": long_,
        "shortComment": short,
        "status": status,
        "date": "2026-10-30T17:35Z",
        "athlete": athlete,
        "source": {"id": "1", "description": "manual"},
        "type": {
            "id": "1",
            "name": f"INJURY_STATUS_{status.upper().replace('-', '_')}",
            "description": status.lower(),
            "abbreviation": status[0],
        },
        "details": {
            "fantasyStatus": {"description": status.upper(), "abbreviation": status[0]},
            "type": body,
            "location": "Leg",
            **({"detail": detail} if detail else {}),  # live payloads omit this key
            "side": side_,
            "returnDate": return_date,
        },
    }


injuries_response = {
    "season": {"year": SEASON, "type": 2},
    "injuries": [
        {
            "id": "6",
            "displayName": "Dallas Mavericks",
            "injuries": [
                injury(
                    1002,
                    "Out",
                    "Collins (knee) is out through at least Nov. 10.",
                    "Collins sprained his left knee Friday and will be re-evaluated in 10 days.",
                    "Knee",
                    "Sprain",
                    "Left",
                    "2026-11-10",
                ),
            ],
        },
        {
            "id": "18",
            "displayName": "New York Knicks",
            "injuries": [
                injury(
                    2002,
                    "Day-To-Day",
                    "Wing (ankle) is questionable for Monday.",
                    "Wing rolled his right ankle Saturday; he is listed as questionable.",
                    "Ankle",
                    "Sprain",
                    "Right",
                    "",
                    athlete_shape="link",
                ),
            ],
        },
        {
            "id": "12",
            "displayName": "LA Clippers",
            "injuries": [
                injury(
                    7002,
                    "Day-To-Day",
                    "Big (back) is probable for Tuesday.",
                    "Big is dealing with back spasms but is expected to play.",
                    "Back",
                    "",
                    "Not Specified",
                    "",
                    athlete_shape="name",
                ),
            ],
        },
    ],
}


def write(name: str, data: object) -> None:
    (OUT / name).write_text(json.dumps(data, indent=1, sort_keys=False) + "\n")


def main() -> None:
    write("league_mSettings.json", settings)
    write("league_mTeam.json", teams_response)
    write("league_mRoster.json", roster_response)
    write("league_mMatchup.json", matchup_response)
    write("league_kona_free_agents.json", free_agents_response)
    write("league_kona_player_info.json", player_info_response)
    write("league_mTransactions.json", transactions_response)
    write("players_wl.json", players_wl_response)
    write("nba_scoreboard.json", scoreboard_response)
    write("nba_injuries.json", injuries_response)
    for team_id in GAMES:
        write(f"nba_team_schedule_{team_id}.json", team_schedule(team_id))
    print(f"wrote fixtures to {OUT}")


if __name__ == "__main__":
    main()

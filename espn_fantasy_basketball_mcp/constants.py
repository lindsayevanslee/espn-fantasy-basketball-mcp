"""ESPN Fantasy Basketball identifiers and the human-readable names for them."""

from __future__ import annotations

# ESPN stat IDs -> category names. 0=PTS, 1=BLK, 2=STL, 3=AST, 6=REB, 11=TO, 13-16 FGM/FGA/FTM/FTA,
# 17=3PM, 19=FG%, 20=FT%, 40=MIN, 42=GP.
STAT_ID_TO_CATEGORY: dict[str, str] = {
    "0": "points",  # Points
    "1": "blocks",  # Blocks
    "2": "steals",  # Steals
    "3": "assists",  # Assists
    "4": "offensiveRebounds",  # Offensive Rebounds (less common in matchups)
    "6": "rebounds",  # Rebounds (total rebounds)
    "11": "turnovers",  # Turnovers
    "13": "fieldGoalsMade",  # Field Goals Made
    "14": "fieldGoalsAttempted",  # Field Goals Attempted
    "15": "freeThrowsMade",  # Free Throws Made
    "16": "freeThrowsAttempted",  # Free Throws Attempted
    "17": "threePointMade",  # 3PM
    "19": "fieldGoalPercentage",  # FG%
    "20": "freeThrowPercentage",  # FT%
    "40": "minutes",  # Minutes
    "gamesPlayed": "gamesPlayed",
}


# Lineup slot IDs. Observed live: 0-6, 11, 12, 13. Slots 7-10 are inferred from the order of
# ESPN's roster-settings table (SG/SF, G/F, PF/C, F/C sit between F and UTIL) and match the
# espn-api library's table; no league seen so far uses them, so they are unverified by data.
LINEUP_SLOT_NAMES: dict[int, str] = {
    0: "PG",  # Point Guard
    1: "SG",  # Shooting Guard
    2: "SF",  # Small Forward
    3: "PF",  # Power Forward
    4: "C",  # Center
    5: "G",  # Guard (PG or SG)
    6: "F",  # Forward (SF or PF)
    7: "SG/SF",  # Swingman
    8: "G/F",  # Guard/Forward
    9: "PF/C",  # Big
    10: "F/C",  # Forward/Center
    11: "UTIL",  # Utility
    12: "BENCH",  # Bench
    13: "IR",  # Injured Reserve
}

SLOT_BENCH = 12
SLOT_IR = 13

# defaultPositionId is 1-based (1=PG ... 5=C); eligibleSlots use the 0-based slot IDs above.
POSITION_NAMES: dict[int, str] = {
    1: "PG",  # Point Guard
    2: "SG",  # Shooting Guard
    3: "SF",  # Small Forward
    4: "PF",  # Power Forward
    5: "C",  # Center
    6: "G",  # Guard (PG or SG)
    7: "F",  # Forward (SF or PF)
}


# rosterSettings.positionLimits is keyed by defaultPositionId (1=PG ... 5=C). Recorded live
# (2026-11-01) from a league whose UI shows "No Limit" for PG-PF and a maximum of 4 centers:
# {"0": 0, "1": -1, "2": -1, "3": -1, "4": -1, "5": 4}. Key 0 matches nothing in the UI and is
# left unnamed (reported as POS_0). An earlier note claiming keys 2-6 was wrong.
POSITION_LIMIT_NAMES: dict[int, str] = {1: "PG", 2: "SG", 3: "SF", 4: "PF", 5: "C"}

# ESPN Fantasy proTeamId -> canonical abbreviation. The ID -> team identity was validated against
# the ESPN Fantasy UI. Abbreviations are the canonical codes normalize_nba_abbrev produces, so
# they can be used directly as keys into the today's-games cache. 0 means unsigned ("FA").
PRO_TEAM_ABBREVS: dict[int, str] = {
    1: "ATL",  # Atlanta Hawks
    2: "BOS",  # Boston Celtics
    3: "NOP",  # New Orleans Pelicans
    4: "CHI",  # Chicago Bulls
    5: "CLE",  # Cleveland Cavaliers
    6: "DAL",  # Dallas Mavericks
    7: "DEN",  # Denver Nuggets
    8: "DET",  # Detroit Pistons
    9: "GSW",  # Golden State Warriors
    10: "HOU",  # Houston Rockets
    11: "IND",  # Indiana Pacers
    12: "LAC",  # LA Clippers
    13: "LAL",  # Los Angeles Lakers
    14: "MIA",  # Miami Heat
    15: "MIL",  # Milwaukee Bucks
    16: "MIN",  # Minnesota Timberwolves
    17: "BKN",  # Brooklyn Nets
    18: "NYK",  # New York Knicks
    19: "ORL",  # Orlando Magic
    20: "PHI",  # Philadelphia 76ers
    21: "PHX",  # Phoenix Suns
    22: "POR",  # Portland Trail Blazers
    23: "SAC",  # Sacramento Kings
    24: "SAS",  # San Antonio Spurs
    25: "OKC",  # Oklahoma City Thunder
    26: "UTA",  # Utah Jazz
    27: "WAS",  # Washington Wizards
    28: "TOR",  # Toronto Raptors
    29: "MEM",  # Memphis Grizzlies
    30: "CHA",  # Charlotte Hornets
}


# ESPN's site API (scoreboard, team schedules) and some fantasy payloads use short or
# non-standard codes. Everything the client emits or uses as a lookup key goes through
# normalize_nba_abbrev so that today's-game lookups, schedule lookups and PRO_TEAM_ABBREVS agree.
ABBREV_ALIASES: dict[str, str] = {
    "GS": "GSW",  # Golden State Warriors
    "NO": "NOP",  # New Orleans Pelicans
    "NY": "NYK",  # New York Knicks
    "SA": "SAS",  # San Antonio Spurs
    "UTAH": "UTA",  # Utah Jazz
    "WSH": "WAS",  # Washington Wizards
    "PHO": "PHX",  # Phoenix Suns
    "BRK": "BKN",  # Brooklyn Nets
    "CHO": "CHA",  # Charlotte Hornets
}


def normalize_nba_abbrev(nba_abbrev: str) -> str:
    """Normalize any NBA team abbreviation variant to the canonical 3-letter code.

    Unknown codes are returned upper-cased and unchanged.
    """
    code = (nba_abbrev or "").strip().upper()
    return ABBREV_ALIASES.get(code, code)


# Share of remaining games a player is expected to play, by ESPN injury status.
AVAILABILITY_FACTORS: dict[str, float] = {
    "ACTIVE": 1.0,
    "NORMAL": 1.0,
    "DAY_TO_DAY": 1.0,
    "QUESTIONABLE": 1.0,
    "PROBABLE": 1.0,
    "DOUBTFUL": 0.5,
    "OUT": 0.0,
    "SUSPENSION": 0.0,
    "SUSPENDED": 0.0,
}


# (helps_at, hurts_below) on the 0-100 scale, roughly league-average bands.
SHOOTING_THRESHOLDS: dict[str, tuple[float, float]] = {
    "fieldGoalPercentage": (48.0, 43.0),
    "freeThrowPercentage": (80.0, 70.0),
}


# Per-game production at which a player is said to help a counting category, and the share
# of that value below which he hurts it (hurts_below = helps_at * HURTS_RATIO). These are
# rough "better than an average fantasy starter" bands, not league data; analyze_matchup puts
# the player's actual per-game number next to every claim so the reader can judge.
CATEGORY_HELP_THRESHOLDS: dict[str, float] = {
    "points": 18.0,
    "rebounds": 7.0,
    "assists": 5.0,
    "steals": 1.2,
    "blocks": 1.0,
    "threePointMade": 2.0,
}
HURTS_RATIO = 0.6
# Turnovers are reversed: a low-turnover player helps, a high-turnover one hurts.
TURNOVER_HELPS_BELOW = 2.0
TURNOVER_HURTS_ABOVE = 3.5


# How close a category must be, as a projected margin, to be flagged isClose. For counting
# categories this is roughly what two strong player-games swing, so a start/sit decision can
# still change the result. Anything not listed falls back to 5% of the total (minimum 2).
CLOSE_MARGINS: dict[str, float] = {
    "points": 20.0,
    "rebounds": 8.0,
    "assists": 6.0,
    "steals": 2.0,
    "blocks": 2.0,
    "threePointMade": 3.0,
    "turnovers": 3.0,
}
# A percentage category is close when the lead is worth no more than this many made shots over
# the week's projected attempts (margin * attempts <= makes). With ~350 FGA a week, 4 makes is
# a 0.011 lead; the old flat 0.002 flagged almost nothing as close.
CLOSE_PERCENTAGE_MAKES = 4.0
# Fallback when attempts are unknown.
CLOSE_PERCENTAGE_FALLBACK: dict[str, float] = {
    "fieldGoalPercentage": 0.010,
    "freeThrowPercentage": 0.015,
}


# ESPN rosterSettings.lineupLocktimeType codes in plain English. Only the first two have been
# seen in a live league; a code not listed here is reported as not recognised, and the per-slot
# lineupLocked flags on get_team_roster remain authoritative for what is actually editable.
LINEUP_LOCK_DESCRIPTIONS: dict[str, str] = {
    "INDIVIDUAL_GAME": (
        "Daily lineups: each player's slot locks at that player's game time and the lineup can "
        "be changed every day for players who have not yet played."
    ),
    "FIRSTGAME_WEEKLY": (
        "Weekly lineups: every slot locks at the first NBA game of the matchup period and "
        "stays locked for the week."
    ),
}


# Ordering of injury statuses from most to least available, used to spot a fantasy status that
# disagrees with ESPN's NBA injury report (e.g. OUT vs "probable").
INJURY_SEVERITY: dict[str, int] = {
    "ACTIVE": 0,
    "NORMAL": 0,
    "PROBABLE": 0,
    "DAY_TO_DAY": 1,
    "DTD": 1,
    "QUESTIONABLE": 1,
    "DOUBTFUL": 2,
    "OUT": 3,
    "SUSPENSION": 3,
    "SUSPENDED": 3,
    "IR": 3,
}

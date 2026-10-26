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


# rosterSettings.positionLimits is keyed one higher than defaultPositionId. Observed live: a league
# whose UI shows "No Limit" for PG-PF and a maximum of 4 centers returned {1: 0, 2: -1, 3: -1,
# 4: -1, 5: -1, 6: 4}. Key 1 matches nothing in the UI and is left unnamed.
POSITION_LIMIT_NAMES: dict[int, str] = {2: "PG", 3: "SG", 4: "SF", 5: "PF", 6: "C"}

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

"""Calendar math for ESPN scoring periods, matchup periods and remaining games."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from .models import RosterScheduleSummary


def date_for_scoring_period(scoring_period: int, anchor_period: int, anchor_date: date) -> date:
    """ESPN scoring periods are consecutive calendar days, so one known (period, date) pair
    places every other period."""
    return anchor_date + timedelta(days=scoring_period - anchor_period)


def matchup_period_window(
    matchup_period: int,
    season_start: date,
    matchup_periods: dict[str, list[int]],
    week_start_day: int = 0,
) -> tuple[date, date] | None:
    """Calendar window of a matchup period given opening night and ESPN's period mapping.

    ESPN's scheduleSettings.matchupPeriods is week-indexed: each entry lists the week
    number(s) a matchup period covers, so a normal period has one element and a two-week
    All-Star period has two. (Verified live: period 1 was [1] while the daily scoring
    period counter read 6.) Period 1 starts on opening night and ends at the end of that
    calendar week; every later period is whole weeks from the next day.

    Some leagues may instead list one scoring period per day; if any entry is longer than
    four, the lists are treated as daily and the window is their min/max day.
    """
    if matchup_period < 1:
        return None
    if matchup_periods and str(matchup_period) not in matchup_periods:
        return None  # beyond the league's schedule

    daily = any(len(v) > 4 for v in matchup_periods.values())
    if daily:
        days = matchup_periods[str(matchup_period)]
        return (
            season_start + timedelta(days=min(days) - 1),
            season_start + timedelta(days=max(days) - 1),
        )

    def weeks_in(period: int) -> int:
        entry = matchup_periods.get(str(period))
        return max(1, len(entry)) if entry else 1

    # ESPN weeks end the day before week_start_day (Sunday for Monday starts).
    days_to_week_end = (week_start_day - 1 - season_start.weekday()) % 7
    start = season_start
    end = season_start + timedelta(days=days_to_week_end, weeks=weeks_in(1) - 1)
    for period in range(2, matchup_period + 1):
        start = end + timedelta(days=1)
        end = start + timedelta(days=7 * weeks_in(period) - 1)
    return start, end


def games_remaining_by_player(
    schedule: RosterScheduleSummary, now: datetime, window_end: date | None = None
) -> dict[int, int]:
    """Count each player's games that have not started yet, within the matchup window.

    Games already played (or in progress) are reflected in the matchup's current category
    scores, so projecting them again would double count. Games after ``window_end`` belong
    to a later matchup period and are excluded; the schedule summaries deliberately fetch an
    extra week so ``gamesNextWeek`` can be reported.

    A game counts as remaining when its tip-off (``datetimeISO``) is later than ``now``.
    When only the date is known, a game dated today or later counts.

    Args:
        schedule: Roster schedule summary for one fantasy team
        now: Timezone-aware current time
        window_end: Last date (inclusive) of the matchup period, or None for no bound

    Returns:
        Mapping of playerId -> number of remaining games
    """
    today = now.date()
    remaining: dict[int, int] = {}
    for player_schedule in schedule.playerSchedules:
        count = 0
        for game in player_schedule.games:
            try:
                game_day = date.fromisoformat(game.date)
            except ValueError:
                continue
            if window_end is not None and game_day > window_end:
                continue
            tip_off: datetime | None = None
            if game.datetimeISO:
                try:
                    tip_off = datetime.fromisoformat(game.datetimeISO)
                except ValueError:
                    tip_off = None
            if tip_off is not None and tip_off.tzinfo is not None and now.tzinfo is not None:
                if tip_off > now:
                    count += 1
            elif game_day >= today:
                count += 1
        remaining[player_schedule.playerId] = count
    return remaining


def week_boundaries(date: str, week_start_day: int = 0) -> tuple[str, str]:
    """Get week boundaries for a given date based on week start day.

    Args:
        date: Date in YYYY-MM-DD format
        week_start_day: Weekday number (0=Monday, 6=Sunday)

    Returns:
        Tuple of (week_start_date, week_end_date) in YYYY-MM-DD format
    """
    from datetime import datetime, timedelta

    dt = datetime.fromisoformat(date)
    # Get the start day of the week
    days_since_start = (dt.weekday() - week_start_day) % 7
    week_start = dt - timedelta(days=days_since_start)
    week_end = week_start + timedelta(days=6)

    return week_start.strftime("%Y-%m-%d"), week_end.strftime("%Y-%m-%d")

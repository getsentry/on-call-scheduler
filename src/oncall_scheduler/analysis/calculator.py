"""Utilities for calculating on-call days from schedule entries."""

import calendar
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Set

import pytz

from oncall_scheduler.models import ScheduleEntry

logger = logging.getLogger(__name__)


def get_dates_in_range(
    start: datetime,
    end: datetime,
    month_start: datetime,
    month_end: datetime,
    timezone_str: str = "UTC",
    workday_end_hour: int = 17,
) -> Set[date]:
    """Extract dates where on-call coverage extends past workday end hour.

    Only counts days where the user has on-call coverage that extends beyond the
    standard workday end hour (e.g., 5 PM) in the specified timezone.

    Args:
        start: Start datetime of the on-call shift
        end: End datetime of the on-call shift
        month_start: Start datetime of the target month
        month_end: End datetime of the target month
        timezone_str: Timezone string for the user (e.g., "America/New_York")
        workday_end_hour: Hour (0-23) when standard workday ends (default: 17 for 5 PM)

    Returns:
        Set of date objects representing days with after-hours on-call coverage
    """
    # Convert to the user's timezone
    tz = pytz.timezone(timezone_str)

    # Ensure all datetimes are timezone-aware
    if start.tzinfo is None:
        start = pytz.utc.localize(start)
    if end.tzinfo is None:
        end = pytz.utc.localize(end)
    if month_start.tzinfo is None:
        month_start = pytz.utc.localize(month_start)
    if month_end.tzinfo is None:
        month_end = pytz.utc.localize(month_end)

    # Convert to user's timezone
    start = start.astimezone(tz)
    end = end.astimezone(tz)
    month_start = month_start.astimezone(tz)
    month_end = month_end.astimezone(tz)

    # Clamp the range to the month boundaries
    actual_start = max(start, month_start)
    actual_end = min(end, month_end)

    # If the shift doesn't overlap with the month, return empty set
    if actual_start >= actual_end:
        return set()

    # Generate dates where coverage extends past workday end hour
    dates = set()
    current_date = actual_start.date()
    end_date = actual_end.date()

    while current_date <= end_date:
        # Create datetime for workday end on this date in user's timezone
        workday_end = tz.localize(
            datetime(current_date.year, current_date.month, current_date.day, workday_end_hour, 0, 0)
        )

        # Check if on-call coverage extends past workday end on this date
        # Coverage extends past workday end if:
        # 1. The shift ends after workday end on this date, AND
        # 2. The shift is active at or after workday end on this date
        shift_active_on_date = (
            start <= workday_end < end  # Shift covers the workday end time
            or (start.date() == current_date and start.hour >= workday_end_hour)  # Shift starts after workday end
            or (end.date() == current_date and end.hour > workday_end_hour)  # Shift ends after workday end
        )

        # More precise check: does the shift extend past workday_end_hour on this specific date?
        day_start = tz.localize(datetime(current_date.year, current_date.month, current_date.day, 0, 0, 0))
        day_end = tz.localize(datetime(current_date.year, current_date.month, current_date.day, 23, 59, 59))

        # Intersection of shift with this day
        shift_start_on_day = max(start, day_start)
        shift_end_on_day = min(end, day_end)

        # Only count if shift extends past workday end hour on this specific day
        if shift_start_on_day <= shift_end_on_day and shift_end_on_day > workday_end:
            dates.add(current_date)

        current_date += timedelta(days=1)

    return dates


def calculate_oncall_days(
    entries: List[ScheduleEntry], month: int, year: int, workday_end_hour: int = 17
) -> Dict[str, Set[date]]:
    """Calculate on-call days per user for a specific month.

    Only counts days where the user has on-call coverage extending past
    the workday end hour in their local timezone.

    Args:
        entries: List of ScheduleEntry objects
        month: Target month (1-12)
        year: Target year
        workday_end_hour: Hour (0-23) when standard workday ends (default: 17 for 5 PM)

    Returns:
        Dictionary mapping user_id to a set of dates they had after-hours on-call coverage
    """
    # Calculate month boundaries
    month_start = datetime(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    month_end = datetime(year, month, last_day, 23, 59, 59)

    # Make month boundaries timezone-aware (UTC)
    month_start = pytz.utc.localize(month_start)
    month_end = pytz.utc.localize(month_end)

    user_days = defaultdict(set)

    for entry in entries:
        # Use the user's timezone for calculations
        timezone_str = entry.user.timezone

        # Extract dates where coverage extends past workday end hour
        dates = get_dates_in_range(
            entry.start, entry.end, month_start, month_end, timezone_str, workday_end_hour
        )

        # Add to user's set of on-call days
        user_days[entry.user.id].update(dates)

        logger.debug(
            f"User {entry.user.name} had after-hours on-call for {len(dates)} days "
            f"on schedule {entry.schedule.name} (timezone: {timezone_str})"
        )

    logger.info(f"Calculated on-call days for {len(user_days)} users in {month}/{year}")
    return dict(user_days)


def get_user_schedule_days(
    user_id: str, entries: List[ScheduleEntry], workday_end_hour: int = 17
) -> List[date]:
    """Get all after-hours on-call dates for a specific user, sorted chronologically.

    Only includes dates where the user had on-call coverage extending past
    the workday end hour.

    Args:
        user_id: The PagerDuty user ID
        entries: List of all ScheduleEntry objects
        workday_end_hour: Hour (0-23) when standard workday ends (default: 17 for 5 PM)

    Returns:
        Sorted list of dates the user had after-hours on-call coverage
    """
    dates = set()

    for entry in entries:
        if entry.user.id == user_id:
            # Extract all dates from this entry using user's timezone
            entry_dates = get_dates_in_range(
                entry.start,
                entry.end,
                entry.start,  # No month boundary filtering
                entry.end,
                entry.user.timezone,
                workday_end_hour,
            )
            dates.update(entry_dates)

    return sorted(dates)


def count_days_in_month(
    entries: List[ScheduleEntry], month: int, year: int, workday_end_hour: int = 17
) -> int:
    """Count total after-hours on-call days across all users in a month.

    Args:
        entries: List of ScheduleEntry objects
        month: Target month (1-12)
        year: Target year
        workday_end_hour: Hour (0-23) when standard workday ends (default: 17 for 5 PM)

    Returns:
        Total count of after-hours on-call days (sum across all users)
    """
    user_days = calculate_oncall_days(entries, month, year, workday_end_hour)
    return sum(len(dates) for dates in user_days.values())

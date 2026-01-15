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
) -> Set[date]:
    """Extract all unique dates in a time range that fall within a month boundary.

    Args:
        start: Start datetime of the on-call shift
        end: End datetime of the on-call shift
        month_start: Start datetime of the target month
        month_end: End datetime of the target month
        timezone_str: Timezone string for the schedule (e.g., "America/New_York")

    Returns:
        Set of date objects representing days the user was on-call
    """
    # Convert to the schedule's timezone
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

    # Convert to schedule timezone
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

    # Generate all dates in the range
    dates = set()
    current = actual_start.date()
    end_date = actual_end.date()

    while current <= end_date:
        dates.add(current)
        current += timedelta(days=1)

    return dates


def calculate_oncall_days(
    entries: List[ScheduleEntry], month: int, year: int
) -> Dict[str, Set[date]]:
    """Calculate on-call days per user for a specific month.

    Args:
        entries: List of ScheduleEntry objects
        month: Target month (1-12)
        year: Target year

    Returns:
        Dictionary mapping user_id to a set of dates they were on-call
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
        # Get the timezone from the schedule
        timezone_str = entry.schedule.timezone

        # Extract dates for this entry
        dates = get_dates_in_range(
            entry.start, entry.end, month_start, month_end, timezone_str
        )

        # Add to user's set of on-call days
        user_days[entry.user.id].update(dates)

        logger.debug(
            f"User {entry.user.name} was on-call for {len(dates)} days "
            f"on schedule {entry.schedule.name}"
        )

    logger.info(f"Calculated on-call days for {len(user_days)} users in {month}/{year}")
    return dict(user_days)


def get_user_schedule_days(user_id: str, entries: List[ScheduleEntry]) -> List[date]:
    """Get all on-call dates for a specific user, sorted chronologically.

    Args:
        user_id: The PagerDuty user ID
        entries: List of all ScheduleEntry objects

    Returns:
        Sorted list of dates the user was on-call
    """
    dates = set()

    for entry in entries:
        if entry.user.id == user_id:
            # Extract all dates from this entry
            entry_dates = get_dates_in_range(
                entry.start,
                entry.end,
                entry.start,  # No month boundary filtering
                entry.end,
                entry.schedule.timezone,
            )
            dates.update(entry_dates)

    return sorted(dates)


def count_days_in_month(entries: List[ScheduleEntry], month: int, year: int) -> int:
    """Count total on-call days across all users in a month.

    Args:
        entries: List of ScheduleEntry objects
        month: Target month (1-12)
        year: Target year

    Returns:
        Total count of on-call days (sum across all users)
    """
    user_days = calculate_oncall_days(entries, month, year)
    return sum(len(dates) for dates in user_days.values())

"""Main orchestrator for on-call schedule analysis."""

import calendar
import logging
from collections import defaultdict
from datetime import datetime

import pytz

from oncall_scheduler.analysis.calculator import get_dates_in_range
from oncall_scheduler.api.client import PagerDutyClient
from oncall_scheduler.models import (
    AnalysisResult,
    HolidayConflict,
    HolidayEntry,
    MultiMonthAnalysisResult,
    OnCallReport,
    PTOConflict,
    PTOEntry,
    User,
)

logger = logging.getLogger(__name__)


def _find_pto_conflicts(
    user_schedule_days: dict[str, dict[str, set]],
    users: dict[str, User],
    pto_by_email: dict[str, list[PTOEntry]],
) -> list[PTOConflict]:
    """Find conflicts between on-call schedules and PTO.

    Args:
        user_schedule_days: Dictionary mapping user IDs to schedule names to sets of on-call dates
        users: Dictionary mapping user IDs to User objects
        pto_by_email: Dictionary mapping user emails to lists of PTO entries

    Returns:
        List of PTOConflict objects for users with conflicts (one per schedule)
    """
    conflicts = []

    for user_id, schedule_dates in user_schedule_days.items():
        user = users[user_id]
        user_pto = pto_by_email.get(user.email, [])

        if not user_pto:
            continue

        # Check each schedule separately
        for schedule_name, dates in schedule_dates.items():
            # Find dates that conflict with PTO for this schedule
            conflicting_dates = []
            for d in dates:
                for pto_entry in user_pto:
                    if pto_entry.contains_date(d):
                        conflicting_dates.append(d)
                        break  # Don't add same date multiple times

            if conflicting_dates:
                conflict = PTOConflict(
                    user=user,
                    schedule_name=schedule_name,
                    conflicting_dates=sorted(conflicting_dates),
                )
                conflicts.append(conflict)
                logger.info(
                    f"PTO CONFLICT: {user.name} on {schedule_name} has {len(conflicting_dates)} "
                    f"on-call days during PTO: {[d.isoformat() for d in conflicting_dates]}"
                )

    # Sort by number of conflicts (descending)
    conflicts.sort(key=lambda c: len(c.conflicting_dates), reverse=True)
    return conflicts


def _find_holiday_conflicts(
    user_schedule_days: dict[str, dict[str, set]],
    users: dict[str, User],
    holidays_by_timezone: dict[str, list[HolidayEntry]],
<<<<<<< HEAD
    included_schedules: list[str] | None = None,
    excluded_schedules: list[str] | None = None,
) -> list[HolidayConflict]:
    """Find conflicts between on-call schedules and holidays.

    Args:
        user_schedule_days: Dictionary mapping user IDs to schedule names to sets of on-call dates
        users: Dictionary mapping user IDs to User objects
        holidays_by_timezone: Dictionary mapping timezones to lists of HolidayEntry objects
        included_schedules: Optional list of schedule names to check. If empty/None, all schedules are checked.
        excluded_schedules: Optional list of schedule names to exclude from checking.

    Returns:
        List of HolidayConflict objects for users with conflicts
    """
    if included_schedules is None:
        included_schedules = []
    if excluded_schedules is None:
        excluded_schedules = []

    conflicts = []

    for user_id, schedule_dates in user_schedule_days.items():
        user = users[user_id]
        user_holidays = holidays_by_timezone.get(user.timezone, [])

        if not user_holidays:
            continue

        # Check each schedule separately
        for schedule_name, dates in schedule_dates.items():
            # Skip schedules not in the inclusion list (if specified)
            if included_schedules and schedule_name not in included_schedules:
                continue
            # Skip schedules in the exclusion list
            if schedule_name in excluded_schedules:
                continue
||||||| b6f0624
=======
) -> list[HolidayConflict]:
    """Find conflicts between on-call schedules and holidays.

    Args:
        user_schedule_days: Dictionary mapping user IDs to schedule names to sets of on-call dates
        users: Dictionary mapping user IDs to User objects
        holidays_by_timezone: Dictionary mapping timezones to lists of HolidayEntry objects

    Returns:
        List of HolidayConflict objects for users with conflicts
    """
    conflicts = []

    for user_id, schedule_dates in user_schedule_days.items():
        user = users[user_id]
        user_holidays = holidays_by_timezone.get(user.timezone, [])

        if not user_holidays:
            continue

        # Check each schedule separately
        for schedule_name, dates in schedule_dates.items():
>>>>>>> main
            # Find dates that conflict with holidays for this schedule
            for holiday in user_holidays:
                if holiday.date in dates:
                    conflict = HolidayConflict(
                        user=user,
                        schedule_name=schedule_name,
                        holiday_name=holiday.name,
                        conflicting_date=holiday.date,
                    )
                    conflicts.append(conflict)
                    logger.info(
                        f"HOLIDAY CONFLICT: {user.name} on {schedule_name} is on-call "
                        f"during {holiday.name} ({holiday.date.isoformat()})"
                    )

    # Sort by date
    conflicts.sort(key=lambda c: (c.conflicting_date, c.user.name))
    return conflicts


def analyze_schedules(
    team_ids: list[str],
    month: int,
    year: int,
    max_days: int,
    client: PagerDutyClient,
    workday_end_hour: int = 17,
    user_timezones: dict[str, str] | None = None,
    timezones_of_concern: list[str] | None = None,
    excluded_users: list[str] | None = None,
    excluded_schedules: list[str] | None = None,
    pto_by_email: dict[str, list[PTOEntry]] | None = None,
    holidays_by_timezone: dict[str, list[HolidayEntry]] | None = None,
<<<<<<< HEAD
    included_schedules_for_holidays: list[str] | None = None,
    excluded_schedules_for_holidays: list[str] | None = None,
||||||| b6f0624
    user_timezones: Optional[Dict[str, str]] = None,
    timezones_of_concern: Optional[List[str]] = None,
    excluded_users: Optional[List[str]] = None,
    excluded_schedules: Optional[List[str]] = None,
    pto_by_email: Optional[Dict[str, List[PTOEntry]]] = None,
=======
>>>>>>> main
) -> AnalysisResult:
    """Analyze on-call schedules for teams and identify users over the limit.

    Only counts days where users have on-call coverage extending past the
    workday end hour in their local timezone.

    Args:
        team_ids: List of PagerDuty team IDs to analyze
        month: Target month (1-12)
        year: Target year
        max_days: Maximum allowed after-hours on-call days per month
        client: PagerDutyClient instance for API calls
        workday_end_hour: Hour (0-23) when standard workday ends (default: 17 for 5 PM)
        user_timezones: Optional mapping of user emails to timezone strings
        timezones_of_concern: Optional list of timezones to include (empty list means all timezones included)
        excluded_users: Optional list of user emails to exclude from over-limit reporting
        excluded_schedules: Optional list of schedule IDs or names to exclude from analysis
        pto_by_email: Optional dict mapping user emails to lists of PTO entries
        holidays_by_timezone: Optional dict mapping timezones to lists of HolidayEntry objects
<<<<<<< HEAD
        included_schedules_for_holidays: Optional list of schedule names to check for holiday conflicts.
            If empty/None, all schedules are checked.
        excluded_schedules_for_holidays: Optional list of schedule names to exclude from holiday conflict checking.
||||||| b6f0624
=======
>>>>>>> main

    Returns:
        AnalysisResult containing categorized user reports

    Raises:
        AuthenticationError: If API authentication fails
        PagerDutyAPIError: For other API errors
    """
    if user_timezones is None:
        user_timezones = {}
    if timezones_of_concern is None:
        timezones_of_concern = []
    if excluded_users is None:
        excluded_users = []
    if excluded_schedules is None:
        excluded_schedules = []
    if pto_by_email is None:
        pto_by_email = {}
    if holidays_by_timezone is None:
        holidays_by_timezone = {}
<<<<<<< HEAD
    if included_schedules_for_holidays is None:
        included_schedules_for_holidays = []
    if excluded_schedules_for_holidays is None:
        excluded_schedules_for_holidays = []
||||||| b6f0624
=======
>>>>>>> main

    logger.info(f"Starting analysis for {len(team_ids)} teams in {month}/{year}")
    logger.info(f"Maximum days limit: {max_days}")
    logger.info(f"Workday end hour: {workday_end_hour}:00")
    if user_timezones:
        logger.info(f"User timezone overrides configured for {len(user_timezones)} users")
    if timezones_of_concern:
        logger.info(f"Filtering to timezones: {', '.join(timezones_of_concern)}")
    if excluded_users:
        logger.info(f"Excluding users: {', '.join(excluded_users)}")
    if excluded_schedules:
        logger.info(f"Excluding schedules: {', '.join(excluded_schedules)}")
    if pto_by_email:
        total_pto_periods = sum(len(periods) for periods in pto_by_email.values())
        logger.info(f"Checking PTO for {len(pto_by_email)} users ({total_pto_periods} periods)")
    if holidays_by_timezone:
        total_holidays = sum(len(holidays) for holidays in holidays_by_timezone.values())
        logger.info(f"Checking holidays for {len(holidays_by_timezone)} timezones ({total_holidays} holidays)")
<<<<<<< HEAD
    if included_schedules_for_holidays:
        logger.info(f"Holiday conflict schedules limited to: {', '.join(included_schedules_for_holidays)}")
    if excluded_schedules_for_holidays:
        logger.info(f"Holiday conflict schedules excluded: {', '.join(excluded_schedules_for_holidays)}")
||||||| b6f0624
=======
>>>>>>> main

    # Step 1: Fetch schedules for the specified teams
    all_schedules = client.get_schedules_by_team(team_ids)

    if not all_schedules:
        logger.warning(f"No schedules found for teams: {team_ids}")
        return AnalysisResult(month=month, year=year, max_days=max_days)

    # Filter out excluded schedules (by ID or name)
    schedules = []
    for schedule in all_schedules:
        if schedule.id in excluded_schedules or schedule.name in excluded_schedules:
            logger.info(f"EXCLUDED SCHEDULE: {schedule.name} ({schedule.id})")
        else:
            schedules.append(schedule)

    if not schedules:
        logger.warning("No schedules remaining after exclusions")
        return AnalysisResult(month=month, year=year, max_days=max_days)

    schedule_ids = [schedule.id for schedule in schedules]
    logger.info(f"Analyzing {len(schedules)} schedules: {', '.join(s.name for s in schedules)}")

    # Step 2: Calculate date range for the month
    month_start = datetime(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    month_end = datetime(year, month, last_day, 23, 59, 59)

    # Make timezone-aware (UTC)
    month_start = pytz.utc.localize(month_start)
    month_end = pytz.utc.localize(month_end)

    # Step 3: Fetch on-call entries for the month with user timezone configuration
    entries = client.get_oncalls(schedule_ids, month_start, month_end, user_timezones)

    if not entries:
        logger.warning("No on-call entries found for the specified period")
        return AnalysisResult(month=month, year=year, max_days=max_days)

    # Step 4: Build mappings of user_id to User object and schedule-specific days
    users: dict[str, User] = {}
    user_schedules: dict[str, list[str]] = defaultdict(list)
    user_schedule_days: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))

    for entry in entries:
        if entry.user.id not in users:
            users[entry.user.id] = entry.user

        if entry.schedule.name not in user_schedules[entry.user.id]:
            user_schedules[entry.user.id].append(entry.schedule.name)

        # Track dates per schedule (used for PTO conflict detection and aggregated for user totals)
        entry_dates = get_dates_in_range(
            entry.start, entry.end, month_start, month_end, entry.user.timezone, workday_end_hour
        )
        user_schedule_days[entry.user.id][entry.schedule.name].update(entry_dates)

    # Step 5: Derive per-user day totals by merging per-schedule sets
    user_days: dict[str, set] = {
        user_id: set().union(*schedule_days.values())
        for user_id, schedule_days in user_schedule_days.items()
    }

    # Step 5b: Filter user_days based on timezone and excluded_users
    filtered_user_days: dict[str, set] = {}
    filtered_user_schedule_days: dict[str, dict[str, set]] = {}
    for user_id, dates in user_days.items():
        user = users[user_id]

        # Filter by timezone if timezones_of_concern is specified
        if timezones_of_concern and user.timezone not in timezones_of_concern:
            logger.debug(f"FILTERED: {user.name} - timezone {user.timezone} not in timezones of concern")
            continue

        # Filter by excluded users if specified
        if excluded_users and user.email in excluded_users:
            logger.debug(f"EXCLUDED: {user.name} ({user.email}) - user is in excluded list")
            continue

        filtered_user_days[user_id] = dates
        filtered_user_schedule_days[user_id] = dict(user_schedule_days[user_id])

    # Step 5c: Check for PTO conflicts (using filtered data)
    pto_conflicts = []
    if pto_by_email:
        pto_conflicts = _find_pto_conflicts(filtered_user_schedule_days, users, pto_by_email)

    # Step 5d: Check for holiday conflicts (using filtered data)
    holiday_conflicts = []
    if holidays_by_timezone:
<<<<<<< HEAD
        holiday_conflicts = _find_holiday_conflicts(
            filtered_user_schedule_days,
            users,
            holidays_by_timezone,
            included_schedules_for_holidays,
            excluded_schedules_for_holidays,
        )
||||||| b6f0624
=======
        holiday_conflicts = _find_holiday_conflicts(filtered_user_schedule_days, users, holidays_by_timezone)
>>>>>>> main

    # Step 6: Categorize users by their on-call days
    over_limit = []
    at_limit = []
    under_limit = []

    for user_id, dates in filtered_user_days.items():
        day_count = len(dates)
        user = users[user_id]

        schedule_names = ", ".join(user_schedules[user_id])

        # Get sorted list of dates for reporting
        sorted_dates = sorted(dates)

        report = OnCallReport(
            user=user,
            schedule_name=schedule_names,
            total_days=day_count,
            scheduled_dates=sorted_dates,
        )

        if day_count > max_days:
            over_limit.append(report)
            logger.info(f"OVER: {user.name} - {day_count} days (limit: {max_days})")
        elif day_count == max_days:
            at_limit.append(report)
            logger.info(f"AT: {user.name} - {day_count} days (limit: {max_days})")
        else:
            under_limit.append(report)
            logger.debug(f"UNDER: {user.name} - {day_count} days (limit: {max_days})")

    # Sort reports by day count (descending)
    over_limit.sort(key=lambda r: r.total_days, reverse=True)
    at_limit.sort(key=lambda r: r.total_days, reverse=True)
    under_limit.sort(key=lambda r: r.total_days, reverse=True)

    result = AnalysisResult(
        month=month,
        year=year,
        max_days=max_days,
        over_limit=over_limit,
        at_limit=at_limit,
        under_limit=under_limit,
        pto_conflicts=pto_conflicts,
        holiday_conflicts=holiday_conflicts,
    )

    log_msg = (
        f"Analysis complete: {len(over_limit)} over limit, "
        f"{len(at_limit)} at limit, {len(under_limit)} under limit"
    )
    if pto_conflicts:
        log_msg += f", {len(pto_conflicts)} PTO conflicts"
    if holiday_conflicts:
        log_msg += f", {len(holiday_conflicts)} holiday conflicts"
    logger.info(log_msg)

    return result


def analyze_multiple_months(
    team_ids: list[str],
    start_month: int,
    start_year: int,
    num_months: int,
    max_days: int,
    client: PagerDutyClient,
    workday_end_hour: int = 17,
    user_timezones: dict[str, str] | None = None,
    timezones_of_concern: list[str] | None = None,
    excluded_users: list[str] | None = None,
    excluded_schedules: list[str] | None = None,
    pto_by_email: dict[str, list[PTOEntry]] | None = None,
    holidays_by_timezone: dict[str, list[HolidayEntry]] | None = None,
<<<<<<< HEAD
    included_schedules_for_holidays: list[str] | None = None,
    excluded_schedules_for_holidays: list[str] | None = None,
||||||| b6f0624
    user_timezones: Optional[Dict[str, str]] = None,
    timezones_of_concern: Optional[List[str]] = None,
    excluded_users: Optional[List[str]] = None,
    excluded_schedules: Optional[List[str]] = None,
    pto_by_email: Optional[Dict[str, List[PTOEntry]]] = None,
=======
>>>>>>> main
) -> MultiMonthAnalysisResult:
    """Analyze on-call schedules for multiple consecutive months.

    Only counts days where users have on-call coverage extending past the
    workday end hour in their local timezone.

    Args:
        team_ids: List of PagerDuty team IDs to analyze
        start_month: Starting month (1-12)
        start_year: Starting year
        num_months: Number of months to analyze
        max_days: Maximum allowed after-hours on-call days per month
        client: PagerDutyClient instance for API calls
        workday_end_hour: Hour (0-23) when standard workday ends (default: 17 for 5 PM)
        user_timezones: Optional mapping of user emails to timezone strings
        timezones_of_concern: Optional list of timezones to include (empty list means all timezones included)
        excluded_users: Optional list of user emails to exclude from over-limit reporting
        excluded_schedules: Optional list of schedule IDs or names to exclude from analysis
        pto_by_email: Optional dict mapping user emails to lists of PTO entries
        holidays_by_timezone: Optional dict mapping timezones to lists of HolidayEntry objects
<<<<<<< HEAD
        included_schedules_for_holidays: Optional list of schedule names to check for holiday conflicts.
            If empty/None, all schedules are checked.
        excluded_schedules_for_holidays: Optional list of schedule names to exclude from holiday conflict checking.
||||||| b6f0624
=======
>>>>>>> main

    Returns:
        MultiMonthAnalysisResult containing results for each month
    """
    if timezones_of_concern is None:
        timezones_of_concern = []
    if excluded_users is None:
        excluded_users = []
    if excluded_schedules is None:
        excluded_schedules = []
    if pto_by_email is None:
        pto_by_email = {}
    if holidays_by_timezone is None:
        holidays_by_timezone = {}
<<<<<<< HEAD
    if included_schedules_for_holidays is None:
        included_schedules_for_holidays = []
    if excluded_schedules_for_holidays is None:
        excluded_schedules_for_holidays = []
||||||| b6f0624
=======
>>>>>>> main

    logger.info(f"Analyzing {num_months} months starting from {start_month}/{start_year}")

    results = []
    current_month = start_month
    current_year = start_year

    for _ in range(num_months):
        result = analyze_schedules(
            team_ids=team_ids,
            month=current_month,
            year=current_year,
            max_days=max_days,
            client=client,
            workday_end_hour=workday_end_hour,
            user_timezones=user_timezones,
            timezones_of_concern=timezones_of_concern,
            excluded_users=excluded_users,
            excluded_schedules=excluded_schedules,
            pto_by_email=pto_by_email,
            holidays_by_timezone=holidays_by_timezone,
<<<<<<< HEAD
            included_schedules_for_holidays=included_schedules_for_holidays,
            excluded_schedules_for_holidays=excluded_schedules_for_holidays,
||||||| b6f0624
=======
>>>>>>> main
        )
        results.append(result)

        # Advance to next month
        current_month += 1
        if current_month > 12:
            current_month = 1
            current_year += 1

    return MultiMonthAnalysisResult(results=results, max_days=max_days)

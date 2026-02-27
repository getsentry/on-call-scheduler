"""Main orchestrator for on-call schedule analysis."""

import calendar
import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

import pytz

from oncall_scheduler.analysis.calculator import get_dates_in_range
from oncall_scheduler.api.client import PagerDutyClient
from oncall_scheduler.models import (
    AnalysisResult,
    MultiMonthAnalysisResult,
    OnCallReport,
    PTOConflict,
    PTOEntry,
    User,
)

logger = logging.getLogger(__name__)


def _find_pto_conflicts(
    user_schedule_days: Dict[str, Dict[str, set]],
    users: Dict[str, User],
    pto_by_email: Dict[str, List[PTOEntry]],
) -> List[PTOConflict]:
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


def analyze_schedules(
    team_ids: List[str],
    month: int,
    year: int,
    max_days: int,
    client: PagerDutyClient,
    workday_end_hour: int = 17,
    user_timezones: Optional[Dict[str, str]] = None,
    timezones_of_concern: Optional[List[str]] = None,
    excluded_users: Optional[List[str]] = None,
    excluded_schedules: Optional[List[str]] = None,
    pto_by_email: Optional[Dict[str, List[PTOEntry]]] = None,
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
        logger.warning(f"No schedules remaining after exclusions")
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
        logger.warning(f"No on-call entries found for the specified period")
        return AnalysisResult(month=month, year=year, max_days=max_days)

    # Step 4: Build mappings of user_id to User object and schedule-specific days
    users: Dict[str, User] = {}
    user_schedules: Dict[str, List[str]] = defaultdict(list)
    user_schedule_days: Dict[str, Dict[str, set]] = defaultdict(lambda: defaultdict(set))

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
    user_days: Dict[str, set] = {
        user_id: set().union(*schedule_days.values())
        for user_id, schedule_days in user_schedule_days.items()
    }

    # Step 5b: Filter user_days based on timezone and excluded_users
    filtered_user_days: Dict[str, set] = {}
    filtered_user_schedule_days: Dict[str, Dict[str, set]] = {}
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
    )

    log_msg = (
        f"Analysis complete: {len(over_limit)} over limit, "
        f"{len(at_limit)} at limit, {len(under_limit)} under limit"
    )
    if pto_conflicts:
        log_msg += f", {len(pto_conflicts)} PTO conflicts"
    logger.info(log_msg)

    return result


def analyze_multiple_months(
    team_ids: List[str],
    start_month: int,
    start_year: int,
    num_months: int,
    max_days: int,
    client: PagerDutyClient,
    workday_end_hour: int = 17,
    user_timezones: Optional[Dict[str, str]] = None,
    timezones_of_concern: Optional[List[str]] = None,
    excluded_users: Optional[List[str]] = None,
    excluded_schedules: Optional[List[str]] = None,
    pto_by_email: Optional[Dict[str, List[PTOEntry]]] = None,
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
        )
        results.append(result)

        # Advance to next month
        current_month += 1
        if current_month > 12:
            current_month = 1
            current_year += 1

    return MultiMonthAnalysisResult(results=results, max_days=max_days)

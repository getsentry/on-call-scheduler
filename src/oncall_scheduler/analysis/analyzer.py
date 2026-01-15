"""Main orchestrator for on-call schedule analysis."""

import calendar
import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

import pytz

from oncall_scheduler.analysis.calculator import calculate_oncall_days, get_user_schedule_days
from oncall_scheduler.api.client import PagerDutyClient
from oncall_scheduler.models import (
    AnalysisResult,
    MultiMonthAnalysisResult,
    OnCallReport,
    ScheduleEntry,
    User,
)

logger = logging.getLogger(__name__)


def analyze_schedules(
    team_ids: List[str],
    month: int,
    year: int,
    max_days: int,
    client: PagerDutyClient,
    workday_end_hour: int = 17,
    user_timezones: Optional[Dict[str, str]] = None,
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

    Returns:
        AnalysisResult containing categorized user reports

    Raises:
        AuthenticationError: If API authentication fails
        PagerDutyAPIError: For other API errors
    """
    if user_timezones is None:
        user_timezones = {}

    logger.info(f"Starting analysis for {len(team_ids)} teams in {month}/{year}")
    logger.info(f"Maximum days limit: {max_days}")
    logger.info(f"Workday end hour: {workday_end_hour}:00")
    if user_timezones:
        logger.info(f"User timezone overrides configured for {len(user_timezones)} users")

    # Step 1: Fetch schedules for the specified teams
    schedules = client.get_schedules_by_team(team_ids)

    if not schedules:
        logger.warning(f"No schedules found for teams: {team_ids}")
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

    # Step 4: Calculate days per user (only after-hours coverage)
    user_days = calculate_oncall_days(entries, month, year, workday_end_hour)

    # Step 5: Build a mapping of user_id to User object and schedule names
    users: Dict[str, User] = {}
    user_schedules: Dict[str, List[str]] = defaultdict(list)

    for entry in entries:
        if entry.user.id not in users:
            users[entry.user.id] = entry.user

        if entry.schedule.name not in user_schedules[entry.user.id]:
            user_schedules[entry.user.id].append(entry.schedule.name)

    # Step 6: Categorize users by their on-call days
    over_limit = []
    at_limit = []
    under_limit = []

    for user_id, dates in user_days.items():
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
    )

    logger.info(
        f"Analysis complete: {len(over_limit)} over limit, "
        f"{len(at_limit)} at limit, {len(under_limit)} under limit"
    )

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

    Returns:
        MultiMonthAnalysisResult containing results for each month
    """
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
        )
        results.append(result)

        # Advance to next month
        current_month += 1
        if current_month > 12:
            current_month = 1
            current_year += 1

    return MultiMonthAnalysisResult(results=results, max_days=max_days)

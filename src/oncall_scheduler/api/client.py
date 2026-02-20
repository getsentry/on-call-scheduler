"""PagerDuty API client wrapper."""

import logging
import time
from datetime import datetime
from typing import Dict, List

import pagerduty

from oncall_scheduler.api.exceptions import (
    AuthenticationError,
    NetworkError,
    PagerDutyAPIError,
    RateLimitError,
    ResourceNotFoundError,
)
from oncall_scheduler.models import Schedule, ScheduleEntry

logger = logging.getLogger(__name__)


class PagerDutyClient:
    """Wrapper around pagerduty.RestApiV2Client for PagerDuty API interactions."""

    def __init__(self, api_key: str):
        """Initialize the PagerDuty API client.

        Args:
            api_key: PagerDuty API key
        """
        self.api_key = api_key
        self.client = None

    def _get_client(self) -> pagerduty.RestApiV2Client:
        """Get or create API client."""
        if self.client is None:
            self.client = pagerduty.RestApiV2Client(self.api_key)
        return self.client

    def _handle_api_error(self, error: Exception) -> None:
        """Map pagerduty exceptions to custom exceptions.

        Args:
            error: The exception to handle

        Raises:
            AuthenticationError: For authentication failures
            RateLimitError: For rate limit errors
            ResourceNotFoundError: For 404 errors
            NetworkError: For network connectivity issues
            PagerDutyAPIError: For other API errors
        """
        error_message = str(error)

        if "401" in error_message or "403" in error_message or "Unauthorized" in error_message:
            raise AuthenticationError(f"Authentication failed: {error_message}")
        elif "429" in error_message or "rate limit" in error_message.lower():
            raise RateLimitError(f"Rate limit exceeded: {error_message}")
        elif "404" in error_message or "Not Found" in error_message:
            raise ResourceNotFoundError(f"Resource not found: {error_message}")
        elif "timeout" in error_message.lower() or "connection" in error_message.lower():
            raise NetworkError(f"Network error: {error_message}")
        else:
            raise PagerDutyAPIError(f"API error: {error_message}")

    def _retry_with_backoff(self, func, *args, **kwargs):
        """Retry a function with exponential backoff.

        Args:
            func: Function to retry
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function

        Returns:
            The result of the function call

        Raises:
            The last exception if all retries fail
        """
        max_retries = 3
        backoff_seconds = 1

        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except (NetworkError, RateLimitError) as e:
                if attempt == max_retries - 1:
                    raise
                logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {backoff_seconds}s...")
                time.sleep(backoff_seconds)
                backoff_seconds *= 2
            except Exception as e:
                self._handle_api_error(e)

    def get_schedules_by_team(self, team_ids: List[str]) -> List[Schedule]:
        """Fetch schedules associated with specified teams.

        Args:
            team_ids: List of PagerDuty team IDs

        Returns:
            List of Schedule objects

        Raises:
            AuthenticationError: If authentication fails
            ResourceNotFoundError: If a team is not found
            PagerDutyAPIError: For other API errors
        """
        schedules = []
        client = self._get_client()

        def _fetch_schedules():
            schedule_list = []
            for team_id in team_ids:
                try:
                    # Fetch schedules for each team
                    logger.info(f"Fetching schedules for team {team_id}")
                    response = client.iter_all("schedules", params={"team_ids": [team_id]})

                    for schedule_data in response:
                        schedule = Schedule.from_api_response(schedule_data)
                        if schedule not in schedule_list:  # Avoid duplicates
                            schedule_list.append(schedule)
                            logger.debug(f"Found schedule: {schedule.name} ({schedule.id})")

                except pagerduty.HttpError as e:
                    if e.response.status_code == 404:
                        logger.warning(f"Team {team_id} not found, skipping")
                        continue
                    else:
                        raise

            return schedule_list

        schedules = self._retry_with_backoff(_fetch_schedules)
        logger.info(f"Found {len(schedules)} schedules across {len(team_ids)} teams")
        return schedules

    def get_oncalls(
        self,
        schedule_ids: List[str],
        since: datetime,
        until: datetime,
        user_timezones: Dict[str, str] = None,
    ) -> List[ScheduleEntry]:
        """Fetch on-call entries for specified schedules and time range.

        Args:
            schedule_ids: List of PagerDuty schedule IDs
            since: Start datetime for the query
            until: End datetime for the query
            user_timezones: Optional mapping of user emails to timezone strings

        Returns:
            List of ScheduleEntry objects

        Raises:
            AuthenticationError: If authentication fails
            ResourceNotFoundError: If a schedule is not found
            PagerDutyAPIError: For other API errors
        """
        if user_timezones is None:
            user_timezones = {}

        client = self._get_client()

        def _fetch_oncalls():
            entries = []
            logger.info(f"Fetching on-call entries from {since} to {until}")

            # Use the oncalls endpoint with schedule_ids filter
            params = {
                "since": since.isoformat(),
                "until": until.isoformat(),
                "schedule_ids": schedule_ids,
                "include": ["users", "schedules"],
            }

            try:
                response = client.iter_all("oncalls", params=params)

                for oncall_data in response:
                    try:
                        # Get user email for timezone lookup
                        user_email = oncall_data.get("user", {}).get("email", "")
                        user_tz = user_timezones.get(user_email)

                        entry = ScheduleEntry.from_oncall_response(
                            oncall_data, user_timezone_override=user_tz
                        )
                        entries.append(entry)
                        logger.debug(
                            f"On-call entry: {entry.user.name} ({entry.user.timezone}) "
                            f"on {entry.schedule.name} from {entry.start} to {entry.end}"
                        )
                    except (KeyError, ValueError) as e:
                        logger.warning(f"Skipping invalid on-call entry: {e}")
                        continue

            except pagerduty.HttpError as e:
                self._handle_api_error(e)

            logger.info(f"Found {len(entries)} on-call entries")
            return entries

        return self._retry_with_backoff(_fetch_oncalls)

    def test_connection(self) -> bool:
        """Test the API connection and authentication.

        Returns:
            True if connection is successful

        Raises:
            AuthenticationError: If authentication fails
        """
        try:
            client = self._get_client()
            # Try to fetch users with limit 1 to test authentication
            response = client.get("/users", params={"limit": 1})
            if response.is_success:
                logger.info("API connection successful")
                return True
            else:
                self._handle_api_error(Exception(f"HTTP {response.status_code}"))
        except Exception as e:
            self._handle_api_error(e)

    def create_schedule_override(
        self,
        schedule_id: str,
        user_id: str,
        start: datetime,
        end: datetime,
    ) -> dict:
        """Create a schedule override to assign a different user for a time period.

        Args:
            schedule_id: PagerDuty schedule ID
            user_id: PagerDuty user ID to assign for the override
            start: Start datetime for the override
            end: End datetime for the override

        Returns:
            The created override data from PagerDuty API

        Raises:
            AuthenticationError: If authentication fails
            ResourceNotFoundError: If schedule or user is not found
            PagerDutyAPIError: For other API errors
        """
        client = self._get_client()

        def _create_override():
            payload = {
                "override": {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "user": {
                        "id": user_id,
                        "type": "user_reference",
                    },
                }
            }

            try:
                response = client.post(f"/schedules/{schedule_id}/overrides", json=payload)
                if response.is_success:
                    logger.info(
                        f"Created override on schedule {schedule_id}: "
                        f"user {user_id} from {start} to {end}"
                    )
                    return response.json().get("override", {})
                else:
                    self._handle_api_error(Exception(f"HTTP {response.status_code}: {response.text}"))
            except Exception as e:
                self._handle_api_error(e)

        return self._retry_with_backoff(_create_override)

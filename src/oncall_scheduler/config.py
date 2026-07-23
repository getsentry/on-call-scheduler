"""Configuration management for the on-call scheduler application."""

import json
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Required settings
    pagerduty_api_key: str = Field(
        ...,
        description="PagerDuty API key",
        validation_alias="PAGERDUTY_API_KEY",
    )

    # Optional settings
    pagerduty_team_ids: str | None = Field(
        default=None,
        description="Comma-separated list of PagerDuty team IDs",
        validation_alias="PAGERDUTY_TEAM_IDS",
    )

    oncall_max_days: int = Field(
        default=10,
        description="Maximum number of on-call days allowed per month",
        validation_alias="ONCALL_MAX_DAYS",
    )

    timezone: str = Field(
        default="UTC",
        description="Default timezone for calculations",
    )

    sentry_dsn: str | None = Field(
        default=None,
        description="Sentry DSN for error tracking",
        validation_alias="SENTRY_DSN",
    )

    sentry_environment: str = Field(
        default="production",
        description="Sentry environment name",
        validation_alias="SENTRY_ENVIRONMENT",
    )

    user_timezones: str | None = Field(
        default=None,
        description="JSON mapping of user emails to timezones, e.g. '{\"user@example.com\": \"America/New_York\"}'",
        validation_alias="USER_TIMEZONES",
    )

    workday_end_hour: int = Field(
        default=17,
        description="Hour (0-23) when the standard workday ends (default: 17 for 5 PM)",
        validation_alias="WORKDAY_END_HOUR",
    )

    timezones_of_concern: str | None = Field(
        default=None,
        description="Comma-separated list of timezones to include in analysis (e.g. 'America/New_York,Europe/London'). If not specified, all timezones are included.",
        validation_alias="TIMEZONES_OF_CONCERN",
    )

    excluded_users: str | None = Field(
        default=None,
        description="Comma-separated list of user emails to exclude from over-limit reporting (e.g. 'user1@example.com,user2@example.com').",
        validation_alias="EXCLUDED_USERS",
    )

    excluded_schedules: str | None = Field(
        default=None,
        description="Comma-separated list of schedule IDs or names to exclude from analysis (e.g. 'SCHEDULE1,SCHEDULE2' or 'Primary On-Call,Secondary').",
        validation_alias="EXCLUDED_SCHEDULES",
    )

    pto_file: str | None = Field(
        default=None,
        description="Path to JSON file containing PTO data to check for on-call conflicts.",
        validation_alias="PTO_FILE",
    )

    holiday_file: str | None = Field(
        default=None,
        description="Path to JSON file containing holiday data to check for on-call conflicts (keyed by timezone).",
        validation_alias="HOLIDAY_FILE",
    )

    include_schedules_for_holidays: str | None = Field(
        default=None,
        description="Comma-separated list of schedule IDs or names to include for holiday conflict checking. If not specified, all schedules are checked.",
        validation_alias="INCLUDE_SCHEDULES_FROM_HOLIDAYS",
    )

    exclude_schedules_for_holidays: str | None = Field(
        default=None,
        description="Comma-separated list of schedule IDs or names to exclude from holiday conflict checking.",
        validation_alias="EXCLUDE_SCHEDULES_FROM_HOLIDAYS",
    )

    def get_team_ids(self) -> list[str]:
        """Parse and return team IDs as a list."""
        if not self.pagerduty_team_ids:
            return []
        return [team_id.strip() for team_id in self.pagerduty_team_ids.split(",")]

    def get_user_timezones(self) -> dict[str, str]:
        """Parse and return user timezone mappings.

        Returns:
            Dictionary mapping user emails to timezone strings
        """
        if not self.user_timezones:
            return {}
        try:
            return json.loads(self.user_timezones)
        except json.JSONDecodeError:
            return {}

    def get_user_timezone(self, email: str) -> str:
        """Get timezone for a specific user, falling back to default timezone.

        Args:
            email: User's email address

        Returns:
            Timezone string for the user
        """
        user_tz_map = self.get_user_timezones()
        return user_tz_map.get(email, self.timezone)

    def get_timezones_of_concern(self) -> list[str]:
        """Parse and return timezones of concern as a list.

        Returns:
            List of timezone strings to include in analysis. Empty list means all timezones are included.
        """
        if not self.timezones_of_concern:
            return []
        return [tz.strip() for tz in self.timezones_of_concern.split(",")]

    def get_excluded_users(self) -> list[str]:
        """Parse and return excluded users as a list.

        Returns:
            List of user emails to exclude from over-limit reporting. Empty list means no users are excluded.
        """
        if not self.excluded_users:
            return []
        return [email.strip() for email in self.excluded_users.split(",")]

    def get_excluded_schedules(self) -> list[str]:
        """Parse and return excluded schedules as a list.

        Returns:
            List of schedule IDs or names to exclude from analysis. Empty list means no schedules are excluded.
        """
        if not self.excluded_schedules:
            return []
        return [schedule.strip() for schedule in self.excluded_schedules.split(",")]

    def get_included_schedules_for_holidays(self) -> list[str]:
        """Parse and return schedules to include for holiday conflict checking.

        Returns:
            List of schedule IDs or names to include for holiday checking. Empty list means all schedules are checked.
        """
        if not self.include_schedules_for_holidays:
            return []
        return [schedule.strip() for schedule in self.include_schedules_for_holidays.split(",")]

    def get_excluded_schedules_for_holidays(self) -> list[str]:
        """Parse and return schedules to exclude from holiday conflict checking.

        Returns:
            List of schedule IDs or names to exclude from holiday checking. Empty list means no schedules are excluded.
        """
        if not self.exclude_schedules_for_holidays:
            return []
        return [schedule.strip() for schedule in self.exclude_schedules_for_holidays.split(",")]


def load_settings() -> Settings:
    """Load and return application settings."""
    return Settings()


def load_pto_data(pto_file: str) -> dict[str, list[dict[str, str]]]:
    """Load PTO data from a JSON file.

    Expected format:
    {
        "user@example.com": [
            {"start": "2026-02-15", "end": "2026-02-20"},
            {"start": "2026-03-01", "end": "2026-03-05"}
        ],
        "another@example.com": [
            {"start": "2026-02-10", "end": "2026-02-12"}
        ]
    }

    Args:
        pto_file: Path to the PTO JSON file

    Returns:
        Dictionary mapping user emails to lists of PTO date ranges

    Raises:
        FileNotFoundError: If the PTO file does not exist
        json.JSONDecodeError: If the file is not valid JSON
    """
    path = Path(pto_file)
    if not path.exists():
        raise FileNotFoundError(f"PTO file not found: {pto_file}")

    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_holiday_data(holiday_file: str) -> dict[str, list[dict[str, str]]]:
    """Load holiday data from a JSON file.

    Expected format:
    {
        "America/New_York": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-07-04", "name": "Independence Day"}
        ],
        "Europe/London": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-12-25", "name": "Christmas Day"}
        ]
    }

    Args:
        holiday_file: Path to the holiday JSON file

    Returns:
        Dictionary mapping timezones to lists of holiday entries

    Raises:
        FileNotFoundError: If the holiday file does not exist
        json.JSONDecodeError: If the file is not valid JSON
    """
    path = Path(holiday_file)
    if not path.exists():
        raise FileNotFoundError(f"Holiday file not found: {holiday_file}")

    with open(path, encoding="utf-8") as f:
        return json.load(f)

"""Configuration management for the on-call scheduler application."""

from typing import List, Optional

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
    pagerduty_team_ids: Optional[str] = Field(
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

    sentry_dsn: Optional[str] = Field(
        default=None,
        description="Sentry DSN for error tracking",
        validation_alias="SENTRY_DSN",
    )

    sentry_environment: str = Field(
        default="production",
        description="Sentry environment name",
        validation_alias="SENTRY_ENVIRONMENT",
    )

    def get_team_ids(self) -> List[str]:
        """Parse and return team IDs as a list."""
        if not self.pagerduty_team_ids:
            return []
        return [team_id.strip() for team_id in self.pagerduty_team_ids.split(",")]


def load_settings() -> Settings:
    """Load and return application settings."""
    return Settings()

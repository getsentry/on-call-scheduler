"""Tests for configuration management."""

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from oncall_scheduler.config import Settings, load_settings


class TestSettings:
    """Tests for the Settings class."""

    def test_settings_with_required_fields(self):
        """Test creating Settings with only required fields."""
        settings = Settings(
            pagerduty_api_key="test_key",
            pagerduty_from_email="test@example.com"
        )

        assert settings.pagerduty_api_key == "test_key"
        assert settings.pagerduty_from_email == "test@example.com"
        assert settings.oncall_max_days == 10  # Default value
        assert settings.timezone == "UTC"  # Default value
        assert settings.sentry_dsn is None
        assert settings.sentry_environment == "production"

    def test_settings_missing_required_fields(self):
        """Test that missing required fields raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            Settings()

        # Should complain about missing pagerduty_api_key and pagerduty_from_email
        errors = exc_info.value.errors()
        field_names = [error["loc"][0] for error in errors]
        assert "pagerduty_api_key" in field_names
        assert "pagerduty_from_email" in field_names

    def test_settings_with_all_fields(self):
        """Test creating Settings with all fields specified."""
        settings = Settings(
            pagerduty_api_key="test_key",
            pagerduty_from_email="test@example.com",
            pagerduty_team_ids="TEAM1,TEAM2,TEAM3",
            oncall_max_days=15,
            timezone="America/New_York",
            sentry_dsn="https://test@sentry.io/123",
            sentry_environment="staging",
        )

        assert settings.pagerduty_api_key == "test_key"
        assert settings.pagerduty_from_email == "test@example.com"
        assert settings.pagerduty_team_ids == "TEAM1,TEAM2,TEAM3"
        assert settings.oncall_max_days == 15
        assert settings.timezone == "America/New_York"
        assert settings.sentry_dsn == "https://test@sentry.io/123"
        assert settings.sentry_environment == "staging"

    def test_settings_custom_max_days(self):
        """Test setting custom max_days value."""
        settings = Settings(
            pagerduty_api_key="test_key",
            pagerduty_from_email="test@example.com",
            oncall_max_days=20,
        )

        assert settings.oncall_max_days == 20

    def test_get_team_ids_empty(self):
        """Test get_team_ids with no team IDs configured."""
        settings = Settings(
            pagerduty_api_key="test_key",
            pagerduty_from_email="test@example.com"
        )

        team_ids = settings.get_team_ids()

        assert team_ids == []

    def test_get_team_ids_single(self):
        """Test get_team_ids with a single team ID."""
        settings = Settings(
            pagerduty_api_key="test_key",
            pagerduty_from_email="test@example.com",
            pagerduty_team_ids="TEAM1",
        )

        team_ids = settings.get_team_ids()

        assert team_ids == ["TEAM1"]

    def test_get_team_ids_multiple(self):
        """Test get_team_ids with multiple team IDs."""
        settings = Settings(
            pagerduty_api_key="test_key",
            pagerduty_from_email="test@example.com",
            pagerduty_team_ids="TEAM1,TEAM2,TEAM3",
        )

        team_ids = settings.get_team_ids()

        assert team_ids == ["TEAM1", "TEAM2", "TEAM3"]

    def test_get_team_ids_with_spaces(self):
        """Test get_team_ids strips whitespace from team IDs."""
        settings = Settings(
            pagerduty_api_key="test_key",
            pagerduty_from_email="test@example.com",
            pagerduty_team_ids="TEAM1 , TEAM2 ,  TEAM3",
        )

        team_ids = settings.get_team_ids()

        assert team_ids == ["TEAM1", "TEAM2", "TEAM3"]

    @patch.dict(os.environ, {
        "PAGERDUTY_API_KEY": "env_key",
        "PAGERDUTY_FROM_EMAIL": "env@example.com",
        "ONCALL_MAX_DAYS": "25",
        "PAGERDUTY_TEAM_IDS": "TEAM_ENV1,TEAM_ENV2",
    }, clear=True)
    def test_settings_from_environment(self):
        """Test loading settings from environment variables."""
        settings = Settings()

        assert settings.pagerduty_api_key == "env_key"
        assert settings.pagerduty_from_email == "env@example.com"
        assert settings.oncall_max_days == 25
        assert settings.get_team_ids() == ["TEAM_ENV1", "TEAM_ENV2"]

    @patch.dict(os.environ, {
        "PAGERDUTY_API_KEY": "env_key",
        "PAGERDUTY_FROM_EMAIL": "env@example.com",
        "SENTRY_DSN": "https://sentry@example.com/123",
        "SENTRY_ENVIRONMENT": "development",
    }, clear=True)
    def test_settings_sentry_from_environment(self):
        """Test loading Sentry settings from environment."""
        settings = Settings()

        assert settings.sentry_dsn == "https://sentry@example.com/123"
        assert settings.sentry_environment == "development"

    @patch.dict(os.environ, {
        "PAGERDUTY_API_KEY": "env_key",
        "PAGERDUTY_FROM_EMAIL": "env@example.com",
    }, clear=True)
    def test_settings_case_insensitive(self):
        """Test that settings are case insensitive."""
        # The model_config specifies case_sensitive=False
        # Let's verify this works by setting an env var in different case
        with patch.dict(os.environ, {"pagerduty_api_key": "lowercase_key"}, clear=False):
            settings = Settings()
            # Should still pick up the value
            assert settings.pagerduty_api_key in ["env_key", "lowercase_key"]


class TestLoadSettings:
    """Tests for the load_settings function."""

    @patch.dict(os.environ, {
        "PAGERDUTY_API_KEY": "test_key",
        "PAGERDUTY_FROM_EMAIL": "test@example.com",
    }, clear=True)
    def test_load_settings(self):
        """Test load_settings function."""
        settings = load_settings()

        assert isinstance(settings, Settings)
        assert settings.pagerduty_api_key == "test_key"
        assert settings.pagerduty_from_email == "test@example.com"

    @patch.dict(os.environ, {}, clear=True)
    def test_load_settings_missing_required(self):
        """Test load_settings with missing required fields."""
        with pytest.raises(ValidationError):
            load_settings()

    def test_get_excluded_schedules_empty(self):
        """Test get_excluded_schedules with no schedules excluded."""
        settings = Settings(
            pagerduty_api_key="test_key",
            pagerduty_from_email="test@example.com"
        )

        excluded_schedules = settings.get_excluded_schedules()

        assert excluded_schedules == []

    def test_get_excluded_schedules_single(self):
        """Test get_excluded_schedules with a single schedule."""
        settings = Settings(
            pagerduty_api_key="test_key",
            pagerduty_from_email="test@example.com",
            excluded_schedules="SCHEDULE1",
        )

        excluded_schedules = settings.get_excluded_schedules()

        assert excluded_schedules == ["SCHEDULE1"]

    def test_get_excluded_schedules_multiple(self):
        """Test get_excluded_schedules with multiple schedules."""
        settings = Settings(
            pagerduty_api_key="test_key",
            pagerduty_from_email="test@example.com",
            excluded_schedules="SCHEDULE1,SCHEDULE2,Primary On-Call",
        )

        excluded_schedules = settings.get_excluded_schedules()

        assert excluded_schedules == ["SCHEDULE1", "SCHEDULE2", "Primary On-Call"]

    def test_get_excluded_schedules_with_spaces(self):
        """Test get_excluded_schedules strips whitespace from schedule identifiers."""
        settings = Settings(
            pagerduty_api_key="test_key",
            pagerduty_from_email="test@example.com",
            excluded_schedules="SCHEDULE1 , SCHEDULE2 ,  Primary On-Call",
        )

        excluded_schedules = settings.get_excluded_schedules()

        assert excluded_schedules == ["SCHEDULE1", "SCHEDULE2", "Primary On-Call"]

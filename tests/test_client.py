"""Tests for PagerDuty API client."""

from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pagerduty
import pytest
import pytz

from oncall_scheduler.api.client import PagerDutyClient
from oncall_scheduler.api.exceptions import (
    AuthenticationError,
    NetworkError,
    PagerDutyAPIError,
    RateLimitError,
    ResourceNotFoundError,
)
from oncall_scheduler.models import Schedule, ScheduleEntry


class TestPagerDutyClient:
    """Tests for the PagerDutyClient class."""

    def test_init(self):
        """Test client initialization."""
        client = PagerDutyClient(api_key="test_key", from_email="test@example.com")

        assert client.api_key == "test_key"
        assert client.from_email == "test@example.com"
        assert client.client is None

    def test_get_client_creates_client(self):
        """Test that _get_client creates a client on first call."""
        client = PagerDutyClient(api_key="test_key", from_email="test@example.com")

        with patch("oncall_scheduler.api.client.pagerduty.RestApiV2Client") as mock_client_class:
            result = client._get_client()

            mock_client_class.assert_called_once_with("test_key")
            assert client.client is not None

    def test_get_client_reuses_client(self):
        """Test that _get_client reuses existing client."""
        client = PagerDutyClient(api_key="test_key", from_email="test@example.com")
        mock_api_client = Mock()
        client.client = mock_api_client

        result = client._get_client()

        assert result is mock_api_client

    def test_handle_api_error_401_authentication(self):
        """Test handling 401 authentication errors."""
        client = PagerDutyClient(api_key="test_key", from_email="test@example.com")

        with pytest.raises(AuthenticationError) as exc_info:
            client._handle_api_error(Exception("401 Unauthorized"))

        assert "Authentication failed" in str(exc_info.value)

    def test_handle_api_error_403_authentication(self):
        """Test handling 403 authentication errors."""
        client = PagerDutyClient(api_key="test_key", from_email="test@example.com")

        with pytest.raises(AuthenticationError) as exc_info:
            client._handle_api_error(Exception("403 Forbidden"))

        assert "Authentication failed" in str(exc_info.value)

    def test_handle_api_error_429_rate_limit(self):
        """Test handling 429 rate limit errors."""
        client = PagerDutyClient(api_key="test_key", from_email="test@example.com")

        with pytest.raises(RateLimitError) as exc_info:
            client._handle_api_error(Exception("429 Too Many Requests"))

        assert "Rate limit exceeded" in str(exc_info.value)

    def test_handle_api_error_404_not_found(self):
        """Test handling 404 not found errors."""
        client = PagerDutyClient(api_key="test_key", from_email="test@example.com")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            client._handle_api_error(Exception("404 Not Found"))

        assert "Resource not found" in str(exc_info.value)

    def test_handle_api_error_timeout(self):
        """Test handling timeout errors."""
        client = PagerDutyClient(api_key="test_key", from_email="test@example.com")

        with pytest.raises(NetworkError) as exc_info:
            client._handle_api_error(Exception("Connection timeout"))

        assert "Network error" in str(exc_info.value)

    def test_handle_api_error_generic(self):
        """Test handling generic API errors."""
        client = PagerDutyClient(api_key="test_key", from_email="test@example.com")

        with pytest.raises(PagerDutyAPIError) as exc_info:
            client._handle_api_error(Exception("Some other error"))

        assert "API error" in str(exc_info.value)

    def test_get_schedules_by_team_success(self):
        """Test successfully fetching schedules by team."""
        client = PagerDutyClient(api_key="test_key", from_email="test@example.com")

        mock_api_client = Mock()
        mock_api_client.iter_all.return_value = iter([
            {
                "id": "PSCHED1",
                "name": "Primary On-Call",
                "time_zone": "America/New_York",
                "html_url": "https://example.pagerduty.com/schedules/PSCHED1",
            },
            {
                "id": "PSCHED2",
                "name": "Secondary On-Call",
                "time_zone": "UTC",
                "html_url": "https://example.pagerduty.com/schedules/PSCHED2",
            },
        ])

        with patch.object(client, "_get_client", return_value=mock_api_client):
            schedules = client.get_schedules_by_team(["TEAM1"])

        assert len(schedules) == 2
        assert schedules[0].id == "PSCHED1"
        assert schedules[0].name == "Primary On-Call"
        assert schedules[1].id == "PSCHED2"

    def test_get_schedules_by_team_multiple_teams(self):
        """Test fetching schedules for multiple teams."""
        client = PagerDutyClient(api_key="test_key", from_email="test@example.com")

        mock_api_client = Mock()
        # First call returns schedule for TEAM1, second call for TEAM2
        mock_api_client.iter_all.side_effect = [
            iter([{"id": "PSCHED1", "name": "Schedule 1", "time_zone": "UTC"}]),
            iter([{"id": "PSCHED2", "name": "Schedule 2", "time_zone": "UTC"}]),
        ]

        with patch.object(client, "_get_client", return_value=mock_api_client):
            schedules = client.get_schedules_by_team(["TEAM1", "TEAM2"])

        assert len(schedules) == 2
        assert mock_api_client.iter_all.call_count == 2

    def test_get_schedules_by_team_handles_404(self):
        """Test that 404 errors for teams are logged and skipped."""
        client = PagerDutyClient(api_key="test_key", from_email="test@example.com")

        mock_api_client = Mock()
        # Create a mock response with status_code 404
        mock_response = Mock()
        mock_response.status_code = 404
        http_error = pagerduty.HttpError(message="404 Not Found", response=mock_response)

        # First team fails with 404, second succeeds
        mock_api_client.iter_all.side_effect = [
            http_error,
            iter([{"id": "PSCHED2", "name": "Schedule 2", "time_zone": "UTC"}]),
        ]

        with patch.object(client, "_get_client", return_value=mock_api_client):
            schedules = client.get_schedules_by_team(["TEAM1", "TEAM2"])

        # Should only return schedule from TEAM2
        assert len(schedules) == 1
        assert schedules[0].id == "PSCHED2"

    def test_get_oncalls_success(self):
        """Test successfully fetching on-call entries."""
        client = PagerDutyClient(api_key="test_key", from_email="test@example.com")

        mock_api_client = Mock()
        mock_api_client.iter_all.return_value = iter([
            {
                "user": {
                    "id": "PUSER1",
                    "name": "John Doe",
                    "email": "john@example.com",
                },
                "schedule": {
                    "id": "PSCHED1",
                    "name": "Primary On-Call",
                    "time_zone": "UTC",
                },
                "start": "2026-01-01T00:00:00Z",
                "end": "2026-01-08T00:00:00Z",
            }
        ])

        since = datetime(2026, 1, 1, 0, 0, 0)
        until = datetime(2026, 1, 31, 23, 59, 59)

        with patch.object(client, "_get_client", return_value=mock_api_client):
            entries = client.get_oncalls(["PSCHED1"], since, until)

        assert len(entries) == 1
        assert entries[0].user.id == "PUSER1"
        assert entries[0].schedule.id == "PSCHED1"

    def test_get_oncalls_filters_invalid_entries(self):
        """Test that invalid on-call entries are skipped."""
        client = PagerDutyClient(api_key="test_key", from_email="test@example.com")

        mock_api_client = Mock()
        mock_api_client.iter_all.return_value = iter([
            # Valid entry
            {
                "user": {"id": "PUSER1", "name": "John Doe", "email": "john@example.com"},
                "schedule": {"id": "PSCHED1", "name": "Primary", "time_zone": "UTC"},
                "start": "2026-01-01T00:00:00Z",
                "end": "2026-01-08T00:00:00Z",
            },
            # Invalid entry (missing user)
            {
                "schedule": {"id": "PSCHED1", "name": "Primary", "time_zone": "UTC"},
                "start": "2026-01-01T00:00:00Z",
                "end": "2026-01-08T00:00:00Z",
            },
            # Another valid entry
            {
                "user": {"id": "PUSER2", "name": "Jane Doe", "email": "jane@example.com"},
                "schedule": {"id": "PSCHED1", "name": "Primary", "time_zone": "UTC"},
                "start": "2026-01-08T00:00:00Z",
                "end": "2026-01-15T00:00:00Z",
            },
        ])

        since = datetime(2026, 1, 1, 0, 0, 0)
        until = datetime(2026, 1, 31, 23, 59, 59)

        with patch.object(client, "_get_client", return_value=mock_api_client):
            entries = client.get_oncalls(["PSCHED1"], since, until)

        # Should only return 2 valid entries
        assert len(entries) == 2
        assert entries[0].user.id == "PUSER1"
        assert entries[1].user.id == "PUSER2"

    def test_test_connection_success(self):
        """Test successful connection test."""
        client = PagerDutyClient(api_key="test_key", from_email="test@example.com")

        mock_api_client = Mock()
        mock_response = Mock()
        mock_response.is_success = True
        mock_api_client.get.return_value = mock_response

        with patch.object(client, "_get_client", return_value=mock_api_client):
            result = client.test_connection()

        assert result is True
        mock_api_client.get.assert_called_once_with("/users", params={"limit": 1})

    def test_test_connection_failure(self):
        """Test connection test with authentication failure."""
        client = PagerDutyClient(api_key="test_key", from_email="test@example.com")

        mock_api_client = Mock()
        mock_api_client.get.side_effect = Exception("401 Unauthorized")

        with patch.object(client, "_get_client", return_value=mock_api_client):
            with pytest.raises(AuthenticationError):
                client.test_connection()

    @patch("oncall_scheduler.api.client.time.sleep")
    def test_retry_with_backoff_success_after_retry(self, mock_sleep):
        """Test retry logic succeeds after initial failures."""
        client = PagerDutyClient(api_key="test_key", from_email="test@example.com")

        mock_func = Mock(side_effect=[NetworkError("timeout"), NetworkError("timeout"), "success"])

        result = client._retry_with_backoff(mock_func)

        assert result == "success"
        assert mock_func.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("oncall_scheduler.api.client.time.sleep")
    def test_retry_with_backoff_exhausts_retries(self, mock_sleep):
        """Test retry logic exhausts all retries and raises error."""
        client = PagerDutyClient(api_key="test_key", from_email="test@example.com")

        mock_func = Mock(side_effect=NetworkError("timeout"))

        with pytest.raises(NetworkError):
            client._retry_with_backoff(mock_func)

        assert mock_func.call_count == 3

    @patch("oncall_scheduler.api.client.time.sleep")
    def test_retry_with_backoff_non_retryable_error(self, mock_sleep):
        """Test that non-retryable errors are not retried."""
        client = PagerDutyClient(api_key="test_key", from_email="test@example.com")

        mock_func = Mock(side_effect=Exception("401 Unauthorized"))

        with pytest.raises(AuthenticationError):
            client._retry_with_backoff(mock_func)

        # Should not retry authentication errors
        assert mock_func.call_count == 1
        assert mock_sleep.call_count == 0

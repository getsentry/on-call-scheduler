"""Tests for custom exceptions."""

import pytest

from oncall_scheduler.api.exceptions import (
    AuthenticationError,
    NetworkError,
    PagerDutyAPIError,
    RateLimitError,
    ResourceNotFoundError,
)


class TestExceptions:
    """Tests for custom exception classes."""

    def test_pagerduty_api_error_inheritance(self):
        """Test that all custom exceptions inherit from PagerDutyAPIError."""
        assert issubclass(AuthenticationError, PagerDutyAPIError)
        assert issubclass(RateLimitError, PagerDutyAPIError)
        assert issubclass(ResourceNotFoundError, PagerDutyAPIError)
        assert issubclass(NetworkError, PagerDutyAPIError)

    def test_pagerduty_api_error_raise(self):
        """Test raising PagerDutyAPIError."""
        with pytest.raises(PagerDutyAPIError) as exc_info:
            raise PagerDutyAPIError("Test error message")

        assert str(exc_info.value) == "Test error message"

    def test_authentication_error_raise(self):
        """Test raising AuthenticationError."""
        with pytest.raises(AuthenticationError) as exc_info:
            raise AuthenticationError("Invalid credentials")

        assert str(exc_info.value) == "Invalid credentials"
        assert isinstance(exc_info.value, PagerDutyAPIError)

    def test_rate_limit_error_raise(self):
        """Test raising RateLimitError."""
        with pytest.raises(RateLimitError) as exc_info:
            raise RateLimitError("Rate limit exceeded")

        assert str(exc_info.value) == "Rate limit exceeded"
        assert isinstance(exc_info.value, PagerDutyAPIError)

    def test_resource_not_found_error_raise(self):
        """Test raising ResourceNotFoundError."""
        with pytest.raises(ResourceNotFoundError) as exc_info:
            raise ResourceNotFoundError("Schedule not found")

        assert str(exc_info.value) == "Schedule not found"
        assert isinstance(exc_info.value, PagerDutyAPIError)

    def test_network_error_raise(self):
        """Test raising NetworkError."""
        with pytest.raises(NetworkError) as exc_info:
            raise NetworkError("Connection timeout")

        assert str(exc_info.value) == "Connection timeout"
        assert isinstance(exc_info.value, PagerDutyAPIError)

    def test_catch_specific_exception(self):
        """Test catching specific exception types."""
        try:
            raise AuthenticationError("Auth failed")
        except AuthenticationError as e:
            assert str(e) == "Auth failed"
        except PagerDutyAPIError:
            pytest.fail("Should have caught AuthenticationError specifically")

    def test_catch_base_exception(self):
        """Test catching exceptions with base class."""
        try:
            raise RateLimitError("Too many requests")
        except PagerDutyAPIError as e:
            assert isinstance(e, RateLimitError)
            assert str(e) == "Too many requests"

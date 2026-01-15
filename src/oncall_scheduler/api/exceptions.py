"""Custom exceptions for PagerDuty API interactions."""


class PagerDutyAPIError(Exception):
    """Base exception for PagerDuty API errors."""

    pass


class AuthenticationError(PagerDutyAPIError):
    """Raised when authentication with PagerDuty fails."""

    pass


class RateLimitError(PagerDutyAPIError):
    """Raised when PagerDuty API rate limit is exceeded."""

    pass


class ResourceNotFoundError(PagerDutyAPIError):
    """Raised when a requested resource (schedule, team, etc.) is not found."""

    pass


class NetworkError(PagerDutyAPIError):
    """Raised when network connectivity issues occur."""

    pass

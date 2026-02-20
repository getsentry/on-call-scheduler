"""Data models for the on-call scheduler application."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional


@dataclass
class User:
    """Represents a PagerDuty user."""

    id: str
    name: str
    email: str
    html_url: Optional[str] = None
    timezone: str = "UTC"

    @classmethod
    def from_api_response(cls, data: dict, default_timezone: str = "UTC") -> "User":
        """Create a User from PagerDuty API response data.

        Args:
            data: User data from PagerDuty API
            default_timezone: Default timezone to use if not specified in data
        """
        return cls(
            id=data["id"],
            name=data.get("summary", data.get("name", "Unknown")),
            email=data.get("email", ""),
            html_url=data.get("html_url"),
            timezone=data.get("time_zone", default_timezone),
        )


@dataclass
class Schedule:
    """Represents a PagerDuty schedule."""

    id: str
    name: str
    timezone: str
    html_url: Optional[str] = None

    @classmethod
    def from_api_response(cls, data: dict) -> "Schedule":
        """Create a Schedule from PagerDuty API response data."""
        return cls(
            id=data["id"],
            name=data.get("summary", data.get("name", "Unknown")),
            timezone=data.get("time_zone", "UTC"),
            html_url=data.get("html_url"),
        )


@dataclass
class ScheduleEntry:
    """Represents a single on-call entry in a schedule."""

    user: User
    schedule: Schedule
    start: datetime
    end: datetime

    @classmethod
    def from_oncall_response(cls, data: dict, user_timezone_override: Optional[str] = None) -> "ScheduleEntry":
        """Create a ScheduleEntry from PagerDuty oncalls API response data.

        Args:
            data: Oncall data from PagerDuty API
            user_timezone_override: Optional timezone to use for the user (overrides API data)
        """
        # Use schedule timezone as default for user if not specified
        schedule = Schedule.from_api_response(data["schedule"])
        default_tz = user_timezone_override or schedule.timezone

        return cls(
            user=User.from_api_response(data["user"], default_timezone=default_tz),
            schedule=schedule,
            start=datetime.fromisoformat(data["start"].replace("Z", "+00:00")),
            end=datetime.fromisoformat(data["end"].replace("Z", "+00:00")),
        )


@dataclass
class OnCallReport:
    """Report of on-call days for a single user."""

    user: User
    schedule_name: str
    total_days: int
    scheduled_dates: List[date] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "user": {
                "id": self.user.id,
                "name": self.user.name,
                "email": self.user.email,
                "html_url": self.user.html_url,
                "timezone": self.user.timezone,
            },
            "schedule_name": self.schedule_name,
            "total_days": self.total_days,
            "scheduled_dates": [d.isoformat() for d in self.scheduled_dates],
        }


@dataclass
class PTOEntry:
    """Represents a PTO (paid time off) period for a user."""

    user_email: str
    start: date
    end: date

    @classmethod
    def from_dict(cls, user_email: str, data: dict) -> "PTOEntry":
        """Create a PTOEntry from dictionary data.

        Args:
            user_email: Email of the user
            data: Dictionary with 'start' and 'end' date strings (YYYY-MM-DD)
        """
        return cls(
            user_email=user_email,
            start=date.fromisoformat(data["start"]),
            end=date.fromisoformat(data["end"]),
        )

    def contains_date(self, d: date) -> bool:
        """Check if the given date falls within this PTO period."""
        return self.start <= d <= self.end


@dataclass
class PTOConflict:
    """Represents a conflict between on-call schedule and PTO."""

    user: User
    schedule_name: str
    conflicting_dates: List[date] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "user": {
                "id": self.user.id,
                "name": self.user.name,
                "email": self.user.email,
                "html_url": self.user.html_url,
                "timezone": self.user.timezone,
            },
            "schedule_name": self.schedule_name,
            "conflicting_dates": [d.isoformat() for d in self.conflicting_dates],
            "conflict_count": len(self.conflicting_dates),
        }


@dataclass
class AnalysisResult:
    """Complete analysis result for a month."""

    month: int
    year: int
    max_days: int
    over_limit: List[OnCallReport] = field(default_factory=list)
    at_limit: List[OnCallReport] = field(default_factory=list)
    under_limit: List[OnCallReport] = field(default_factory=list)
    pto_conflicts: List[PTOConflict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "month": self.month,
            "year": self.year,
            "max_days": self.max_days,
            "over_limit": [report.to_dict() for report in self.over_limit],
            "at_limit": [report.to_dict() for report in self.at_limit],
            "under_limit": [report.to_dict() for report in self.under_limit],
            "pto_conflicts": [conflict.to_dict() for conflict in self.pto_conflicts],
            "summary": {
                "over_limit_count": len(self.over_limit),
                "at_limit_count": len(self.at_limit),
                "under_limit_count": len(self.under_limit),
                "pto_conflict_count": len(self.pto_conflicts),
            },
        }


@dataclass
class MultiMonthAnalysisResult:
    """Analysis results spanning multiple months."""

    results: List[AnalysisResult] = field(default_factory=list)
    max_days: int = 10

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "max_days": self.max_days,
            "months": [result.to_dict() for result in self.results],
            "summary": {
                "total_months": len(self.results),
                "total_over_limit": sum(len(r.over_limit) for r in self.results),
                "total_at_limit": sum(len(r.at_limit) for r in self.results),
                "total_under_limit": sum(len(r.under_limit) for r in self.results),
                "total_pto_conflicts": sum(len(r.pto_conflicts) for r in self.results),
            },
        }

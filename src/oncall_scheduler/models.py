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

    @classmethod
    def from_api_response(cls, data: dict) -> "User":
        """Create a User from PagerDuty API response data."""
        return cls(
            id=data["id"],
            name=data.get("summary", data.get("name", "Unknown")),
            email=data.get("email", ""),
            html_url=data.get("html_url"),
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
    def from_oncall_response(cls, data: dict) -> "ScheduleEntry":
        """Create a ScheduleEntry from PagerDuty oncalls API response data."""
        return cls(
            user=User.from_api_response(data["user"]),
            schedule=Schedule.from_api_response(data["schedule"]),
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
            },
            "schedule_name": self.schedule_name,
            "total_days": self.total_days,
            "scheduled_dates": [d.isoformat() for d in self.scheduled_dates],
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

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "month": self.month,
            "year": self.year,
            "max_days": self.max_days,
            "over_limit": [report.to_dict() for report in self.over_limit],
            "at_limit": [report.to_dict() for report in self.at_limit],
            "under_limit": [report.to_dict() for report in self.under_limit],
            "summary": {
                "over_limit_count": len(self.over_limit),
                "at_limit_count": len(self.at_limit),
                "under_limit_count": len(self.under_limit),
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
            },
        }

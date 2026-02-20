"""Tests for data models."""

from datetime import date, datetime

import pytest
import pytz

from oncall_scheduler.models import (
    AnalysisResult,
    OnCallReport,
    PTOConflict,
    PTOEntry,
    Schedule,
    ScheduleEntry,
    User,
)


class TestUser:
    """Tests for the User model."""

    def test_from_api_response_basic(self):
        """Test creating a User from API response with basic data."""
        data = {
            "id": "PUSER123",
            "name": "John Doe",
            "email": "john@example.com",
            "html_url": "https://example.pagerduty.com/users/PUSER123",
        }

        user = User.from_api_response(data)

        assert user.id == "PUSER123"
        assert user.name == "John Doe"
        assert user.email == "john@example.com"
        assert user.html_url == "https://example.pagerduty.com/users/PUSER123"

    def test_from_api_response_with_summary(self):
        """Test User creation when name is in 'summary' field."""
        data = {
            "id": "PUSER123",
            "summary": "Jane Smith",
            "email": "jane@example.com",
        }

        user = User.from_api_response(data)

        assert user.name == "Jane Smith"
        assert user.html_url is None

    def test_from_api_response_fallback_to_unknown(self):
        """Test User creation with missing name falls back to 'Unknown'."""
        data = {
            "id": "PUSER123",
            "email": "test@example.com",
        }

        user = User.from_api_response(data)

        assert user.name == "Unknown"

    def test_from_api_response_missing_email(self):
        """Test User creation with missing email defaults to empty string."""
        data = {
            "id": "PUSER123",
            "name": "Test User",
        }

        user = User.from_api_response(data)

        assert user.email == ""


class TestSchedule:
    """Tests for the Schedule model."""

    def test_from_api_response_basic(self):
        """Test creating a Schedule from API response with basic data."""
        data = {
            "id": "PSCHED123",
            "name": "Primary On-Call",
            "time_zone": "America/New_York",
            "html_url": "https://example.pagerduty.com/schedules/PSCHED123",
        }

        schedule = Schedule.from_api_response(data)

        assert schedule.id == "PSCHED123"
        assert schedule.name == "Primary On-Call"
        assert schedule.timezone == "America/New_York"
        assert schedule.html_url == "https://example.pagerduty.com/schedules/PSCHED123"

    def test_from_api_response_with_summary(self):
        """Test Schedule creation when name is in 'summary' field."""
        data = {
            "id": "PSCHED123",
            "summary": "Secondary Schedule",
            "time_zone": "UTC",
        }

        schedule = Schedule.from_api_response(data)

        assert schedule.name == "Secondary Schedule"

    def test_from_api_response_default_timezone(self):
        """Test Schedule creation with missing timezone defaults to UTC."""
        data = {
            "id": "PSCHED123",
            "name": "Test Schedule",
        }

        schedule = Schedule.from_api_response(data)

        assert schedule.timezone == "UTC"


class TestScheduleEntry:
    """Tests for the ScheduleEntry model."""

    def test_from_oncall_response(self):
        """Test creating a ScheduleEntry from oncalls API response."""
        data = {
            "user": {
                "id": "PUSER123",
                "name": "Alice Smith",
                "email": "alice@example.com",
            },
            "schedule": {
                "id": "PSCHED123",
                "name": "Primary On-Call",
                "time_zone": "America/Los_Angeles",
            },
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-08T00:00:00Z",
        }

        entry = ScheduleEntry.from_oncall_response(data)

        assert entry.user.id == "PUSER123"
        assert entry.user.name == "Alice Smith"
        assert entry.schedule.id == "PSCHED123"
        assert entry.schedule.name == "Primary On-Call"
        assert entry.start.year == 2026
        assert entry.start.month == 1
        assert entry.start.day == 1
        assert entry.end.year == 2026
        assert entry.end.month == 1
        assert entry.end.day == 8

    def test_from_oncall_response_timezone_aware(self):
        """Test that ScheduleEntry datetimes are timezone-aware."""
        data = {
            "user": {"id": "PUSER123", "name": "Test User", "email": "test@example.com"},
            "schedule": {"id": "PSCHED123", "name": "Test Schedule", "time_zone": "UTC"},
            "start": "2026-01-15T12:00:00Z",
            "end": "2026-01-16T12:00:00Z",
        }

        entry = ScheduleEntry.from_oncall_response(data)

        assert entry.start.tzinfo is not None
        assert entry.end.tzinfo is not None


class TestOnCallReport:
    """Tests for the OnCallReport model."""

    def test_to_dict(self):
        """Test converting OnCallReport to dictionary."""
        user = User(
            id="PUSER123",
            name="Bob Jones",
            email="bob@example.com",
            html_url="https://example.pagerduty.com/users/PUSER123",
        )

        dates = [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]

        report = OnCallReport(
            user=user,
            schedule_name="Primary On-Call",
            total_days=3,
            scheduled_dates=dates,
        )

        result = report.to_dict()

        assert result["user"]["id"] == "PUSER123"
        assert result["user"]["name"] == "Bob Jones"
        assert result["user"]["email"] == "bob@example.com"
        assert result["user"]["html_url"] == "https://example.pagerduty.com/users/PUSER123"
        assert result["schedule_name"] == "Primary On-Call"
        assert result["total_days"] == 3
        assert result["scheduled_dates"] == ["2026-01-01", "2026-01-02", "2026-01-03"]

    def test_to_dict_empty_dates(self):
        """Test converting OnCallReport with no dates to dictionary."""
        user = User(id="PUSER123", name="Test User", email="test@example.com")

        report = OnCallReport(
            user=user,
            schedule_name="Test Schedule",
            total_days=0,
            scheduled_dates=[],
        )

        result = report.to_dict()

        assert result["total_days"] == 0
        assert result["scheduled_dates"] == []


class TestAnalysisResult:
    """Tests for the AnalysisResult model."""

    def test_to_dict_empty(self):
        """Test converting empty AnalysisResult to dictionary."""
        result = AnalysisResult(month=1, year=2026, max_days=10)

        output = result.to_dict()

        assert output["month"] == 1
        assert output["year"] == 2026
        assert output["max_days"] == 10
        assert output["over_limit"] == []
        assert output["at_limit"] == []
        assert output["under_limit"] == []
        assert output["pto_conflicts"] == []
        assert output["summary"]["over_limit_count"] == 0
        assert output["summary"]["at_limit_count"] == 0
        assert output["summary"]["under_limit_count"] == 0
        assert output["summary"]["pto_conflict_count"] == 0

    def test_to_dict_with_reports(self):
        """Test converting AnalysisResult with reports to dictionary."""
        user1 = User(id="PUSER1", name="User One", email="user1@example.com")
        user2 = User(id="PUSER2", name="User Two", email="user2@example.com")
        user3 = User(id="PUSER3", name="User Three", email="user3@example.com")

        over_report = OnCallReport(
            user=user1,
            schedule_name="Schedule A",
            total_days=15,
            scheduled_dates=[date(2026, 1, i) for i in range(1, 16)],
        )

        at_report = OnCallReport(
            user=user2,
            schedule_name="Schedule B",
            total_days=10,
            scheduled_dates=[date(2026, 1, i) for i in range(1, 11)],
        )

        under_report = OnCallReport(
            user=user3,
            schedule_name="Schedule C",
            total_days=5,
            scheduled_dates=[date(2026, 1, i) for i in range(1, 6)],
        )

        result = AnalysisResult(
            month=1,
            year=2026,
            max_days=10,
            over_limit=[over_report],
            at_limit=[at_report],
            under_limit=[under_report],
        )

        output = result.to_dict()

        assert len(output["over_limit"]) == 1
        assert len(output["at_limit"]) == 1
        assert len(output["under_limit"]) == 1
        assert output["summary"]["over_limit_count"] == 1
        assert output["summary"]["at_limit_count"] == 1
        assert output["summary"]["under_limit_count"] == 1
        assert output["over_limit"][0]["total_days"] == 15
        assert output["at_limit"][0]["total_days"] == 10
        assert output["under_limit"][0]["total_days"] == 5

    def test_to_dict_with_pto_conflicts(self):
        """Test converting AnalysisResult with PTO conflicts to dictionary."""
        user = User(id="PUSER1", name="User One", email="user1@example.com")

        conflict = PTOConflict(
            user=user,
            schedule_name="Schedule A",
            conflicting_dates=[date(2026, 1, 15), date(2026, 1, 16)],
        )

        result = AnalysisResult(
            month=1,
            year=2026,
            max_days=10,
            pto_conflicts=[conflict],
        )

        output = result.to_dict()

        assert "pto_conflicts" in output
        assert len(output["pto_conflicts"]) == 1
        assert output["pto_conflicts"][0]["conflict_count"] == 2
        assert output["summary"]["pto_conflict_count"] == 1


class TestPTOEntry:
    """Tests for the PTOEntry model."""

    def test_from_dict_basic(self):
        """Test creating a PTOEntry from dictionary data."""
        data = {"start": "2026-02-15", "end": "2026-02-20"}

        entry = PTOEntry.from_dict("user@example.com", data)

        assert entry.user_email == "user@example.com"
        assert entry.start == date(2026, 2, 15)
        assert entry.end == date(2026, 2, 20)

    def test_contains_date_within_range(self):
        """Test that contains_date returns True for dates within PTO range."""
        entry = PTOEntry(
            user_email="user@example.com",
            start=date(2026, 2, 15),
            end=date(2026, 2, 20),
        )

        assert entry.contains_date(date(2026, 2, 15))  # Start date
        assert entry.contains_date(date(2026, 2, 17))  # Middle
        assert entry.contains_date(date(2026, 2, 20))  # End date

    def test_contains_date_outside_range(self):
        """Test that contains_date returns False for dates outside PTO range."""
        entry = PTOEntry(
            user_email="user@example.com",
            start=date(2026, 2, 15),
            end=date(2026, 2, 20),
        )

        assert not entry.contains_date(date(2026, 2, 14))  # Before
        assert not entry.contains_date(date(2026, 2, 21))  # After
        assert not entry.contains_date(date(2026, 1, 17))  # Different month


class TestPTOConflict:
    """Tests for the PTOConflict model."""

    def test_to_dict(self):
        """Test converting PTOConflict to dictionary."""
        user = User(
            id="PUSER123",
            name="Bob Jones",
            email="bob@example.com",
            html_url="https://example.pagerduty.com/users/PUSER123",
            timezone="America/New_York",
        )

        conflict = PTOConflict(
            user=user,
            schedule_name="Primary On-Call",
            conflicting_dates=[date(2026, 2, 15), date(2026, 2, 16), date(2026, 2, 17)],
        )

        result = conflict.to_dict()

        assert result["user"]["id"] == "PUSER123"
        assert result["user"]["name"] == "Bob Jones"
        assert result["user"]["email"] == "bob@example.com"
        assert result["user"]["timezone"] == "America/New_York"
        assert result["schedule_name"] == "Primary On-Call"
        assert result["conflicting_dates"] == ["2026-02-15", "2026-02-16", "2026-02-17"]
        assert result["conflict_count"] == 3

    def test_to_dict_empty_conflicts(self):
        """Test converting PTOConflict with no conflicts to dictionary."""
        user = User(id="PUSER123", name="Test User", email="test@example.com")

        conflict = PTOConflict(
            user=user,
            schedule_name="Test Schedule",
            conflicting_dates=[],
        )

        result = conflict.to_dict()

        assert result["conflicting_dates"] == []
        assert result["conflict_count"] == 0

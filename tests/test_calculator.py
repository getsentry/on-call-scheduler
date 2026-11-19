"""Tests for on-call days calculator."""

from datetime import date, datetime, timedelta

import pytest
import pytz

from oncall_scheduler.analysis.calculator import (
    calculate_oncall_days,
    count_days_in_month,
    get_dates_in_range,
    get_user_schedule_days,
)
from oncall_scheduler.models import Schedule, ScheduleEntry, User


class TestGetDatesInRange:
    """Tests for the get_dates_in_range function."""

    def test_basic_range(self):
        """Test getting dates in a basic range."""
        start = datetime(2026, 1, 1, 0, 0, 0)
        end = datetime(2026, 1, 5, 0, 0, 0)
        month_start = datetime(2026, 1, 1, 0, 0, 0)
        month_end = datetime(2026, 1, 31, 23, 59, 59)

        dates = get_dates_in_range(start, end, month_start, month_end, "UTC")

        # Only days with coverage past the 17:00 workday end count; the shift
        # ends at midnight on Jan 5, so Jan 5 has no after-hours coverage
        assert len(dates) == 4
        assert date(2026, 1, 1) in dates
        assert date(2026, 1, 2) in dates
        assert date(2026, 1, 3) in dates
        assert date(2026, 1, 4) in dates
        assert date(2026, 1, 5) not in dates

    def test_range_clamped_to_month_start(self):
        """Test range that starts before the month."""
        start = datetime(2025, 12, 28, 0, 0, 0)
        end = datetime(2026, 1, 5, 0, 0, 0)
        month_start = datetime(2026, 1, 1, 0, 0, 0)
        month_end = datetime(2026, 1, 31, 23, 59, 59)

        dates = get_dates_in_range(start, end, month_start, month_end, "UTC")

        # Should only include Jan 1-4, not Dec 28-31 (and not Jan 5, which
        # has no coverage past the workday end)
        assert len(dates) == 4
        assert date(2025, 12, 28) not in dates
        assert date(2026, 1, 1) in dates
        assert date(2026, 1, 4) in dates
        assert date(2026, 1, 5) not in dates

    def test_range_clamped_to_month_end(self):
        """Test range that extends past the month."""
        start = datetime(2026, 1, 28, 0, 0, 0)
        end = datetime(2026, 2, 3, 0, 0, 0)
        month_start = datetime(2026, 1, 1, 0, 0, 0)
        month_end = datetime(2026, 1, 31, 23, 59, 59)

        dates = get_dates_in_range(start, end, month_start, month_end, "UTC")

        # Should only include Jan 28-31, not Feb 1-3
        assert len(dates) == 4
        assert date(2026, 1, 28) in dates
        assert date(2026, 1, 31) in dates
        assert date(2026, 2, 1) not in dates

    def test_range_outside_month(self):
        """Test range completely outside the month."""
        start = datetime(2026, 2, 1, 0, 0, 0)
        end = datetime(2026, 2, 5, 0, 0, 0)
        month_start = datetime(2026, 1, 1, 0, 0, 0)
        month_end = datetime(2026, 1, 31, 23, 59, 59)

        dates = get_dates_in_range(start, end, month_start, month_end, "UTC")

        assert len(dates) == 0

    def test_timezone_conversion(self):
        """Test that timezone conversion is handled correctly."""
        # Start at 11 PM UTC on Dec 31, which is 3 PM PST on Dec 31
        start = pytz.utc.localize(datetime(2025, 12, 31, 23, 0, 0))
        # End at 2 AM UTC on Jan 1, which is 6 PM PST on Dec 31 (still Dec 31!)
        end = pytz.utc.localize(datetime(2026, 1, 1, 2, 0, 0))
        month_start = pytz.utc.localize(datetime(2026, 1, 1, 0, 0, 0))
        month_end = pytz.utc.localize(datetime(2026, 1, 31, 23, 59, 59))

        # In America/Los_Angeles timezone
        dates = get_dates_in_range(start, end, month_start, month_end, "America/Los_Angeles")

        # In PST, this entire shift is on Dec 31, 2025 (outside our month)
        assert len(dates) == 0

    def test_single_day(self):
        """Test a shift within a single day that runs past the workday end."""
        start = datetime(2026, 1, 15, 9, 0, 0)
        end = datetime(2026, 1, 15, 18, 0, 0)
        month_start = datetime(2026, 1, 1, 0, 0, 0)
        month_end = datetime(2026, 1, 31, 23, 59, 59)

        dates = get_dates_in_range(start, end, month_start, month_end, "UTC")

        assert len(dates) == 1
        assert date(2026, 1, 15) in dates

    def test_single_day_within_work_hours_not_counted(self):
        """Test a shift that ends exactly at the workday end is not counted."""
        start = datetime(2026, 1, 15, 9, 0, 0)
        end = datetime(2026, 1, 15, 17, 0, 0)
        month_start = datetime(2026, 1, 1, 0, 0, 0)
        month_end = datetime(2026, 1, 31, 23, 59, 59)

        dates = get_dates_in_range(start, end, month_start, month_end, "UTC")

        assert len(dates) == 0


class TestCalculateOncallDays:
    """Tests for the calculate_oncall_days function."""

    def test_single_user_single_entry(self):
        """Test calculating days for a single user with one entry."""
        user = User(id="PUSER1", name="Test User", email="test@example.com")
        schedule = Schedule(id="PSCHED1", name="Test Schedule", timezone="UTC")

        start = pytz.utc.localize(datetime(2026, 1, 1, 0, 0, 0))
        end = pytz.utc.localize(datetime(2026, 1, 8, 0, 0, 0))

        entry = ScheduleEntry(user=user, schedule=schedule, start=start, end=end)

        result = calculate_oncall_days([entry], month=1, year=2026)

        assert "PUSER1" in result
        # Jan 1-7: the shift ends at midnight on Jan 8, before the workday end
        assert len(result["PUSER1"]) == 7
        assert date(2026, 1, 8) not in result["PUSER1"]

    def test_multiple_users(self):
        """Test calculating days for multiple users."""
        user1 = User(id="PUSER1", name="User One", email="user1@example.com")
        user2 = User(id="PUSER2", name="User Two", email="user2@example.com")
        schedule = Schedule(id="PSCHED1", name="Test Schedule", timezone="UTC")

        start1 = pytz.utc.localize(datetime(2026, 1, 1, 0, 0, 0))
        end1 = pytz.utc.localize(datetime(2026, 1, 8, 0, 0, 0))

        start2 = pytz.utc.localize(datetime(2026, 1, 8, 0, 0, 0))
        end2 = pytz.utc.localize(datetime(2026, 1, 15, 0, 0, 0))

        entry1 = ScheduleEntry(user=user1, schedule=schedule, start=start1, end=end1)
        entry2 = ScheduleEntry(user=user2, schedule=schedule, start=start2, end=end2)

        result = calculate_oncall_days([entry1, entry2], month=1, year=2026)

        assert "PUSER1" in result
        assert "PUSER2" in result
        # Each user covers 7 evenings; the handoff day (Jan 8) belongs to user 2 only
        assert len(result["PUSER1"]) == 7
        assert len(result["PUSER2"]) == 7
        assert date(2026, 1, 8) not in result["PUSER1"]
        assert date(2026, 1, 8) in result["PUSER2"]

    def test_overlapping_entries_same_user(self):
        """Test that overlapping entries for same user don't double-count days."""
        user = User(id="PUSER1", name="Test User", email="test@example.com")
        schedule1 = Schedule(id="PSCHED1", name="Schedule 1", timezone="UTC")
        schedule2 = Schedule(id="PSCHED2", name="Schedule 2", timezone="UTC")

        start1 = pytz.utc.localize(datetime(2026, 1, 1, 0, 0, 0))
        end1 = pytz.utc.localize(datetime(2026, 1, 8, 0, 0, 0))

        start2 = pytz.utc.localize(datetime(2026, 1, 5, 0, 0, 0))
        end2 = pytz.utc.localize(datetime(2026, 1, 10, 0, 0, 0))

        entry1 = ScheduleEntry(user=user, schedule=schedule1, start=start1, end=end1)
        entry2 = ScheduleEntry(user=user, schedule=schedule2, start=start2, end=end2)

        result = calculate_oncall_days([entry1, entry2], month=1, year=2026)

        # Days 1-9 should be counted once, not twice (Jan 10 ends at midnight)
        assert len(result["PUSER1"]) == 9

    def test_entries_spanning_month_boundary(self):
        """Test entries that span across month boundaries."""
        user = User(id="PUSER1", name="Test User", email="test@example.com")
        schedule = Schedule(id="PSCHED1", name="Test Schedule", timezone="UTC")

        start = pytz.utc.localize(datetime(2025, 12, 28, 0, 0, 0))
        end = pytz.utc.localize(datetime(2026, 1, 5, 0, 0, 0))

        entry = ScheduleEntry(user=user, schedule=schedule, start=start, end=end)

        result = calculate_oncall_days([entry], month=1, year=2026)

        # Should only count Jan 1-4 (Jan 5 ends at midnight, before the workday end)
        assert len(result["PUSER1"]) == 4
        assert date(2026, 1, 1) in result["PUSER1"]
        assert date(2026, 1, 4) in result["PUSER1"]
        assert date(2026, 1, 5) not in result["PUSER1"]

    def test_month_start_uses_user_timezone(self):
        """Test that a Dec 31 evening in Los Angeles is not counted in January."""
        user = User(
            id="PUSER1", name="LA User", email="la@example.com", timezone="America/Los_Angeles"
        )
        schedule = Schedule(id="PSCHED1", name="Test Schedule", timezone="UTC")

        # Dec 31 17:00-19:00 in Los Angeles, which is already Jan 1 in UTC
        start = pytz.utc.localize(datetime(2026, 1, 1, 1, 0, 0))
        end = pytz.utc.localize(datetime(2026, 1, 1, 3, 0, 0))
        entry = ScheduleEntry(user=user, schedule=schedule, start=start, end=end)

        january = calculate_oncall_days([entry], month=1, year=2026)
        december = calculate_oncall_days([entry], month=12, year=2025)

        assert january.get("PUSER1", set()) == set()
        assert december["PUSER1"] == {date(2025, 12, 31)}

    def test_month_end_uses_user_timezone(self):
        """Test that a Feb 1 evening in Vienna is not counted in January."""
        user = User(
            id="PUSER1", name="Vienna User", email="vienna@example.com", timezone="Europe/Vienna"
        )
        schedule = Schedule(id="PSCHED1", name="Test Schedule", timezone="UTC")

        # Jan 31 09:00 to Feb 2 09:00 in Vienna
        start = pytz.utc.localize(datetime(2026, 1, 31, 8, 0, 0))
        end = pytz.utc.localize(datetime(2026, 2, 2, 8, 0, 0))
        entry = ScheduleEntry(user=user, schedule=schedule, start=start, end=end)

        january = calculate_oncall_days([entry], month=1, year=2026)
        february = calculate_oncall_days([entry], month=2, year=2026)

        assert january["PUSER1"] == {date(2026, 1, 31)}
        assert february["PUSER1"] == {date(2026, 2, 1)}

    def test_empty_entries_list(self):
        """Test with no entries."""
        result = calculate_oncall_days([], month=1, year=2026)

        assert result == {}


class TestGetUserScheduleDays:
    """Tests for the get_user_schedule_days function."""

    def test_get_user_days(self):
        """Test getting all days for a specific user."""
        user1 = User(id="PUSER1", name="User One", email="user1@example.com")
        user2 = User(id="PUSER2", name="User Two", email="user2@example.com")
        schedule = Schedule(id="PSCHED1", name="Test Schedule", timezone="UTC")

        start1 = pytz.utc.localize(datetime(2026, 1, 1, 0, 0, 0))
        end1 = pytz.utc.localize(datetime(2026, 1, 5, 0, 0, 0))

        start2 = pytz.utc.localize(datetime(2026, 1, 10, 0, 0, 0))
        end2 = pytz.utc.localize(datetime(2026, 1, 12, 0, 0, 0))

        entry1 = ScheduleEntry(user=user1, schedule=schedule, start=start1, end=end1)
        entry2 = ScheduleEntry(user=user2, schedule=schedule, start=start2, end=end2)

        result = get_user_schedule_days("PUSER1", [entry1, entry2])

        # Jan 1-4: Jan 5 has no coverage past the workday end
        assert len(result) == 4
        assert date(2026, 1, 1) in result
        assert date(2026, 1, 4) in result
        assert date(2026, 1, 5) not in result
        assert date(2026, 1, 10) not in result

    def test_sorted_output(self):
        """Test that returned dates are sorted chronologically."""
        user = User(id="PUSER1", name="Test User", email="test@example.com")
        schedule = Schedule(id="PSCHED1", name="Test Schedule", timezone="UTC")

        # Create entries out of order
        start2 = pytz.utc.localize(datetime(2026, 1, 10, 0, 0, 0))
        end2 = pytz.utc.localize(datetime(2026, 1, 12, 0, 0, 0))

        start1 = pytz.utc.localize(datetime(2026, 1, 1, 0, 0, 0))
        end1 = pytz.utc.localize(datetime(2026, 1, 3, 0, 0, 0))

        entry2 = ScheduleEntry(user=user, schedule=schedule, start=start2, end=end2)
        entry1 = ScheduleEntry(user=user, schedule=schedule, start=start1, end=end1)

        result = get_user_schedule_days("PUSER1", [entry2, entry1])

        # Should be sorted
        assert result == sorted(result)
        assert result[0] == date(2026, 1, 1)

    def test_user_not_found(self):
        """Test getting days for a user with no entries."""
        user = User(id="PUSER1", name="Test User", email="test@example.com")
        schedule = Schedule(id="PSCHED1", name="Test Schedule", timezone="UTC")

        start = pytz.utc.localize(datetime(2026, 1, 1, 0, 0, 0))
        end = pytz.utc.localize(datetime(2026, 1, 5, 0, 0, 0))

        entry = ScheduleEntry(user=user, schedule=schedule, start=start, end=end)

        result = get_user_schedule_days("PUSER999", [entry])

        assert result == []


class TestCountDaysInMonth:
    """Tests for the count_days_in_month function."""

    def test_count_single_user(self):
        """Test counting days for a single user."""
        user = User(id="PUSER1", name="Test User", email="test@example.com")
        schedule = Schedule(id="PSCHED1", name="Test Schedule", timezone="UTC")

        start = pytz.utc.localize(datetime(2026, 1, 1, 0, 0, 0))
        end = pytz.utc.localize(datetime(2026, 1, 8, 0, 0, 0))

        entry = ScheduleEntry(user=user, schedule=schedule, start=start, end=end)

        count = count_days_in_month([entry], month=1, year=2026)

        # Jan 1-7 have after-hours coverage
        assert count == 7

    def test_count_multiple_users(self):
        """Test counting total days across multiple users."""
        user1 = User(id="PUSER1", name="User One", email="user1@example.com")
        user2 = User(id="PUSER2", name="User Two", email="user2@example.com")
        schedule = Schedule(id="PSCHED1", name="Test Schedule", timezone="UTC")

        start1 = pytz.utc.localize(datetime(2026, 1, 1, 0, 0, 0))
        end1 = pytz.utc.localize(datetime(2026, 1, 8, 0, 0, 0))

        start2 = pytz.utc.localize(datetime(2026, 1, 8, 0, 0, 0))
        end2 = pytz.utc.localize(datetime(2026, 1, 15, 0, 0, 0))

        entry1 = ScheduleEntry(user=user1, schedule=schedule, start=start1, end=end1)
        entry2 = ScheduleEntry(user=user2, schedule=schedule, start=start2, end=end2)

        count = count_days_in_month([entry1, entry2], month=1, year=2026)

        # User 1: 7 days, User 2: 7 days
        assert count == 14

    def test_count_empty(self):
        """Test counting with no entries."""
        count = count_days_in_month([], month=1, year=2026)

        assert count == 0

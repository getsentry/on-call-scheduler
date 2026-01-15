"""Tests for the on-call schedule analyzer."""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest
import pytz

from oncall_scheduler.analysis.analyzer import analyze_schedules
from oncall_scheduler.models import Schedule, ScheduleEntry, User


class TestAnalyzeSchedules:
    """Tests for the analyze_schedules function."""

    def test_analyze_schedules_no_schedules_found(self):
        """Test analysis when no schedules are found for teams."""
        mock_client = Mock()
        mock_client.get_schedules_by_team.return_value = []

        result = analyze_schedules(
            team_ids=["TEAM1"], month=1, year=2026, max_days=10, client=mock_client
        )

        assert result.month == 1
        assert result.year == 2026
        assert result.max_days == 10
        assert len(result.over_limit) == 0
        assert len(result.at_limit) == 0
        assert len(result.under_limit) == 0

    def test_analyze_schedules_no_oncall_entries(self):
        """Test analysis when schedules exist but no on-call entries."""
        mock_client = Mock()
        mock_client.get_schedules_by_team.return_value = [
            Schedule(id="PSCHED1", name="Test Schedule", timezone="UTC")
        ]
        mock_client.get_oncalls.return_value = []

        result = analyze_schedules(
            team_ids=["TEAM1"], month=1, year=2026, max_days=10, client=mock_client
        )

        assert len(result.over_limit) == 0
        assert len(result.at_limit) == 0
        assert len(result.under_limit) == 0

    def test_analyze_schedules_user_over_limit(self):
        """Test analysis with user exceeding the limit."""
        user = User(id="PUSER1", name="Test User", email="test@example.com")
        schedule = Schedule(id="PSCHED1", name="Test Schedule", timezone="UTC")

        # Create entries totaling 15 days (over the 10 day limit)
        entries = []
        for day in range(1, 16):
            start = pytz.utc.localize(datetime(2026, 1, day, 0, 0, 0))
            end = pytz.utc.localize(datetime(2026, 1, day, 23, 59, 59))
            entries.append(ScheduleEntry(user=user, schedule=schedule, start=start, end=end))

        mock_client = Mock()
        mock_client.get_schedules_by_team.return_value = [schedule]
        mock_client.get_oncalls.return_value = entries

        result = analyze_schedules(
            team_ids=["TEAM1"], month=1, year=2026, max_days=10, client=mock_client
        )

        assert len(result.over_limit) == 1
        assert len(result.at_limit) == 0
        assert len(result.under_limit) == 0
        assert result.over_limit[0].user.id == "PUSER1"
        assert result.over_limit[0].total_days == 15

    def test_analyze_schedules_user_at_limit(self):
        """Test analysis with user exactly at the limit."""
        user = User(id="PUSER1", name="Test User", email="test@example.com")
        schedule = Schedule(id="PSCHED1", name="Test Schedule", timezone="UTC")

        # Create entries totaling exactly 10 days
        entries = []
        for day in range(1, 11):
            start = pytz.utc.localize(datetime(2026, 1, day, 0, 0, 0))
            end = pytz.utc.localize(datetime(2026, 1, day, 23, 59, 59))
            entries.append(ScheduleEntry(user=user, schedule=schedule, start=start, end=end))

        mock_client = Mock()
        mock_client.get_schedules_by_team.return_value = [schedule]
        mock_client.get_oncalls.return_value = entries

        result = analyze_schedules(
            team_ids=["TEAM1"], month=1, year=2026, max_days=10, client=mock_client
        )

        assert len(result.over_limit) == 0
        assert len(result.at_limit) == 1
        assert len(result.under_limit) == 0
        assert result.at_limit[0].user.id == "PUSER1"
        assert result.at_limit[0].total_days == 10

    def test_analyze_schedules_user_under_limit(self):
        """Test analysis with user under the limit."""
        user = User(id="PUSER1", name="Test User", email="test@example.com")
        schedule = Schedule(id="PSCHED1", name="Test Schedule", timezone="UTC")

        # Create entries totaling 5 days (under the 10 day limit)
        entries = []
        for day in range(1, 6):
            start = pytz.utc.localize(datetime(2026, 1, day, 0, 0, 0))
            end = pytz.utc.localize(datetime(2026, 1, day, 23, 59, 59))
            entries.append(ScheduleEntry(user=user, schedule=schedule, start=start, end=end))

        mock_client = Mock()
        mock_client.get_schedules_by_team.return_value = [schedule]
        mock_client.get_oncalls.return_value = entries

        result = analyze_schedules(
            team_ids=["TEAM1"], month=1, year=2026, max_days=10, client=mock_client
        )

        assert len(result.over_limit) == 0
        assert len(result.at_limit) == 0
        assert len(result.under_limit) == 1
        assert result.under_limit[0].user.id == "PUSER1"
        assert result.under_limit[0].total_days == 5

    def test_analyze_schedules_multiple_users(self):
        """Test analysis with multiple users in different categories."""
        user1 = User(id="PUSER1", name="User One", email="user1@example.com")
        user2 = User(id="PUSER2", name="User Two", email="user2@example.com")
        user3 = User(id="PUSER3", name="User Three", email="user3@example.com")
        schedule = Schedule(id="PSCHED1", name="Test Schedule", timezone="UTC")

        entries = []

        # User 1: 15 days (over limit)
        for day in range(1, 16):
            start = pytz.utc.localize(datetime(2026, 1, day, 0, 0, 0))
            end = pytz.utc.localize(datetime(2026, 1, day, 23, 59, 59))
            entries.append(ScheduleEntry(user=user1, schedule=schedule, start=start, end=end))

        # User 2: 10 days (at limit)
        for day in range(1, 11):
            start = pytz.utc.localize(datetime(2026, 1, day, 0, 0, 0))
            end = pytz.utc.localize(datetime(2026, 1, day, 23, 59, 59))
            entries.append(ScheduleEntry(user=user2, schedule=schedule, start=start, end=end))

        # User 3: 5 days (under limit)
        for day in range(1, 6):
            start = pytz.utc.localize(datetime(2026, 1, day, 0, 0, 0))
            end = pytz.utc.localize(datetime(2026, 1, day, 23, 59, 59))
            entries.append(ScheduleEntry(user=user3, schedule=schedule, start=start, end=end))

        mock_client = Mock()
        mock_client.get_schedules_by_team.return_value = [schedule]
        mock_client.get_oncalls.return_value = entries

        result = analyze_schedules(
            team_ids=["TEAM1"], month=1, year=2026, max_days=10, client=mock_client
        )

        assert len(result.over_limit) == 1
        assert len(result.at_limit) == 1
        assert len(result.under_limit) == 1

    def test_analyze_schedules_sorted_by_days(self):
        """Test that results are sorted by day count in descending order."""
        user1 = User(id="PUSER1", name="User One", email="user1@example.com")
        user2 = User(id="PUSER2", name="User Two", email="user2@example.com")
        user3 = User(id="PUSER3", name="User Three", email="user3@example.com")
        schedule = Schedule(id="PSCHED1", name="Test Schedule", timezone="UTC")

        entries = []

        # User 1: 15 days
        for day in range(1, 16):
            start = pytz.utc.localize(datetime(2026, 1, day, 0, 0, 0))
            end = pytz.utc.localize(datetime(2026, 1, day, 23, 59, 59))
            entries.append(ScheduleEntry(user=user1, schedule=schedule, start=start, end=end))

        # User 2: 20 days (more than user 1)
        for day in range(1, 21):
            start = pytz.utc.localize(datetime(2026, 1, day, 0, 0, 0))
            end = pytz.utc.localize(datetime(2026, 1, day, 23, 59, 59))
            entries.append(ScheduleEntry(user=user2, schedule=schedule, start=start, end=end))

        # User 3: 12 days
        for day in range(1, 13):
            start = pytz.utc.localize(datetime(2026, 1, day, 0, 0, 0))
            end = pytz.utc.localize(datetime(2026, 1, day, 23, 59, 59))
            entries.append(ScheduleEntry(user=user3, schedule=schedule, start=start, end=end))

        mock_client = Mock()
        mock_client.get_schedules_by_team.return_value = [schedule]
        mock_client.get_oncalls.return_value = entries

        result = analyze_schedules(
            team_ids=["TEAM1"], month=1, year=2026, max_days=10, client=mock_client
        )

        # All three users are over limit
        assert len(result.over_limit) == 3

        # Should be sorted by day count descending: User2 (20), User1 (15), User3 (12)
        assert result.over_limit[0].user.id == "PUSER2"
        assert result.over_limit[0].total_days == 20
        assert result.over_limit[1].user.id == "PUSER1"
        assert result.over_limit[1].total_days == 15
        assert result.over_limit[2].user.id == "PUSER3"
        assert result.over_limit[2].total_days == 12

    def test_analyze_schedules_multiple_schedules_per_user(self):
        """Test analysis with users on multiple schedules."""
        user = User(id="PUSER1", name="Test User", email="test@example.com")
        schedule1 = Schedule(id="PSCHED1", name="Primary Schedule", timezone="UTC")
        schedule2 = Schedule(id="PSCHED2", name="Secondary Schedule", timezone="UTC")

        entries = []

        # User on schedule 1 for 7 days
        for day in range(1, 8):
            start = pytz.utc.localize(datetime(2026, 1, day, 0, 0, 0))
            end = pytz.utc.localize(datetime(2026, 1, day, 23, 59, 59))
            entries.append(ScheduleEntry(user=user, schedule=schedule1, start=start, end=end))

        # User on schedule 2 for 5 days (total 12 days, over limit)
        for day in range(15, 20):
            start = pytz.utc.localize(datetime(2026, 1, day, 0, 0, 0))
            end = pytz.utc.localize(datetime(2026, 1, day, 23, 59, 59))
            entries.append(ScheduleEntry(user=user, schedule=schedule2, start=start, end=end))

        mock_client = Mock()
        mock_client.get_schedules_by_team.return_value = [schedule1, schedule2]
        mock_client.get_oncalls.return_value = entries

        result = analyze_schedules(
            team_ids=["TEAM1"], month=1, year=2026, max_days=10, client=mock_client
        )

        assert len(result.over_limit) == 1
        assert result.over_limit[0].total_days == 12
        # Schedule names should be combined
        assert "Primary Schedule" in result.over_limit[0].schedule_name
        assert "Secondary Schedule" in result.over_limit[0].schedule_name

    def test_analyze_schedules_includes_scheduled_dates(self):
        """Test that analysis includes sorted scheduled dates."""
        user = User(id="PUSER1", name="Test User", email="test@example.com")
        schedule = Schedule(id="PSCHED1", name="Test Schedule", timezone="UTC")

        entries = []
        for day in [5, 3, 1, 4, 2]:  # Out of order
            start = pytz.utc.localize(datetime(2026, 1, day, 0, 0, 0))
            end = pytz.utc.localize(datetime(2026, 1, day, 23, 59, 59))
            entries.append(ScheduleEntry(user=user, schedule=schedule, start=start, end=end))

        mock_client = Mock()
        mock_client.get_schedules_by_team.return_value = [schedule]
        mock_client.get_oncalls.return_value = entries

        result = analyze_schedules(
            team_ids=["TEAM1"], month=1, year=2026, max_days=10, client=mock_client
        )

        # Dates should be sorted
        dates = result.under_limit[0].scheduled_dates
        assert dates == sorted(dates)

    def test_analyze_schedules_calls_client_correctly(self):
        """Test that analyzer calls client methods with correct parameters."""
        mock_client = Mock()
        mock_client.get_schedules_by_team.return_value = [
            Schedule(id="PSCHED1", name="Test Schedule", timezone="UTC")
        ]
        mock_client.get_oncalls.return_value = []

        analyze_schedules(
            team_ids=["TEAM1", "TEAM2"], month=2, year=2026, max_days=15, client=mock_client
        )

        # Verify client was called with correct team IDs
        mock_client.get_schedules_by_team.assert_called_once_with(["TEAM1", "TEAM2"])

        # Verify get_oncalls was called with correct schedule IDs and date range
        assert mock_client.get_oncalls.called
        call_args = mock_client.get_oncalls.call_args
        schedule_ids = call_args[0][0]
        since = call_args[0][1]
        until = call_args[0][2]

        assert schedule_ids == ["PSCHED1"]
        assert since.month == 2
        assert since.year == 2026
        assert until.month == 2
        assert until.year == 2026

    def test_analyze_schedules_excluded_users(self):
        """Test that excluded users are filtered from the results."""
        user1 = User(id="PUSER1", name="User One", email="user1@example.com")
        user2 = User(id="PUSER2", name="User Two", email="user2@example.com")
        user3 = User(id="PUSER3", name="User Three", email="user3@example.com")
        schedule = Schedule(id="PSCHED1", name="Test Schedule", timezone="UTC")

        entries = []

        # All three users: 15 days (over limit)
        for user in [user1, user2, user3]:
            for day in range(1, 16):
                start = pytz.utc.localize(datetime(2026, 1, day, 0, 0, 0))
                end = pytz.utc.localize(datetime(2026, 1, day, 23, 59, 59))
                entries.append(ScheduleEntry(user=user, schedule=schedule, start=start, end=end))

        mock_client = Mock()
        mock_client.get_schedules_by_team.return_value = [schedule]
        mock_client.get_oncalls.return_value = entries

        # Exclude user1 and user2
        result = analyze_schedules(
            team_ids=["TEAM1"],
            month=1,
            year=2026,
            max_days=10,
            client=mock_client,
            excluded_users=["user1@example.com", "user2@example.com"],
        )

        # Only user3 should appear (user1 and user2 are excluded)
        assert len(result.over_limit) == 1
        assert result.over_limit[0].user.id == "PUSER3"
        assert result.over_limit[0].user.email == "user3@example.com"

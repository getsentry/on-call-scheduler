"""Tests for output formatting."""

import json
from datetime import date
from io import StringIO
from unittest.mock import patch

import pytest

from oncall_scheduler.models import AnalysisResult, OnCallReport, User
from oncall_scheduler.output.formatter import (
    _format_date_ranges,
    format_json,
    format_table,
    format_table_verbose,
)


class TestFormatDateRanges:
    """Tests for the _format_date_ranges function."""

    def test_format_single_date(self):
        """Test formatting a single date."""
        dates = [date(2026, 1, 15)]

        result = _format_date_ranges(dates)

        assert result == "Jan 15"

    def test_format_consecutive_dates(self):
        """Test formatting consecutive dates as a range."""
        dates = [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 4)]

        result = _format_date_ranges(dates)

        assert result == "Jan 01-04"

    def test_format_multiple_ranges(self):
        """Test formatting multiple separate ranges."""
        dates = [
            date(2026, 1, 1),
            date(2026, 1, 2),
            date(2026, 1, 3),
            date(2026, 1, 10),
            date(2026, 1, 11),
            date(2026, 1, 15),
        ]

        result = _format_date_ranges(dates)

        assert result == "Jan 01-03, Jan 10-11, Jan 15"

    def test_format_empty_list(self):
        """Test formatting an empty list."""
        dates = []

        result = _format_date_ranges(dates)

        assert result == "None"

    def test_format_gap_in_dates(self):
        """Test formatting dates with gaps."""
        dates = [date(2026, 1, 1), date(2026, 1, 5), date(2026, 1, 10)]

        result = _format_date_ranges(dates)

        assert result == "Jan 01, Jan 05, Jan 10"

    def test_format_across_months(self):
        """Test formatting dates across month boundaries."""
        dates = [
            date(2026, 1, 30),
            date(2026, 1, 31),
            date(2026, 2, 1),
            date(2026, 2, 2),
        ]

        result = _format_date_ranges(dates)

        assert result == "Jan 30-31, Feb 01-02"


class TestFormatJson:
    """Tests for the format_json function."""

    def test_format_json_empty_result(self):
        """Test JSON formatting with empty result."""
        result = AnalysisResult(month=1, year=2026, max_days=10)

        json_output = format_json(result)
        parsed = json.loads(json_output)

        assert parsed["month"] == 1
        assert parsed["year"] == 2026
        assert parsed["max_days"] == 10
        assert parsed["over_limit"] == []
        assert parsed["at_limit"] == []
        assert parsed["under_limit"] == []
        assert parsed["summary"]["over_limit_count"] == 0

    def test_format_json_with_reports(self):
        """Test JSON formatting with reports."""
        user = User(id="PUSER1", name="Test User", email="test@example.com", html_url="https://example.com")

        report = OnCallReport(
            user=user,
            schedule_name="Test Schedule",
            total_days=15,
            scheduled_dates=[date(2026, 1, 1), date(2026, 1, 2)],
        )

        result = AnalysisResult(month=1, year=2026, max_days=10, over_limit=[report])

        json_output = format_json(result)
        parsed = json.loads(json_output)

        assert len(parsed["over_limit"]) == 1
        assert parsed["over_limit"][0]["user"]["id"] == "PUSER1"
        assert parsed["over_limit"][0]["total_days"] == 15
        assert parsed["over_limit"][0]["scheduled_dates"] == ["2026-01-01", "2026-01-02"]
        assert parsed["summary"]["over_limit_count"] == 1

    def test_format_json_is_valid(self):
        """Test that formatted output is valid JSON."""
        result = AnalysisResult(month=1, year=2026, max_days=10)

        json_output = format_json(result)

        # Should not raise an exception
        json.loads(json_output)


class TestFormatTable:
    """Tests for the format_table function."""

    @patch("oncall_scheduler.output.formatter.Console")
    def test_format_table_empty_result(self, mock_console_class):
        """Test table formatting with empty result."""
        mock_console = mock_console_class.return_value
        result = AnalysisResult(month=1, year=2026, max_days=10)

        format_table(result)

        # Verify console.print was called
        assert mock_console.print.called

    @patch("oncall_scheduler.output.formatter.Console")
    def test_format_table_with_over_limit(self, mock_console_class):
        """Test table formatting with users over limit."""
        mock_console = mock_console_class.return_value
        user = User(id="PUSER1", name="Test User", email="test@example.com")

        report = OnCallReport(
            user=user,
            schedule_name="Test Schedule",
            total_days=15,
            scheduled_dates=[date(2026, 1, 1), date(2026, 1, 2)],
        )

        result = AnalysisResult(month=1, year=2026, max_days=10, over_limit=[report])

        format_table(result)

        # Verify console was used
        assert mock_console.print.called

    @patch("oncall_scheduler.output.formatter.Console")
    def test_format_table_with_at_limit(self, mock_console_class):
        """Test table formatting with users at limit."""
        mock_console = mock_console_class.return_value
        user = User(id="PUSER1", name="Test User", email="test@example.com")

        report = OnCallReport(
            user=user,
            schedule_name="Test Schedule",
            total_days=10,
            scheduled_dates=[],
        )

        result = AnalysisResult(month=1, year=2026, max_days=10, at_limit=[report])

        format_table(result)

        assert mock_console.print.called

    @patch("oncall_scheduler.output.formatter.Console")
    def test_format_table_with_under_limit_collapsed(self, mock_console_class):
        """Test table formatting shows under limit count without details."""
        mock_console = mock_console_class.return_value
        user = User(id="PUSER1", name="Test User", email="test@example.com")

        report = OnCallReport(
            user=user,
            schedule_name="Test Schedule",
            total_days=5,
            scheduled_dates=[],
        )

        result = AnalysisResult(month=1, year=2026, max_days=10, under_limit=[report])

        format_table(result)

        # Should mention "use --verbose to see details"
        print_calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("--verbose" in str(call) for call in print_calls)

    @patch("oncall_scheduler.output.formatter.Console")
    def test_format_table_displays_summary(self, mock_console_class):
        """Test that summary is displayed."""
        mock_console = mock_console_class.return_value
        result = AnalysisResult(month=1, year=2026, max_days=10)

        format_table(result)

        # Should display summary
        print_calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Summary" in str(call) for call in print_calls)


class TestFormatTableVerbose:
    """Tests for the format_table_verbose function."""

    @patch("oncall_scheduler.output.formatter.Console")
    def test_format_table_verbose_shows_under_limit(self, mock_console_class):
        """Test verbose mode shows all under limit users."""
        mock_console = mock_console_class.return_value
        user = User(id="PUSER1", name="Test User", email="test@example.com")

        report = OnCallReport(
            user=user,
            schedule_name="Test Schedule",
            total_days=5,
            scheduled_dates=[],
        )

        result = AnalysisResult(month=1, year=2026, max_days=10, under_limit=[report])

        format_table_verbose(result)

        # Verbose mode should show detailed table, not just count
        assert mock_console.print.called
        # Should NOT mention "--verbose" since we're already in verbose mode
        print_calls = [str(call) for call in mock_console.print.call_args_list]
        has_verbose_mention = any("--verbose" in str(call) for call in print_calls)
        assert not has_verbose_mention

    @patch("oncall_scheduler.output.formatter.Console")
    def test_format_table_verbose_with_all_categories(self, mock_console_class):
        """Test verbose mode with users in all categories."""
        mock_console = mock_console_class.return_value

        user1 = User(id="PUSER1", name="User One", email="user1@example.com")
        user2 = User(id="PUSER2", name="User Two", email="user2@example.com")
        user3 = User(id="PUSER3", name="User Three", email="user3@example.com")

        over_report = OnCallReport(user=user1, schedule_name="Schedule A", total_days=15, scheduled_dates=[])
        at_report = OnCallReport(user=user2, schedule_name="Schedule B", total_days=10, scheduled_dates=[])
        under_report = OnCallReport(user=user3, schedule_name="Schedule C", total_days=5, scheduled_dates=[])

        result = AnalysisResult(
            month=1,
            year=2026,
            max_days=10,
            over_limit=[over_report],
            at_limit=[at_report],
            under_limit=[under_report],
        )

        format_table_verbose(result)

        assert mock_console.print.called
        # Should show all three categories
        print_calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("OVER LIMIT" in str(call) for call in print_calls)
        assert any("AT LIMIT" in str(call) for call in print_calls)
        assert any("UNDER LIMIT" in str(call) for call in print_calls)

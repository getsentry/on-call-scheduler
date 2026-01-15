"""Output formatting for analysis results."""

import calendar
import json
from datetime import date
from typing import List

from rich.console import Console
from rich.table import Table

from oncall_scheduler.models import AnalysisResult, MultiMonthAnalysisResult, OnCallReport


def _format_date_ranges(dates: List[date]) -> str:
    """Format a list of dates into compact ranges.

    Args:
        dates: Sorted list of dates

    Returns:
        String representation of date ranges (e.g., "Jan 1-5, 10-12, 15")
    """
    if not dates:
        return "None"

    ranges = []
    start = dates[0]
    prev = dates[0]

    for current in dates[1:] + [None]:  # Add None to trigger final range
        if current is None or (current - prev).days > 1:
            # End of a range
            if start == prev:
                ranges.append(start.strftime("%b %d"))
            else:
                ranges.append(f"{start.strftime('%b %d')}-{prev.strftime('%d')}")
            if current is not None:
                start = current
        prev = current if current is not None else prev

    return ", ".join(ranges)


def _add_rows_to_table(
    table: Table,
    reports: List[OnCallReport],
    status: str,
    style: str,
    month_label: str | None = None,
) -> None:
    """Add rows to the table with consistent styling.

    Args:
        table: Rich Table to add rows to
        reports: List of OnCallReport objects
        status: Status label (e.g., "Over", "At", "Under")
        style: Rich style string for the row
        month_label: Optional month label for multi-month tables
    """
    for report in reports:
        row = [
            f"[{style}]{report.user.name}[/{style}]",
            f"[{style} bold]{report.total_days}[/{style} bold]",
            f"[{style}]{report.schedule_name}[/{style}]",
            f"[{style}]{_format_date_ranges(report.scheduled_dates)}[/{style}]",
            f"[{style}]{status}[/{style}]",
        ]
        if month_label is not None:
            row.insert(0, f"[{style}]{month_label}[/{style}]")
        table.add_row(*row)


def format_table(result: AnalysisResult) -> None:
    """Format and display analysis results as a Rich table.

    Args:
        result: AnalysisResult to display
    """
    console = Console()

    # Header
    month_name = calendar.month_name[result.month]
    console.print()
    console.print(
        f"[bold cyan]PagerDuty On-Call Analysis - {month_name} {result.year}[/bold cyan]"
    )
    console.print(f"[cyan]Max Days Allowed: {result.max_days}[/cyan]")
    console.print()

    # Combined table
    table = Table(show_header=True, header_style="bold")
    table.add_column("User")
    table.add_column("Days", justify="center")
    table.add_column("Schedule")
    table.add_column("Dates")
    table.add_column("Status", justify="center")

    # Add over limit rows (red)
    _add_rows_to_table(table, result.over_limit, "Over", "red")

    # Add at limit rows (yellow)
    _add_rows_to_table(table, result.at_limit, "At", "yellow")

    # Show collapsed message for under limit in non-verbose mode
    if result.over_limit or result.at_limit:
        console.print(table)
        console.print()

    if result.under_limit:
        console.print(
            f"[green]Users under limit: {len(result.under_limit)} "
            f"(use --verbose to see details)[/green]"
        )

    # Summary
    console.print()
    console.print(
        f"[bold]Summary:[/bold] [red]{len(result.over_limit)} over limit[/red], "
        f"[yellow]{len(result.at_limit)} at limit[/yellow], "
        f"[green]{len(result.under_limit)} under limit[/green]"
    )
    console.print()


def format_table_verbose(result: AnalysisResult) -> None:
    """Format and display analysis results as a Rich table with verbose output.

    Args:
        result: AnalysisResult to display
    """
    console = Console()

    # Header
    month_name = calendar.month_name[result.month]
    console.print()
    console.print(
        f"[bold cyan]PagerDuty On-Call Analysis - {month_name} {result.year}[/bold cyan]"
    )
    console.print(f"[cyan]Max Days Allowed: {result.max_days}[/cyan]")
    console.print()

    # Combined table
    table = Table(show_header=True, header_style="bold")
    table.add_column("User")
    table.add_column("Days", justify="center")
    table.add_column("Schedule")
    table.add_column("Dates")
    table.add_column("Status", justify="center")

    # Add over limit rows (red)
    _add_rows_to_table(table, result.over_limit, "Over", "red")

    # Add at limit rows (yellow)
    _add_rows_to_table(table, result.at_limit, "At", "yellow")

    # Add under limit rows (green) - verbose shows all
    _add_rows_to_table(table, result.under_limit, "Under", "green")

    if result.over_limit or result.at_limit or result.under_limit:
        console.print(table)
        console.print()

    # Summary
    console.print()
    console.print(
        f"[bold]Summary:[/bold] [red]{len(result.over_limit)} over limit[/red], "
        f"[yellow]{len(result.at_limit)} at limit[/yellow], "
        f"[green]{len(result.under_limit)} under limit[/green]"
    )
    console.print()


def format_multi_month_table(result: MultiMonthAnalysisResult) -> None:
    """Format and display multi-month analysis results as a Rich table.

    Args:
        result: MultiMonthAnalysisResult to display
    """
    console = Console()

    # Header
    if result.results:
        first = result.results[0]
        last = result.results[-1]
        first_month = calendar.month_name[first.month]
        last_month = calendar.month_name[last.month]
        console.print()
        console.print(
            f"[bold cyan]PagerDuty On-Call Analysis - "
            f"{first_month} {first.year} to {last_month} {last.year}[/bold cyan]"
        )
    console.print(f"[cyan]Max Days Allowed: {result.max_days}[/cyan]")
    console.print()

    # Combined table with Month column
    table = Table(show_header=True, header_style="bold")
    table.add_column("Month")
    table.add_column("User")
    table.add_column("Days", justify="center")
    table.add_column("Schedule")
    table.add_column("Dates")
    table.add_column("Status", justify="center")

    has_data = False
    total_under = 0

    for month_result in result.results:
        month_label = f"{calendar.month_abbr[month_result.month]} {month_result.year}"

        # Add over limit rows (red)
        _add_rows_to_table(table, month_result.over_limit, "Over", "red", month_label)

        # Add at limit rows (yellow)
        _add_rows_to_table(table, month_result.at_limit, "At", "yellow", month_label)

        if month_result.over_limit or month_result.at_limit:
            has_data = True

        total_under += len(month_result.under_limit)

    if has_data:
        console.print(table)
        console.print()

    if total_under > 0:
        console.print(
            f"[green]Users under limit: {total_under} "
            f"(use --verbose to see details)[/green]"
        )

    # Summary
    total_over = sum(len(r.over_limit) for r in result.results)
    total_at = sum(len(r.at_limit) for r in result.results)
    console.print()
    console.print(
        f"[bold]Summary ({len(result.results)} months):[/bold] "
        f"[red]{total_over} over limit[/red], "
        f"[yellow]{total_at} at limit[/yellow], "
        f"[green]{total_under} under limit[/green]"
    )
    console.print()


def format_multi_month_table_verbose(result: MultiMonthAnalysisResult) -> None:
    """Format and display multi-month analysis results with verbose output.

    Args:
        result: MultiMonthAnalysisResult to display
    """
    console = Console()

    # Header
    if result.results:
        first = result.results[0]
        last = result.results[-1]
        first_month = calendar.month_name[first.month]
        last_month = calendar.month_name[last.month]
        console.print()
        console.print(
            f"[bold cyan]PagerDuty On-Call Analysis - "
            f"{first_month} {first.year} to {last_month} {last.year}[/bold cyan]"
        )
    console.print(f"[cyan]Max Days Allowed: {result.max_days}[/cyan]")
    console.print()

    # Combined table with Month column
    table = Table(show_header=True, header_style="bold")
    table.add_column("Month")
    table.add_column("User")
    table.add_column("Days", justify="center")
    table.add_column("Schedule")
    table.add_column("Dates")
    table.add_column("Status", justify="center")

    has_data = False

    for month_result in result.results:
        month_label = f"{calendar.month_abbr[month_result.month]} {month_result.year}"

        # Add over limit rows (red)
        _add_rows_to_table(table, month_result.over_limit, "Over", "red", month_label)

        # Add at limit rows (yellow)
        _add_rows_to_table(table, month_result.at_limit, "At", "yellow", month_label)

        # Add under limit rows (green) - verbose shows all
        _add_rows_to_table(table, month_result.under_limit, "Under", "green", month_label)

        if month_result.over_limit or month_result.at_limit or month_result.under_limit:
            has_data = True

    if has_data:
        console.print(table)
        console.print()

    # Summary
    total_over = sum(len(r.over_limit) for r in result.results)
    total_at = sum(len(r.at_limit) for r in result.results)
    total_under = sum(len(r.under_limit) for r in result.results)
    console.print()
    console.print(
        f"[bold]Summary ({len(result.results)} months):[/bold] "
        f"[red]{total_over} over limit[/red], "
        f"[yellow]{total_at} at limit[/yellow], "
        f"[green]{total_under} under limit[/green]"
    )
    console.print()


def format_json(result: AnalysisResult | MultiMonthAnalysisResult) -> str:
    """Format analysis results as JSON.

    Args:
        result: AnalysisResult or MultiMonthAnalysisResult to format

    Returns:
        JSON string representation
    """
    return json.dumps(result.to_dict(), indent=2)

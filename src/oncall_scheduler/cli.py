"""Command-line interface for the on-call scheduler application."""

import json
import logging
import sys
from datetime import datetime
from typing import List, Optional

import click
import sentry_sdk
from pydantic import ValidationError

from oncall_scheduler.analysis.analyzer import analyze_multiple_months, analyze_schedules
from oncall_scheduler.api.client import PagerDutyClient
from oncall_scheduler.api.exceptions import (
    AuthenticationError,
    PagerDutyAPIError,
    ResourceNotFoundError,
)
from oncall_scheduler.config import load_pto_data, load_settings
from oncall_scheduler.models import PTOEntry
from oncall_scheduler.output.formatter import (
    format_json,
    format_multi_month_table,
    format_multi_month_table_verbose,
    format_table,
    format_table_verbose,
)

# Version
__version__ = "0.1.0"


def setup_logging(verbose: bool = False):
    """Configure logging for the application.

    Args:
        verbose: If True, set log level to INFO, otherwise ERROR
    """
    level = logging.INFO if verbose else logging.ERROR
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )


def init_sentry(dsn: Optional[str], environment: str, verbose: bool = False):
    """Initialize Sentry SDK for error tracking.

    Args:
        dsn: Sentry DSN (Data Source Name)
        environment: Environment name (e.g., "production", "development")
        verbose: If True, log Sentry initialization
    """
    if dsn:
        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=f"oncall-scheduler@{__version__}",
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0,
        )
        if verbose:
            logging.info(f"Sentry initialized for environment: {environment}")
    else:
        if verbose:
            logging.info("Sentry DSN not provided, error tracking disabled")


@click.group()
@click.version_option(version=__version__)
def cli():
    """PagerDuty On-Call Schedule Manager.

    Analyze on-call schedules and identify users exceeding configured limits.
    """
    pass


@cli.command()
@click.option(
    "--team",
    "-t",
    "teams",
    multiple=True,
    help="PagerDuty team ID to analyze (can be specified multiple times)",
)
@click.option(
    "--max-days",
    "-m",
    type=int,
    help="Maximum number of on-call days per month (overrides config)",
)
@click.option(
    "--month",
    type=click.IntRange(1, 12),
    help="Month to analyze (1-12, default: current month)",
)
@click.option(
    "--year",
    type=int,
    help="Year to analyze (default: current year)",
)
@click.option(
    "--output",
    "-o",
    type=click.Choice(["table", "json"], case_sensitive=False),
    default="table",
    help="Output format (default: table)",
)
@click.option(
    "--months",
    "-n",
    type=click.IntRange(1, 12),
    default=1,
    help="Number of months to analyze starting from the specified month (default: 1)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose output (show all users including under limit)",
)
@click.option(
    "--timezone",
    "-z",
    "timezones",
    multiple=True,
    help="Only include users in specified timezones (can be specified multiple times, e.g. --timezone America/New_York --timezone Europe/London)",
)
@click.option(
    "--exclude-user",
    "-e",
    "excluded_users",
    multiple=True,
    help="Exclude specific users from over-limit reporting (can be specified multiple times, e.g. --exclude-user user1@example.com --exclude-user user2@example.com)",
)
@click.option(
    "--exclude-schedule",
    "-s",
    "excluded_schedules",
    multiple=True,
    help="Exclude specific schedules from analysis by ID or name (can be specified multiple times, e.g. --exclude-schedule SCHEDULE1 --exclude-schedule 'Primary On-Call')",
)
@click.option(
    "--pto-file",
    "-p",
    "pto_file",
    type=click.Path(exists=True),
    help="Path to JSON file containing PTO data to check for on-call conflicts",
)
def check(
    teams: tuple,
    max_days: Optional[int],
    month: Optional[int],
    year: Optional[int],
    months: int,
    output: str,
    verbose: bool,
    timezones: tuple,
    excluded_users: tuple,
    excluded_schedules: tuple,
    pto_file: Optional[str],
):
    """Check on-call schedules and identify users over the limit."""
    # Setup logging
    setup_logging(verbose)

    try:
        # Load configuration
        settings = load_settings()

        # Initialize Sentry for error tracking
        init_sentry(settings.sentry_dsn, settings.sentry_environment, verbose)

    except ValidationError as e:
        click.echo("Configuration error:", err=True)
        for error in e.errors():
            field = " -> ".join(str(loc) for loc in error["loc"])
            click.echo(f"  {field}: {error['msg']}", err=True)
        click.echo(
            "\nPlease check your .env file or set the required environment variables.",
            err=True,
        )
        click.echo("See .env.example for reference.", err=True)
        sys.exit(1)

    # Determine team IDs (CLI args take precedence over config)
    team_list: List[str] = list(teams) if teams else settings.get_team_ids()

    if not team_list:
        click.echo(
            "Error: No team IDs specified. "
            "Use --team option or set PAGERDUTY_TEAM_IDS in .env",
            err=True,
        )
        sys.exit(1)

    # Determine max days (CLI arg takes precedence)
    max_days_limit = max_days if max_days is not None else settings.oncall_max_days

    # Determine timezones of concern (CLI args take precedence over config)
    timezones_of_concern_list: List[str] = list(timezones) if timezones else settings.get_timezones_of_concern()

    # Determine excluded users (CLI args take precedence over config)
    excluded_users_list: List[str] = list(excluded_users) if excluded_users else settings.get_excluded_users()

    # Determine excluded schedules (CLI args take precedence over config)
    excluded_schedules_list: List[str] = list(excluded_schedules) if excluded_schedules else settings.get_excluded_schedules()

    # Load PTO data if provided
    pto_by_email: dict[str, List[PTOEntry]] = {}
    if pto_file:
        try:
            pto_data = load_pto_data(pto_file)
            for user_email, periods in pto_data.items():
                pto_by_email[user_email] = [
                    PTOEntry.from_dict(user_email, period) for period in periods
                ]
        except FileNotFoundError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)
        except (json.JSONDecodeError, KeyError, ValueError, AttributeError, TypeError) as e:
            click.echo(f"Error parsing PTO file: {e}", err=True)
            sys.exit(1)

    # Determine month and year (default to current)
    now = datetime.now()
    target_month = month if month is not None else now.month
    target_year = year if year is not None else now.year

    if verbose:
        click.echo(f"Teams: {', '.join(team_list)}", err=True)
        if months > 1:
            click.echo(f"Period: {target_month}/{target_year} + {months - 1} months", err=True)
        else:
            click.echo(f"Period: {target_month}/{target_year}", err=True)
        click.echo(f"Max days: {max_days_limit}", err=True)
        if timezones_of_concern_list:
            click.echo(f"Timezones of concern: {', '.join(timezones_of_concern_list)}", err=True)
        if excluded_users_list:
            click.echo(f"Excluded users: {', '.join(excluded_users_list)}", err=True)
        if excluded_schedules_list:
            click.echo(f"Excluded schedules: {', '.join(excluded_schedules_list)}", err=True)
        if pto_by_email:
            total_periods = sum(len(periods) for periods in pto_by_email.values())
            click.echo(f"PTO: {len(pto_by_email)} users, {total_periods} periods loaded", err=True)
        click.echo("", err=True)

    try:
        # Initialize API client
        client = PagerDutyClient(api_key=settings.pagerduty_api_key)

        # Test connection
        if verbose:
            click.echo("Testing API connection...", err=True)
        client.test_connection()
        if verbose:
            click.echo("API connection successful\n", err=True)

        # Get user timezone configuration
        user_timezones = settings.get_user_timezones()
        workday_end_hour = settings.workday_end_hour

        # Run analysis
        if months > 1:
            result = analyze_multiple_months(
                team_ids=team_list,
                start_month=target_month,
                start_year=target_year,
                num_months=months,
                max_days=max_days_limit,
                client=client,
                workday_end_hour=workday_end_hour,
                user_timezones=user_timezones,
                timezones_of_concern=timezones_of_concern_list,
                excluded_users=excluded_users_list,
                excluded_schedules=excluded_schedules_list,
                pto_by_email=pto_by_email,
            )

            # Display results
            if output == "json":
                click.echo(format_json(result))
            else:
                if verbose:
                    format_multi_month_table_verbose(result)
                else:
                    format_multi_month_table(result)
        else:
            result = analyze_schedules(
                team_ids=team_list,
                month=target_month,
                year=target_year,
                max_days=max_days_limit,
                client=client,
                workday_end_hour=workday_end_hour,
                user_timezones=user_timezones,
                timezones_of_concern=timezones_of_concern_list,
                excluded_users=excluded_users_list,
                excluded_schedules=excluded_schedules_list,
                pto_by_email=pto_by_email,
            )

            # Display results
            if output == "json":
                click.echo(format_json(result))
            else:
                if verbose:
                    format_table_verbose(result)
                else:
                    format_table(result)

    except AuthenticationError as e:
        click.echo(f"\nAuthentication failed: {e}", err=True)
        click.echo("\nPlease check your PAGERDUTY_API_KEY.", err=True)
        click.echo(
            "Get your API key from: https://support.pagerduty.com/docs/api-access-keys",
            err=True,
        )
        sys.exit(1)

    except ResourceNotFoundError as e:
        click.echo(f"\nResource not found: {e}", err=True)
        click.echo("\nPlease check that the team IDs are correct.", err=True)
        sys.exit(1)

    except PagerDutyAPIError as e:
        click.echo(f"\nPagerDuty API error: {e}", err=True)
        sys.exit(1)

    except Exception as e:
        click.echo(f"\nUnexpected error: {e}", err=True)
        if verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


@cli.command()
def version():
    """Show the application version."""
    click.echo(f"oncall-scheduler version {__version__}")


if __name__ == "__main__":
    cli()

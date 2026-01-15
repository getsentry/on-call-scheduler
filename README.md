# PagerDuty On-Call Scheduler

A Python CLI tool for analyzing PagerDuty on-call schedules and identifying team members who exceed configurable on-call day limits per month.

## Features

- Fetch on-call schedules by PagerDuty team
- Calculate on-call days per user for a specified month
- Identify users exceeding configurable daily limits
- Beautiful color-coded terminal output using Rich
- JSON output support for automation and scripting
- Timezone-aware date calculations
- Configurable via environment variables or CLI arguments

## Installation

### Prerequisites

- Python 3.12 or higher
- [uv](https://github.com/astral-sh/uv) (fast Python package installer)
- PagerDuty API key

### Install with uv

```bash
# Clone the repository
git clone <repository-url>
cd on-call-scheduler

# Install dependencies using uv
uv sync

# The tool is now ready to use
uv run oncall-scheduler --help
```

### Install in development mode

```bash
# Install with development dependencies
uv sync --extra dev

# Run tests
uv run pytest
```

## Configuration

### PagerDuty API Key

1. Log in to your PagerDuty account
2. Navigate to **Integrations** → **API Access Keys** (General API token) or **My Profile** → **User Settings** (Personal API token).
3. Create a new API key with read permissions
4. Copy the API key for use in configuration

### Environment Variables

Create a `.env` file in the project root (see `.env.example`):

```bash
# Required
PAGERDUTY_API_KEY=your_api_key_here

# Optional (can also be specified via CLI)
PAGERDUTY_TEAM_IDS=TEAM1,TEAM2,TEAM3
ONCALL_MAX_DAYS=10

# Optional: Sentry error tracking
SENTRY_DSN=https://your-sentry-dsn@sentry.io/project-id
SENTRY_ENVIRONMENT=production
```

### Configuration Priority

1. CLI arguments (highest priority)
2. Environment variables
3. .env file
4. Default values (lowest priority)

### Sentry Error Tracking

The application includes built-in Sentry integration for error tracking and monitoring:

1. **Create a Sentry Project**: Sign up at [sentry.io](https://sentry.io) and create a new project
2. **Get your DSN**: Navigate to **Settings** → **Projects** → **[Your Project]** → **Client Keys (DSN)**
3. **Configure**: Add the `SENTRY_DSN` to your `.env` file
4. **Optional**: Set `SENTRY_ENVIRONMENT` to differentiate between environments (e.g., "production", "staging", "development")

When configured, the application will automatically:
- Capture and report unhandled exceptions
- Track performance metrics
- Provide detailed error context and stack traces
- Associate errors with specific releases

To disable Sentry, simply omit the `SENTRY_DSN` environment variable.

## Usage

### Basic Usage

Check on-call schedules for the current month:

```bash
uv run oncall-scheduler check --team PXXXXXX
```

### Specify Multiple Teams

```bash
uv run oncall-scheduler check --team TEAM1 --team TEAM2 --team TEAM3
```

### Custom Month and Year

```bash
uv run oncall-scheduler check --team PXXXXXX --month 2 --year 2026
```

### Custom Day Limit

```bash
uv run oncall-scheduler check --team PXXXXXX --max-days 15
```

### Analyze Multiple Months

Analyze the next 3 months starting from the current month:

```bash
uv run oncall-scheduler check --team PXXXXXX --months 3
```

Analyze 6 months starting from a specific month:

```bash
uv run oncall-scheduler check --team PXXXXXX --month 1 --year 2026 --months 6
```

### Verbose Output

Show all users including those under the limit:

```bash
uv run oncall-scheduler check --team PXXXXXX --verbose
```

### JSON Output

Output results as JSON for scripting:

```bash
uv run oncall-scheduler check --team PXXXXXX --output json
```

### Using with jq

```bash
# Get names of users over the limit
uv run oncall-scheduler check --team PXXXXXX --output json | jq '.over_limit[].user.name'

# Count users over limit
uv run oncall-scheduler check --team PXXXXXX --output json | jq '.over_limit | length'
```

## Output Examples

### Table Output (Default)

```
PagerDuty On-Call Analysis - January 2026
Max Days Allowed: 10

┏━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ User             ┃ Days ┃ Schedule          ┃ Dates               ┃ Status ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ Alice Smith      │ 14   │ Primary On-Call   │ Jan 01-07, 15-21    │ Over   │  (red)
│ Bob Jones        │ 12   │ Secondary On-Call │ Jan 05-10, 20-25    │ Over   │  (red)
│ Carol White      │ 10   │ Primary On-Call   │ Jan 08-12, 22-26    │ At     │  (yellow)
└──────────────────┴──────┴───────────────────┴─────────────────────┴────────┘

Users under limit: 5 (use --verbose to see details)

Summary: 2 over limit, 1 at limit, 5 under limit
```

### JSON Output

```json
{
  "month": 1,
  "year": 2026,
  "max_days": 10,
  "over_limit": [
    {
      "user": {
        "id": "PXXXXXX",
        "name": "Alice Smith",
        "email": "alice@example.com",
        "html_url": "https://example.pagerduty.com/users/PXXXXXX"
      },
      "schedule_name": "Primary On-Call",
      "total_days": 14,
      "scheduled_dates": ["2026-01-01", "2026-01-02", "..."]
    }
  ],
  "at_limit": [...],
  "under_limit": [...],
  "summary": {
    "over_limit_count": 2,
    "at_limit_count": 1,
    "under_limit_count": 5
  }
}
```

## Automation

### Cron Job

Run daily at 9 AM:

```bash
0 9 * * * cd /path/to/on-call-scheduler && /path/to/uv run oncall-scheduler check >> /var/log/oncall-check.log 2>&1
```

### Integration with Slack/Email

Use the JSON output to integrate with notification systems:

```bash
#!/bin/bash
RESULT=$(uv run oncall-scheduler check --team PXXXXXX --output json)
OVER_COUNT=$(echo "$RESULT" | jq '.summary.over_limit_count')

if [ "$OVER_COUNT" -gt 0 ]; then
    # Send alert to Slack, email, etc.
    echo "$RESULT" | jq '.over_limit[]' | curl -X POST -H 'Content-Type: application/json' \
        -d @- https://hooks.slack.com/services/YOUR/WEBHOOK/URL
fi
```

## Development

### Project Structure

```
src/
└── oncall_scheduler/
    ├── __init__.py
    ├── __main__.py          # Entry point
    ├── cli.py               # Click CLI interface
    ├── config.py            # Configuration management
    ├── models.py            # Data models
    ├── api/
    │   ├── client.py       # PagerDuty API wrapper
    │   └── exceptions.py   # Custom exceptions
    ├── analysis/
    │   ├── analyzer.py     # Main analysis orchestrator
    │   └── calculator.py   # On-call days calculator
    └── output/
        └── formatter.py    # Output formatting
```

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src/oncall_scheduler --cov-report=term-missing

# Run specific test file
uv run pytest tests/test_calculator.py
```

### Code Quality

```bash
# Format code
uv run black src/oncall_scheduler tests

# Lint code
uv run ruff check src/oncall_scheduler tests

# Type checking
uv run mypy src/oncall_scheduler
```

## Troubleshooting

### Authentication Errors

```
Error: Authentication failed
```

**Solution**: Check that your `PAGERDUTY_API_KEY` is correct and has the necessary permissions.

### Team Not Found

```
Error: Resource not found: Team PXXXXXX not found
```

**Solution**: Verify the team ID is correct. You can find team IDs in the PagerDuty web UI under Configuration → Teams.

### No Schedules Found

```
Warning: No schedules found for teams: [PXXXXXX]
```

**Solution**: The team might not have any associated schedules. Check that the team has schedules configured in PagerDuty.

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Support

For issues and questions:
- GitHub Issues: [Create an issue](https://github.com/your-org/on-call-scheduler/issues)
- PagerDuty API Documentation: https://developer.pagerduty.com/

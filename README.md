# PagerDuty On-Call Scheduler

A Python CLI tool for analyzing PagerDuty on-call schedules and identifying team members who exceed configurable on-call day limits per month.

## Features

- Fetch on-call schedules by PagerDuty team
- **Timezone-aware per-user calculations** - each user's on-call time is calculated in their local timezone
- **After-hours only counting** - only counts days where on-call coverage extends past standard workday hours (configurable, default: 5 PM)
- Calculate on-call days per user for a specified month
- Identify users exceeding configurable daily limits
- Beautiful color-coded terminal output using Rich
- JSON output support for automation and scripting
- Configurable via environment variables or CLI arguments
- **Rotation planning (`plan`, experimental)** - generate a weekly rotation that stays within the same day limit, with time-zone and fairness goals (see [Planning a Rotation](#planning-a-rotation-experimental))

## Installation

### Prerequisites

- Python 3.12 or higher
- [uv](https://github.com/astral-sh/uv) (fast Python package installer)
- PagerDuty API key

### Install with uv

```bash
# Clone the repository
git clone https://github.com/getsentry/on-call-scheduler.git
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

## How It Works: Timezone-Aware After-Hours Counting

The scheduler uses timezone-aware calculations to only count days where users have on-call coverage **extending past standard workday hours**. This means:

### Key Concepts

1. **User Timezones**: Each user is assigned a timezone (from PagerDuty API, or configured via `USER_TIMEZONES`, or defaults to schedule timezone)

2. **Workday End Hour**: Configurable via `WORKDAY_END_HOUR` (default: 17 for 5 PM)

3. **After-Hours Coverage**: A day is only counted if the user's on-call shift extends past the workday end hour on that specific day in their local timezone

### Examples

**Scenario 1: Full Day Coverage**
- User timezone: America/New_York (EST/EDT)
- Shift: Jan 1, 12:00 AM - Jan 2, 12:00 AM EST
- **Result**: Jan 1 is counted (coverage extends past 5 PM EST)

**Scenario 2: Business Hours Only**
- User timezone: America/New_York
- Shift: Jan 1, 9:00 AM - Jan 1, 5:00 PM EST
- **Result**: Jan 1 is NOT counted (coverage ends at 5 PM, doesn't extend past it)

**Scenario 3: Evening Shift**
- User timezone: America/New_York
- Shift: Jan 1, 5:00 PM - Jan 2, 9:00 AM EST
- **Result**: Both Jan 1 and Jan 2 are counted (coverage extends past 5 PM on Jan 1, and past 5 PM on Jan 2)

**Scenario 4: Night Shift**
- User timezone: Europe/London
- Shift: Jan 1, 10:00 PM - Jan 2, 6:00 AM GMT
- **Result**: Jan 1 is counted (shift extends past 5 PM), Jan 2 is NOT counted (shift ends at 6 AM, before 5 PM)

This approach ensures that only **after-hours on-call burden** is measured, not business-hours coverage.

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

## Planning a Rotation (experimental)

`check` finds problems in schedules you already have. `plan` designs a new weekly rotation that avoids them. You describe the team in a TOML file, and it returns:

- a rotation that meets every hard rule
- each goal's result, with proof that it is the best possible
- the order to enter for each PagerDuty layer

It uses the [OR-Tools](https://developers.google.com/optimization) CP-SAT solver and needs no PagerDuty API key.

```bash
uv run oncall-scheduler plan examples/plan/three-offices.toml
uv run oncall-scheduler plan examples/plan/three-offices.toml --handoff-time 10:00   # compare handoffs
uv run oncall-scheduler plan team.toml --add "Sam=San Francisco"                     # what if Sam joins?
uv run oncall-scheduler plan team.toml --remove Ana --load balanced --cycle-weeks 16  # ...or Ana leaves?
uv run oncall-scheduler plan team.toml --csv next-year.csv --md report.md
```

### Day limits, counted the same way as `check`

A legal cap is set per office. With `per = "month"`, the planner counts days with the same function `check` uses (`get_dates_in_range`). A day counts when on-call coverage runs past `workday_end_hour` in the person's local time. The cap then applies to every calendar month for the next `check_years` years.

That makes the **handoff time** important. A weekly handoff at Tuesday 10:00 in Los Angeles is 19:00 in Vienna, after a 17:00 workday end. Both handoff days then count, so each shift costs 8 days instead of 7. Two shifts 4 weeks apart can then reach 11 days in a 31-day month. With an 08:00 Los Angeles handoff (17:00 in Vienna), each shift counts 7 days and the same rotation stays within 10.

With the example team:

- **Handoff at 10:00:** `plan` reports that equal load is impossible and explains why.
- **Handoff at 08:00:** it produces the rotation.

```toml
[offices.Vienna]
timezone = "Europe/Vienna"
max_oncall_days = 10
per = "month"            # or a rolling window in days, e.g. per = 28 (every shift day counts)

[rotation]
start = 2027-01-19       # the handoff weekday comes from this date
handoff_time = "08:00"
handoff_timezone = "America/Los_Angeles"
workday_end_hour = 17    # same meaning as WORKDAY_END_HOUR
```

### Team file

See [`examples/plan/`](examples/plan) for complete files:

| File | Shows |
| --- | --- |
| `three-offices.toml` | Primary and Secondary across 3 offices, a monthly cap, and a switch-over from published weeks |
| `primary-only.toml` | One role, with a minimum number of weeks off |
| `custom-rules.toml`, `custom_rules.py` | Role restrictions, people who shouldn't be on call together, and extra rules in Python |

`[rotation]` options:

| Key | Default | Meaning |
| --- | --- | --- |
| `roles` | `["Primary", "Secondary"]` | One layer per role, highest first |
| `cycle_weeks` | team size | Length of the repeating cycle |
| `handovers` | `"avoid"` | `"avoid"` back-to-back weeks, or `"maximize"` someone moving up a role the next week |
| `single_order` | `true` | With `"avoid"`, every role reuses the first role's order, shifted, so there is one list to maintain |
| `load` | `"equal"` | `"equal"` on-call weeks for everyone, or `"balanced"`: capped people do what the cap allows, and everyone else is within one week of each other |
| `max_weeks_in_a_row`, `min_weeks_off` | `2`, `0` | Hard limits |
| `never_together` | `[]` | Pairs of people never on call in the same week |
| `priorities` | all goals | Order of the goals: `timezones`, `handovers`, `office_spread`, `rest`, `cutover`, `custom` |
| `rules_file` | none | A Python file with `apply(rules)` for extra hard rules or goals |
| `check_years` | `5` | How many years of calendar months the monthly cap is checked for |

People can be limited to some roles (`roles = ["Secondary"]` on a `[[people]]` entry). `[[published]]` entries list the weeks already published up to the start date, so the caps are enforced across the switch-over.

Goals are optimised one at a time, in priority order. When no rotation meets the hard rules, `plan` names the rule that blocks it, and for monthly caps explains how the handoff time affects the day count.

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
    ├── output/
    │   └── formatter.py    # Output formatting
    └── planning/           # `plan`: rotation planner (OR-Tools CP-SAT)
        ├── config.py       # Team file (TOML) loading
        ├── model.py        # CP-SAT model
        ├── planner.py      # Constraints, goals, diagnosis
        ├── report.py       # Markdown / CSV output
        └── verify.py       # Independent re-checks of the result
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
uv run ruff format .

# Lint code (add --fix to apply safe fixes)
uv run ruff check .

# Type checking
uv run mypy src/oncall_scheduler
```

CI runs `ruff format --check`, `ruff check` and `mypy` on every pull request and fails if any of them reports anything.

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

Apache-2.0

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Support

For issues and questions:
- GitHub Issues: [Create an issue](https://github.com/your-org/on-call-scheduler/issues)
- PagerDuty API Documentation: https://developer.pagerduty.com/

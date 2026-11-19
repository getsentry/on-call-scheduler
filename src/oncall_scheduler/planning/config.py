"""Load and validate a team file (TOML) for `oncall-scheduler plan`.

See examples/plan/ and the README for the format.
"""

from __future__ import annotations

import datetime as dt
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import pytz

GOALS = ("timezones", "handovers", "office_spread", "rest", "cutover", "custom")
DEFAULT_PRIORITIES = list(GOALS)


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class LegalCap:
    """At most `max_days` on-call days per period.

    period "month": after-hours days per calendar month, counted like `oncall-scheduler check`
    (a day counts when on-call coverage runs past `workday_end_hour` local time).
    period int: every day of a shift counts, in any rolling window of that many days.
    """

    max_days: int
    period: str | int

    @property
    def monthly(self) -> bool:
        return self.period == "month"

    def describe(self) -> str:
        if self.monthly:
            return f"max {self.max_days} after-hours on-call days per calendar month"
        return f"max {self.max_days} on-call days in any {self.period}"


@dataclass
class Config:
    path: Path
    team_name: str
    roles: list[str]
    offices: dict[str, dict]
    people: dict[str, str]  # person -> office
    allowed_roles: dict[str, set[str]]  # only people with restrictions
    tz: dict[str, str]  # person -> time zone
    caps: dict[str, LegalCap]  # office -> cap
    start: dt.date
    handoff_time: dt.time
    handoff_tz: str
    workday_end_hour: int
    check_years: int
    cycle: int
    handovers: str
    single_order: bool
    load: str
    max_in_row: int | None
    min_weeks_off: int
    never_together: list[tuple[str, str]]
    priorities: list[str]
    time_limit: float
    rules_file: Path | None
    published: list[tuple[str, ...]] = field(default_factory=list)

    @property
    def rolling_caps_weeks(self) -> dict[str, tuple[int, int]]:
        """office -> (max shifts, per N weeks) for rolling-window caps."""
        out = {}
        for office, cap in self.caps.items():
            if not cap.monthly:
                out[office] = (cap.max_days // 7, int(cap.period) // 7)
        return out

    def shift_bounds(self, k: int) -> tuple[dt.datetime, dt.datetime]:
        """Start and end of the shift `k` weeks after `start` (negative: published weeks)."""
        tz = pytz.timezone(self.handoff_tz)
        d = self.start + dt.timedelta(weeks=k)
        begin = tz.localize(dt.datetime.combine(d, self.handoff_time))
        end = tz.localize(dt.datetime.combine(d + dt.timedelta(weeks=1), self.handoff_time))
        return begin, end

    @property
    def handoff_label(self) -> str:
        return f"{self.start:%A} {self.handoff_time:%H:%M} {self.handoff_tz}"


def _cap(name: str, o: dict) -> LegalCap | None:
    if "max_oncall_days" not in o:
        return None
    max_days, per = o["max_oncall_days"], o.get("per", "month")
    if per == "month":
        return LegalCap(max_days, "month")
    if not isinstance(per, int) or per % 7:
        raise ConfigError(
            f'office "{name}": per must be "month" or a number of days divisible by 7'
        )
    if max_days < 7:
        raise ConfigError(
            f'office "{name}": fewer than 7 days per {per} rules out full-week shifts'
        )
    return LegalCap(max_days, per)


def load_config(
    path,
    *,
    add=(),
    remove=(),
    start=None,
    cycle_weeks=None,
    handovers=None,
    load=None,
    handoff_time=None,
    two_orders=False,
    no_published=False,
) -> Config:
    path = Path(path)
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"not valid TOML: {e}") from e

    rot = raw.get("rotation", {})
    roles = rot.get("roles", ["Primary", "Secondary"])
    if not roles or len(set(roles)) != len(roles):
        raise ConfigError("rotation.roles must be a non-empty list of distinct names")

    offices = raw.get("offices") or {}
    if not offices:
        raise ConfigError("add at least one [offices.<name>] section")
    caps = {}
    for name, o in offices.items():
        if "timezone" not in o:
            raise ConfigError(f'office "{name}" needs a timezone')
        if o["timezone"] not in pytz.all_timezones_set:
            raise ConfigError(f'office "{name}": unknown timezone "{o["timezone"]}"')
        cap = _cap(name, o)
        if cap:
            caps[name] = cap

    people: dict[str, str] = {}
    allowed: dict[str, set[str]] = {}
    for p in raw.get("people", []):
        if "name" not in p or "office" not in p:
            raise ConfigError("each [[people]] entry needs a name and an office")
        if p["name"] in people:
            raise ConfigError(f'"{p["name"]}" is listed twice')
        people[p["name"]] = p["office"]
        if "roles" in p:
            bad = set(p["roles"]) - set(roles)
            if bad:
                raise ConfigError(f"{p['name']}: unknown role(s) {sorted(bad)}; roles are {roles}")
            allowed[p["name"]] = set(p["roles"])
    for name in remove:
        if name not in people:
            raise ConfigError(f'cannot remove "{name}": not in the team file')
        del people[name]
        allowed.pop(name, None)
    for spec in add:
        if "=" not in spec:
            raise ConfigError('--add expects "Name=Office"')
        name, office = (s.strip() for s in spec.split("=", 1))
        people[name] = office
    for name, office in people.items():
        if office not in offices:
            raise ConfigError(f'{name}: unknown office "{office}". Known: {", ".join(offices)}')
    if len(people) < len(roles) + 1:
        raise ConfigError(f"need at least {len(roles) + 1} people for {len(roles)} role(s)")
    for r in roles:
        if not any(r in allowed.get(i, set(roles)) for i in people):
            raise ConfigError(f'nobody can take the role "{r}"')

    start = start or rot.get("start")
    if isinstance(start, dt.datetime):
        start = start.date()
    if isinstance(start, str):
        start = dt.date.fromisoformat(start)
    if not isinstance(start, dt.date):
        raise ConfigError("rotation.start is required, as a date: start = 2027-01-19")

    handoff = handoff_time or rot.get("handoff_time", "10:00")
    try:
        handoff_t = handoff if isinstance(handoff, dt.time) else dt.time.fromisoformat(str(handoff))
    except ValueError as e:
        raise ConfigError(f'handoff_time must look like "08:00": {handoff}') from e
    handoff_tz = rot.get("handoff_timezone", "UTC")
    if handoff_tz not in pytz.all_timezones_set:
        raise ConfigError(f'unknown handoff_timezone "{handoff_tz}"')

    handovers = handovers or rot.get("handovers", "avoid")
    if handovers not in ("avoid", "maximize"):
        raise ConfigError('rotation.handovers must be "avoid" or "maximize"')
    if handovers == "maximize" and len(roles) < 2:
        raise ConfigError('handovers = "maximize" needs at least two roles')
    load = load or rot.get("load", "equal")
    if load not in ("equal", "balanced"):
        raise ConfigError('rotation.load must be "equal" or "balanced"')
    priorities = rot.get("priorities", DEFAULT_PRIORITIES)
    for g in priorities:
        if g not in GOALS:
            raise ConfigError(f'unknown priority "{g}". Choose from: {", ".join(GOALS)}')

    never = []
    for pair in rot.get("never_together", []):
        if len(pair) != 2 or any(n not in people for n in pair):
            raise ConfigError(f"never_together entries must be pairs of people in the team: {pair}")
        never.append((pair[0], pair[1]))

    rules_file = rot.get("rules_file")
    if rules_file:
        rules_file = (path.parent / rules_file).resolve()
        if not rules_file.exists():
            raise ConfigError(f"rules_file not found: {rules_file}")

    published = []
    if not no_published:
        rows = sorted(raw.get("published", []), key=lambda r: r["week"])
        rows = [r for r in rows if r["week"] < start]
        keys = [r.lower() for r in roles]
        for a, b in zip(rows, rows[1:], strict=False):
            if (b["week"] - a["week"]).days != 7:
                raise ConfigError(
                    f"published weeks must be consecutive ({a['week']} -> {b['week']})"
                )
        if rows and (start - rows[-1]["week"]).days != 7:
            raise ConfigError(
                f"published weeks must run up to the week before start: the last is "
                f"{rows[-1]['week']}, start is {start}. Add the missing weeks, or move the start."
            )
        for row in rows:
            missing = [k for k in keys if k not in row]
            if missing:
                raise ConfigError(f"published week {row['week']} is missing {missing}")
            published.append(tuple(row[k] for k in keys))

    return Config(
        path=path,
        team_name=raw.get("team", {}).get("name", path.stem),
        roles=roles,
        offices=offices,
        people=people,
        allowed_roles=allowed,
        tz={i: offices[o]["timezone"] for i, o in people.items()},
        caps=caps,
        start=start,
        handoff_time=handoff_t,
        handoff_tz=handoff_tz,
        workday_end_hour=rot.get("workday_end_hour", 17),
        check_years=rot.get("check_years", 5),
        cycle=cycle_weeks or rot.get("cycle_weeks") or len(people),
        handovers=handovers,
        single_order=rot.get("single_order", True)
        and handovers == "avoid"
        and len(roles) > 1
        and not two_orders,
        load=load,
        max_in_row=rot.get("max_weeks_in_a_row", 2),
        min_weeks_off=rot.get("min_weeks_off", 0),
        never_together=never,
        priorities=priorities,
        time_limit=rot.get("time_limit_seconds", 20),
        rules_file=rules_file,
        published=published,
    )

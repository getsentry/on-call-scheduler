"""Turn a Config into a solved rotation: build the model, optimise, explain failures."""

from __future__ import annotations

import dataclasses
import datetime as dt
import importlib.util
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import cache

import pytz

from oncall_scheduler.analysis.calculator import get_dates_in_range
from oncall_scheduler.planning.config import Config
from oncall_scheduler.planning.model import RotaModel


class PlanError(Exception):
    def __init__(self, messages):
        super().__init__("\n".join(messages))
        self.messages = messages


@dataclass
class Plan:
    cfg: Config
    schedule: list[tuple[str, ...]]  # published weeks, then the new rotation (2+ cycles)
    pre: int  # number of published weeks at the start of `schedule`
    goals: list[str]
    values: dict
    proven: dict
    offsets: dict  # role -> k when that role's order is roles[0]'s order shifted by k
    note: str | None = None

    @property
    def cycle(self):
        return self.schedule[self.pre : self.pre + self.cfg.cycle]

    def week_date(self, w):
        return self.cfg.start + dt.timedelta(weeks=w - self.pre)

    def holders(self, k):
        """Who holds each role `k` weeks after start (negative k: published weeks)."""
        if k < 0:
            return self.schedule[self.pre + k]
        return self.cycle[k % self.cfg.cycle]


# --------------------------------------------------------------------------- #
# Counting on-call days the way `oncall-scheduler check` does
# --------------------------------------------------------------------------- #
@cache
def _counted(start, end, tz, workday_end_hour):
    return frozenset(get_dates_in_range(start, end, start, end, tz, workday_end_hour))


def counted_dates(cfg: Config, k: int, tz: str) -> frozenset[dt.date]:
    """Local dates that shift `k` counts as on-call days for someone in `tz`."""
    begin, end = cfg.shift_bounds(k)
    dates: frozenset[dt.date] = _counted(begin, end, tz, cfg.workday_end_hour)
    return dates


def horizon_weeks(cfg: Config) -> int:
    return math.ceil(cfg.check_years * 52.18) + 1


def days_per_shift(cfg: Config, tz: str) -> int:
    """Most after-hours days one weekly shift counts for someone in `tz` (DST can vary it)."""
    return max(len(counted_dates(cfg, k, tz)) for k in range(53))


def local_handoff(cfg: Config, tz: str) -> str:
    begin, _ = cfg.shift_bounds(0)
    return begin.astimezone(pytz.timezone(tz)).strftime("%H:%M")


class Rules:
    """Passed to `apply(rules)` in a team's rules_file, for rules the file format doesn't cover.

    Weeks are 0-based positions in the cycle (0 = the week starting on the start date).
    """

    def __init__(self, rota: RotaModel, cfg: Config, pre: int):
        self._rota, self._pre = rota, pre
        self.model = rota.m  # the raw OR-Tools CpModel, for anything else
        self.people = dict(cfg.people)  # person -> office
        self.roles = list(cfg.roles)
        self.cycle_length = cfg.cycle
        self.start = cfg.start
        self.goals: list[tuple] = []

    def weeks(self):
        return range(self.cycle_length)

    def week_of(self, date: dt.date) -> int:
        """Cycle position of the week containing `date` (the cycle repeats)."""
        return ((date - self.start).days // 7) % self.cycle_length

    def _w(self, week):
        return self._pre + week % self.cycle_length

    def on_call(self, person, week, role=None):
        """0/1 expression: `person` is on call in cycle `week` (in `role`, if given)."""
        w = self._w(week)
        return self._rota.on(person, w) if role is None else self._rota.x[role][person][w]

    def both_on_call(self, a, b, week):
        return self._rota.both_on(a, b, self._w(week))

    def require(self, constraint):
        """Add a hard rule, e.g. rules.require(rules.on_call("Ana", 0) == 0)."""
        return self.model.add(constraint)

    def forbid(self, person, week, role=None):
        return self.require(self.on_call(person, week, role) == 0)

    def add_goal(self, name, expr, sense="min"):
        """Add a goal, optimised where "custom" sits in rotation.priorities (default: last)."""
        if sense not in ("min", "max"):
            raise ValueError('sense must be "min" or "max"')
        self.goals.append((name, expr, sense))


def _load_rules(path):
    spec = importlib.util.spec_from_file_location(f"oncall_rules_{abs(hash(str(path)))}", path)
    if spec is None or spec.loader is None:
        raise PlanError([f"cannot load rules_file {path}"])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "apply"):
        raise PlanError([f"{path} must define a function apply(rules)"])
    return mod.apply


def capacity_problems(cfg: Config):
    n, cycle, n_roles = len(cfg.people), cfg.cycle, len(cfg.roles)
    out = []
    if cfg.load == "equal" and (n_roles * cycle) % n:
        out.append(
            f'load = "equal" needs {n_roles} x cycle_weeks to be a multiple of the team size '
            f'({n}); cycle_weeks is {cycle}. Use a multiple of {n}, or load = "balanced".'
        )
    need = n_roles * cycle / n
    for i, office in cfg.people.items():
        if office in cfg.rolling_caps_weeks:
            mx, win = cfg.rolling_caps_weeks[office]
            cap = math.floor(mx * cycle / win)
            if cfg.load == "equal" and cap < need:
                out.append(
                    f"{i} ({office}) can legally do at most {cap} shift{'s' if cap != 1 else ''} "
                    f'per {cycle} weeks, but equal load needs {need:g}. Use load = "balanced" so '
                    "others cover the difference."
                )
    return out


def _add_monthly_caps(cfg: Config, rota: RotaModel, pre: int):
    """Calendar-month caps, counted like `check`, for every month in the next check_years."""
    model, cycle = rota.m, cfg.cycle
    for i, office in cfg.people.items():
        cap = cfg.caps.get(office)
        if not cap or not cap.monthly:
            continue
        terms: dict[tuple[int, int], list] = defaultdict(list)
        const: Counter = Counter()
        for k in range(-pre, horizon_weeks(cfg)):
            months = Counter((d.year, d.month) for d in counted_dates(cfg, k, cfg.tz[i]))
            for ym, n_days in months.items():
                if k < 0:
                    if i in cfg.published[pre + k]:
                        const[ym] += n_days
                else:
                    # Summing per shift can count a handoff day twice when someone does two
                    # weeks in a row, so this never undercounts.
                    terms[ym].append(n_days * rota.on(i, pre + k % cycle))
        for ym, ts in terms.items():
            model.add(sum(ts) + const[ym] <= cap.max_days)


def build(cfg: Config, single_order: bool):
    people, roles, cycle = cfg.people, cfg.roles, cfg.cycle
    published = cfg.published
    pre = len(published)
    pad = max(
        [4, cfg.min_weeks_off + 2, (cfg.max_in_row or 0) + 1]
        + [w for _, w in cfg.rolling_caps_weeks.values()]
    )
    weeks = pre + 2 * cycle + pad

    everyone, tz = dict(people), dict(cfg.tz)
    externals = sorted({n for week in published for n in week} - set(people))
    for e in externals:  # people in published weeks who are no longer on the rotation
        everyone[e] = tz[e] = f"(not on rotation: {e})"
    rota = RotaModel(
        everyone,
        roles,
        weeks,
        tz=tz,
        limits=cfg.rolling_caps_weeks,
        max_consecutive=cfg.max_in_row,
        allowed_roles=cfg.allowed_roles,
        free_from=pre,
    )
    x, model = rota.x, rota.m
    for w, week in enumerate(published):
        for r, name in zip(roles, week, strict=True):
            model.add(x[r][name][w] == 1)
    for e in externals:
        for r in roles:
            for w in range(pre, weeks):
                model.add(x[r][e][w] == 0)
    for r in roles:
        for i in everyone:
            for w in range(pre + cycle, weeks):
                model.add(x[r][i][w] == x[r][i][w - cycle])
    steady = range(pre, pre + cycle)

    _add_monthly_caps(cfg, rota, pre)
    for w in range(max(0, pre - cfg.min_weeks_off - 1), weeks):
        for k in range(2, cfg.min_weeks_off + 1):
            if pre <= w + k < weeks:
                for i in people:
                    model.add(rota.on(i, w) - rota.on(i, w + 1) + rota.on(i, w + k) <= 1)
    for a, b in cfg.never_together:
        for w in range(pre, weeks):
            model.add(rota.on(a, w) + rota.on(b, w) <= 1)

    goals: list[tuple] = []
    n, n_roles = len(people), len(roles)
    totals = {i: sum(rota.on(i, w) for w in steady) for i in people}
    if cfg.load == "equal":
        for i in people:
            model.add(totals[i] == n_roles * cycle // n)
    else:
        capped = [i for i in people if people[i] in cfg.caps]
        others = [i for i in people if i not in capped]
        for i in capped:
            model.add(totals[i] <= math.ceil(n_roles * cycle / n))
        if others:
            lo = model.new_int_var(0, n_roles * cycle, "others_lo")
            for i in others:
                model.add(totals[i] >= lo)
                model.add(totals[i] <= lo + 1)
        if capped:
            goals.append(
                (
                    "On-call weeks per cycle done by people with a legal cap",
                    sum(totals[i] for i in capped),
                    "max",
                )
            )

    counts = {i: {r: sum(x[r][i][w] for w in steady) for r in roles} for i in people}
    if cfg.allowed_roles:
        # someone can't take every role: balance role counts as a goal, not a hard rule
        spreads = []
        for i in people:
            mine = [counts[i][r] for r in roles if r in cfg.allowed_roles.get(i, set(roles))]
            if len(mine) > 1:
                hi, lo_ = model.new_int_var(0, cycle, ""), model.new_int_var(0, cycle, "")
                model.add_max_equality(hi, mine)
                model.add_min_equality(lo_, mine)
                spreads.append(hi - lo_)
        if spreads:
            worst = model.new_int_var(0, cycle, "role_spread")
            model.add_max_equality(worst, spreads)
            goals.append(("Largest gap between one person's role counts", worst, "min"))
    else:
        for i in people:
            for r in roles:
                model.add(counts[i][r] * n_roles >= totals[i] - (n_roles - 1))
                model.add(counts[i][r] * n_roles <= totals[i] + (n_roles - 1))

    offsets = {}
    if single_order:
        for r in roles[1:]:
            ys = {}
            for k in range(1, cycle):
                y = model.new_bool_var(f"offset|{r}|{k}")
                ys[k] = y
                for i in people:
                    for w in steady:
                        model.add(x[r][i][w] == x[roles[0]][i][w + k]).only_enforce_if(y)
            model.add_exactly_one(ys.values())
            offsets[r] = ys

    rules = Rules(rota, cfg, pre)
    if cfg.rules_file:
        _load_rules(cfg.rules_file)(rules)

    roster = list(people)
    for g in cfg.priorities:
        if g == "timezones" and n_roles > 1:
            goals.append(
                (
                    "Weeks where two on-call people share a time zone",
                    rota.same_tz_pairs(steady),
                    "min",
                )
            )
        elif g == "handovers" and cfg.handovers == "avoid":
            b2b = sum(rota.back_to_back(i, w) for i in roster for w in steady)
            goals.append(("Times someone is on call 2 weeks in a row", b2b, "min"))
        elif g == "handovers":
            hand = sum(rota.handover(i, w) for i in roster for w in steady)
            goals.append((f"Hand-overs ({roles[1]} one week, {roles[0]} the next)", hand, "max"))
        elif g == "office_spread":
            goals.append(
                (
                    "Runs of 3+ weeks from one office (any role)",
                    rota.office_run_events(3, steady),
                    "min",
                )
            )
            goals.append(
                (
                    "Back-to-back weeks from one office (any role)",
                    rota.office_run_events(2, steady),
                    "min",
                )
            )
        elif g == "rest":
            gaps = sum(rota.one_week_gap(i, w) for i in roster for w in steady)
            goals.append(("Times someone gets only 1 week off between shifts", gaps, "min"))
        elif g == "cutover" and pre:
            terms = [rota.back_to_back(i, pre - 1) for i in roster]
            terms += [rota.one_week_gap(i, w) for i in roster for w in range(max(0, pre - 2), pre)]
            goals.append(("Short breaks created at the switch-over", sum(terms), "min"))
        elif g == "custom":
            goals += rules.goals
    if "custom" not in cfg.priorities:
        goals += rules.goals
    return rota, goals, pre, offsets


def _feasible(cfg: Config) -> bool:
    rota, _, _, _ = build(cfg, single_order=False)
    v, _ = rota.solve_lex([], time_limit=cfg.time_limit)
    return v is not None


def handoff_hints(cfg: Config) -> list[str]:
    hints = []
    for office, cap in cfg.caps.items():
        if not cap.monthly:
            continue
        tz = cfg.offices[office]["timezone"]
        per = days_per_shift(cfg, tz)
        if per > 7:
            hints.append(
                f"Each weekly shift counts as {per} on-call days in {office}: the handoff is at "
                f"{local_handoff(cfg, tz)} there, after the {cfg.workday_end_hour}:00 workday end, "
                f"so both handoff days count. A handoff at or before {cfg.workday_end_hour}:00 "
                f"{office} time counts 7 (try --handoff-time)."
            )
    return hints


def plan(cfg: Config) -> Plan:
    problems = capacity_problems(cfg)
    if problems:
        raise PlanError(problems)
    for single in [True, False] if cfg.single_order else [False]:
        rota, goals, pre, offsets = build(cfg, single)
        values, proven = rota.solve_lex(goals, time_limit=cfg.time_limit)
        if values is not None:
            sched = rota.schedule()
            offs = {
                r: next(k for k, y in ys.items() if rota.solver.value(y))
                for r, ys in offsets.items()
            }
            note = None
            if cfg.single_order and not single:
                note = (
                    "No design with one shared order exists for this team; each role has its own."
                )
            return Plan(cfg, sched, pre, [g[0] for g in goals], values, proven, offs, note)

    # Nothing works: find which optional rule is in the way.
    msgs = ["No rotation meets all the hard rules."]
    relax: list[tuple[str, dict]] = [
        ("the legal caps", dict(caps={})),
        ("the published weeks (try a later start date)", dict(published=[])),
        ("never_together", dict(never_together=[])),
        (f"min_weeks_off = {cfg.min_weeks_off}", dict(min_weeks_off=0)),
        (f"max_weeks_in_a_row = {cfg.max_in_row}", dict(max_in_row=None)),
        ("the per-person role restrictions", dict(allowed_roles={})),
        ("the rules_file", dict(rules_file=None)),
    ]
    culprits = []
    for label, change in relax:
        if all(getattr(cfg, k) == v for k, v in change.items()):
            continue
        if _feasible(dataclasses.replace(cfg, **change)):
            culprits.append(label)
    if culprits:
        msgs.append("It becomes possible if you drop any one of: " + "; ".join(culprits) + ".")
    if "the legal caps" in culprits:
        msgs += handoff_hints(cfg)
        if cfg.load == "equal":
            msgs.append('Or use load = "balanced", so others cover what capped people cannot.')
    if not culprits:
        msgs.append('Try load = "balanced", a longer cycle_weeks, or fewer hard rules.')
    raise PlanError(msgs)

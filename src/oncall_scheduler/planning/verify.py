"""Independent checks: score a schedule in plain Python, without the solver.

`evaluate` checks rolling-window caps day by day and computes the fairness stats.
`monthly_days` recounts calendar-month caps with the same day counter `check` uses.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from oncall_scheduler.planning.planner import Plan, counted_dates, horizon_weeks


@dataclass
class Report:
    legal_ok: bool
    legal_violations: list  # (person, first day index of a violating window, days on call)
    same_tz_weeks: int  # weeks where at least two on-call people share a time zone
    longest_office_run: dict  # role -> longest run of one office
    handover_people: list  # people who step up a role from one week to the next
    longest_stretch: dict  # person -> most consecutive weeks on call
    gaps: dict  # person -> weeks off between consecutive shifts
    partners: dict  # person -> people they are on call with
    load: dict  # person -> {role: count}


def evaluate(schedule, roles, people, tz=None, limits_days=None, cyclic=True) -> Report:
    """schedule: list of tuples (one name per role, in `roles` order), one per week.

    people: person -> office (people not listed, e.g. former members in history, are allowed).
    limits_days: office -> (max days on call, rolling window in days).
    """
    tz = tz or {}
    limits_days = limits_days or {}
    n_weeks = len(schedule)
    names = sorted({n for week in schedule for n in week} | set(people))
    on = {i: [0] * n_weeks for i in names}
    for w, week in enumerate(schedule):
        if len(set(week)) != len(week):
            raise ValueError(f"week {w}: one person holds two roles: {week}")
        for n in week:
            on[n][w] = 1

    violations = []
    for i, office in people.items():
        if office not in limits_days:
            continue
        max_days, window = limits_days[office]
        days = [v for w in range(n_weeks) for v in [on[i][w]] * 7]
        seq = days * 3 if cyclic else days
        for s in range(len(seq) - window + 1):
            n = sum(seq[s : s + window])
            if n > max_days:
                violations.append((i, s % len(days), n))
                break

    def tz_of(n):
        return tz.get(n, f"?{n}")

    same_tz = sum(len({tz_of(n) for n in week}) < len(week) for week in schedule)

    def longest_run(seq):
        if not seq:
            return 0
        best, run = 1, 1
        seq2 = seq * 2 if cyclic else seq
        for a, b in zip(seq2, seq2[1:]):
            run = run + 1 if a == b else 1
            best = max(best, run)
        return min(best, len(seq))

    runs = {
        r: longest_run([people.get(week[k], f"?{week[k]}") for week in schedule])
        for k, r in enumerate(roles)
    }

    hand = set()
    pairs = [(w, w + 1) for w in range(n_weeks - 1)] + ([(n_weeks - 1, 0)] if cyclic else [])
    for a, b in pairs:
        for k in range(len(roles) - 1):
            if schedule[a][k + 1] == schedule[b][k]:
                hand.add(schedule[a][k + 1])

    stretch, gaps = {}, {}
    for i in people:
        seq = on[i] * 2 if cyclic else on[i]
        best = run = 0
        for v in seq:
            run = run + 1 if v else 0
            best = max(best, run)
        stretch[i] = min(best, n_weeks)
        weeks_on = [w for w in range(n_weeks) if on[i][w]]
        ws = weeks_on + ([weeks_on[0] + n_weeks] if cyclic and weeks_on else [])
        gaps[i] = [b - a - 1 for a, b in zip(ws, ws[1:]) if b - a > 1]

    partners: dict[str, set[str]] = defaultdict(set)
    for week in schedule:
        for a in week:
            partners[a].update(n for n in week if n != a)

    load = {
        i: {r: sum(1 for week in schedule if week[k] == i) for k, r in enumerate(roles)}
        for i in people
    }

    return Report(
        legal_ok=not violations,
        legal_violations=violations,
        same_tz_weeks=same_tz,
        longest_office_run=runs,
        handover_people=sorted(hand),
        longest_stretch=stretch,
        gaps=gaps,
        partners={k: sorted(v) for k, v in partners.items()},
        load=load,
    )


def monthly_days(plan: Plan, person: str) -> dict[tuple[int, int], int]:
    """After-hours on-call days per calendar month (person's local time), from the published
    weeks through `check_years`, counted with the same day counter as `check`."""
    cfg = plan.cfg
    days: set = set()
    for k in range(-plan.pre, horizon_weeks(cfg)):
        if person in plan.holders(k):
            days |= counted_dates(cfg, k, cfg.tz[person])
    return dict(sorted(Counter((d.year, d.month) for d in days).items()))

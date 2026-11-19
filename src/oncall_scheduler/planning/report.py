"""Render a Plan as Markdown and CSV."""

from __future__ import annotations

import csv
from collections import Counter

from oncall_scheduler.planning.planner import Plan, days_per_shift, local_handoff
from oncall_scheduler.planning.verify import evaluate, monthly_days


def legal_checks(plan: Plan) -> list[tuple[str, bool, str]]:
    """(office, ok, detail) for each office with a legal cap, recounted independently."""
    cfg = plan.cfg
    out = []
    for office, cap in cfg.caps.items():
        members = [i for i, o in cfg.people.items() if o == office]
        tz = cfg.offices[office]["timezone"]
        if cap.monthly:
            worst, worst_ym = 0, None
            for i in members:
                for ym, n in monthly_days(plan, i).items():
                    if n > worst:
                        worst, worst_ym = n, ym
            detail = (
                f"busiest month {worst} days"
                + (f" ({worst_ym[0]}-{worst_ym[1]:02d})" if worst_ym else "")
                + f", checked for {cfg.check_years} years; a shift counts as "
                f"{days_per_shift(cfg, tz)} days (handoff {local_handoff(cfg, tz)} local)"
            )
            out.append((office, worst <= cap.max_days, detail))
        else:
            limits = {office: (cap.max_days, int(cap.period))}
            steady = evaluate(plan.cycle, cfg.roles, cfg.people, cfg.tz, limits, cyclic=True)
            full = evaluate(plan.schedule, cfg.roles, cfg.people, cfg.tz, limits, cyclic=False)
            # published weeks can't change, so only flag windows that reach the new rotation
            new_viol = [v for v in full.legal_violations if v[1] + int(cap.period) > plan.pre * 7]
            out.append((office, steady.legal_ok and not new_viol, "checked day by day"))
    return out


def markdown(plan: Plan) -> str:
    cfg, roles = plan.cfg, plan.cfg.roles
    steady = evaluate(plan.cycle, roles, cfg.people, cfg.tz, cyclic=True)
    out: list[str] = []
    p = out.append
    offices = Counter(cfg.people.values())
    p(f"# {cfg.team_name}: on-call rotation from {cfg.start}")
    p("")
    style = (
        "hand-overs avoided"
        if cfg.handovers == "avoid"
        else f"hand-overs ({roles[1]} then {roles[0]}) maximised"
    )
    p(
        f"{len(cfg.people)} people ("
        + ", ".join(f"{o}: {n}" for o, n in offices.items())
        + f"), roles: {', '.join(roles)}, {cfg.cycle}-week cycle, {style}. "
        f"Handoff {cfg.handoff_label}."
    )
    if plan.note:
        p("")
        p(f"Note: {plan.note}")
    p("")
    p("## Checks")
    p("")
    for office, ok, detail in legal_checks(plan):
        p(
            f"- Legal cap for {office} ({cfg.caps[office].describe()}): "
            f"**{'OK' if ok else 'VIOLATED'}**, {detail}"
        )
    if cfg.max_in_row:
        worst = max(steady.longest_stretch.values())
        ok = worst <= cfg.max_in_row
        status = "OK" if ok else "VIOLATED"
        p(f"- Nobody on call more than {cfg.max_in_row} weeks in a row: **{status}**")
    if cfg.min_weeks_off:
        short = [i for i, g in steady.gaps.items() if g and min(g) < cfg.min_weeks_off]
        p(
            f"- At least {cfg.min_weeks_off} weeks off between shifts: "
            f"**{'OK' if not short else 'VIOLATED'}**"
        )
    for a, b in cfg.never_together:
        clash = any(a in wk and b in wk for wk in plan.cycle)
        p(f"- {a} and {b} never on call together: **{'VIOLATED' if clash else 'OK'}**")
    p("")
    p("## Goals, in priority order")
    p("")
    p("Each goal was optimised as far as possible before the next one was considered.")
    p("")
    p("| Goal | Result | |")
    p("| --- | --- | --- |")
    for g in plan.goals:
        how = "best possible (proven)" if plan.proven[g] else "best found within the time limit"
        p(f"| {g} | {plan.values[g]} | {how} |")
    p("")
    p("## Schedule")
    p("")
    p("| Week of | " + " | ".join(roles) + " | |")
    p("| --- | " + " | ".join("---" for _ in roles) + " | --- |")
    for w in range(max(0, plan.pre - 4), plan.pre + cfg.cycle):
        names = [f"{n} ({cfg.people.get(n, 'not on rotation')})" for n in plan.schedule[w]]
        tag = "published" if w < plan.pre else ("cycle starts" if w == plan.pre else "")
        p(f"| {plan.week_date(w)} | " + " | ".join(names) + f" | {tag} |")
    p("")
    p(f"The {cfg.cycle}-week cycle then repeats.")
    p("")
    p("## Per person, per cycle")
    p("")
    p("| Person | Office | " + " | ".join(roles) + " | Weeks off between shifts | On call with |")
    p("| --- | --- | " + " | ".join("---" for _ in roles) + " | --- | --- |")
    for i in cfg.people:
        load = steady.load[i]
        gaps = ", ".join(map(str, steady.gaps[i])) or "-"
        partners = ", ".join(steady.partners.get(i, [])) or "-"
        p(
            f"| {i} | {cfg.people[i]} | "
            + " | ".join(str(load[r]) for r in roles)
            + f" | {gaps} | {partners} |"
        )
    p("")
    p("## PagerDuty layers")
    p("")
    p(f"One layer per role: weekly rotation starting {cfg.start}, handoff {cfg.handoff_label}.")
    p("")
    first = [wk[0] for wk in plan.cycle]
    for k, r in enumerate(roles):
        line = f"- **{r}**: " + ", ".join(wk[k] for wk in plan.cycle)
        if r in plan.offsets:
            off = plan.offsets[r]
            line += (
                f"  \n  (the {roles[0]} list starting from entry {off + 1}, {first[off]}: "
                f"{r} is {off} weeks ahead)"
            )
        p(line)
    return "\n".join(out) + "\n"


def write_csv(plan: Plan, path, weeks=52):
    cfg = plan.cfg
    with open(path, "w", newline="") as f:
        wr = csv.writer(f)
        cols = [c for r in cfg.roles for c in (r.lower(), f"{r.lower()}_office")]
        wr.writerow(["shift_start"] + cols)
        for k in range(weeks):
            row: list = [cfg.shift_bounds(k)[0].isoformat()]
            for n in plan.cycle[k % cfg.cycle]:
                row += [n, cfg.people[n]]
            wr.writerow(row)

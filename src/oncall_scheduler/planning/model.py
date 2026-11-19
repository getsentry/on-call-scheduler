"""CP-SAT model of a weekly on-call rotation with one or more roles.

Decision variables: x[role][person][week] is 1 when `person` holds `role` in `week`.
Weeks form a finite horizon; the planner adds periodicity on top to get a cycle.
"""

from __future__ import annotations

from ortools.sat.python import cp_model


class RotaModel:
    def __init__(
        self,
        people: dict[str, str],  # person -> office
        roles: list[str],  # highest role first, e.g. ["Primary", "Secondary"]
        weeks: int,
        *,
        tz: dict[str, str],  # person -> time-zone label
        limits: dict[str, tuple[int, int]] | None = None,  # office -> (max shifts, per N weeks)
        max_consecutive: int | None = None,  # nobody on call more than N weeks in a row
        allowed_roles: dict[str, set[str]] | None = None,  # person -> roles they may take
        free_from: int = 0,  # weeks before this are fixed history: skip windows wholly inside it
    ):
        self.people = people
        self.names = list(people)
        self.roles = list(roles)
        self.W = weeks
        self.tz = tz
        self.tzs = sorted(set(tz.values()))
        self.offices = sorted(set(people.values()))
        self.limits = limits or {}
        self.free_from = free_from
        self.m = m = cp_model.CpModel()
        self._cache: dict = {}
        self.x = {
            r: {i: [m.new_bool_var(f"{r}|{i}|{w}") for w in range(weeks)] for i in self.names}
            for r in self.roles
        }
        for w in range(weeks):
            for r in self.roles:
                m.add_exactly_one(self.x[r][i][w] for i in self.names)
            for i in self.names:
                m.add_at_most_one(self.x[r][i][w] for r in self.roles)
        for i, rs in (allowed_roles or {}).items():
            for r in self.roles:
                if r not in rs:
                    for w in range(weeks):
                        m.add(self.x[r][i][w] == 0)
        for i in self.names:
            if people[i] in self.limits:
                mx, win = self.limits[people[i]]
                for w in self.windows(win):
                    m.add(sum(self.on(i, w + k) for k in range(win)) <= mx)
            if max_consecutive:
                k = max_consecutive + 1
                for w in self.windows(k):
                    m.add(sum(self.on(i, w + d) for d in range(k)) <= max_consecutive)

    # ---- helpers ------------------------------------------------------------ #
    def windows(self, length):
        """Start weeks of length-`length` windows that touch at least one non-history week."""
        return range(max(0, self.free_from - length + 1), max(0, self.W - length + 1))

    def on(self, i, w):
        """0/1 expression: person i holds some role in week w."""
        return sum(self.x[r][i][w] for r in self.roles)

    def _and(self, lits, key):
        if key not in self._cache:
            b = self.m.new_bool_var(str(key))
            self.m.add_bool_and(lits).only_enforce_if(b)
            self.m.add_bool_or([lit.Not() for lit in lits]).only_enforce_if(b.Not())
            self._cache[key] = b
        return self._cache[key]

    def on_var(self, i, w):
        key = ("on", i, w)
        if key not in self._cache:
            b = self.m.new_bool_var(str(key))
            self.m.add(b == self.on(i, w))
            self._cache[key] = b
        return self._cache[key]

    def _group_in(self, r, kind, label, w):
        key = (kind, r, label, w)
        if key not in self._cache:
            groups = self.tz if kind == "tz" else self.people
            b = self.m.new_bool_var(str(key))
            self.m.add(b == sum(self.x[r][i][w] for i in self.names if groups[i] == label))
            self._cache[key] = b
        return self._cache[key]

    # ---- metrics ------------------------------------------------------------ #
    def same_tz_pairs(self, weeks):
        """# of (week, pair of roles) where both holders share a time zone."""
        terms = []
        for w in weeks:
            for a in range(len(self.roles)):
                for b in range(a + 1, len(self.roles)):
                    ra, rb = self.roles[a], self.roles[b]
                    for t in self.tzs:
                        terms.append(
                            self._and(
                                [self._group_in(ra, "tz", t, w), self._group_in(rb, "tz", t, w)],
                                ("sametz", ra, rb, t, w),
                            )
                        )
        return sum(terms)

    def office_run_events(self, run_len, weeks):
        """# of (role, week) where `run_len` consecutive weeks of that role are one office."""
        terms = []
        for r in self.roles:
            for o in self.offices:
                for w in weeks:
                    if w + run_len - 1 < self.W:
                        lits = [self._group_in(r, "office", o, w + d) for d in range(run_len)]
                        terms.append(self._and(lits, ("run", r, o, run_len, w)))
        return sum(terms)

    def handover(self, i, w):
        """1 if person i steps up one role from week w to w+1 (e.g. Secondary -> Primary)."""
        return sum(
            self._and(
                [self.x[self.roles[k + 1]][i][w], self.x[self.roles[k]][i][w + 1]],
                ("hand", k, i, w),
            )
            for k in range(len(self.roles) - 1)
        )

    def back_to_back(self, i, w):
        return self._and([self.on_var(i, w), self.on_var(i, w + 1)], ("b2b", i, w))

    def one_week_gap(self, i, w):
        """On in w, off in w+1, on in w+2."""
        return self._and(
            [self.on_var(i, w), self.on_var(i, w + 1).Not(), self.on_var(i, w + 2)], ("gap1", i, w)
        )

    def both_on(self, a, b, w):
        return self._and([self.on_var(a, w), self.on_var(b, w)], ("both", a, b, w))

    # ---- solving ------------------------------------------------------------ #
    def solve_lex(self, objectives, time_limit=20.0, workers=8):
        """Optimise objectives [(name, expr, 'min'|'max')] in priority order.

        Each stage's result is fixed before the next. Returns (values, proven) or
        (None, status) when no solution is found. Deterministic for a given input.
        """
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit
        solver.parameters.num_workers = workers
        solver.parameters.interleave_search = True  # deterministic regardless of thread count
        solver.parameters.random_seed = 0
        values, proven = {}, {}
        stages = objectives or [(None, None, None)]
        for name, expr, sense in stages:
            if expr is None or isinstance(expr, int):
                self.m.clear_objective()
            elif sense == "min":
                self.m.minimize(expr)
            else:
                self.m.maximize(expr)
            st = solver.solve(self.m)
            if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                return None, solver.status_name(st)
            if name is None:
                break
            val = expr if isinstance(expr, int) else int(round(solver.objective_value))
            values[name], proven[name] = val, st == cp_model.OPTIMAL
            if not isinstance(expr, int):
                self.m.add(expr == val)
            self.m.clear_hints()
            for r in self.roles:
                for i in self.names:
                    for w in range(self.W):
                        self.m.add_hint(self.x[r][i][w], solver.value(self.x[r][i][w]))
        self.solver = solver
        return values, proven

    def schedule(self):
        """List of tuples, one per week: the holder of each role in `roles` order."""
        out = []
        for w in range(self.W):
            out.append(
                tuple(
                    next(i for i in self.names if self.solver.value(self.x[r][i][w]))
                    for r in self.roles
                )
            )
        return out

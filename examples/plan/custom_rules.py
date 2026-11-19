"""Extra rules for examples/plan/custom-rules.toml.

`apply(rules)` is called once while the model is built. `rules` offers:

    rules.weeks()                     cycle positions 0 .. cycle_length-1
    rules.on_call(person, week[, role])   0/1 expression
    rules.both_on_call(a, b, week)    0/1 variable
    rules.require(constraint)         add a hard rule
    rules.forbid(person, week[, role])
    rules.add_goal(name, expression, "min" | "max")
    rules.model                       the raw OR-Tools CpModel, for anything else
    rules.people, rules.roles, rules.cycle_length, rules.start, rules.week_of(date)

Weeks are positions in the repeating cycle. For one-off absences (PTO), use
overrides in your scheduling tool instead.
"""

PLATFORM = ["Oto", "Pam", "Rae"]  # a sub-team that shouldn't be stretched thin
SENIORS = ["Nia", "Oto", "Quin"]
NEW_HIRE = "Sol"


def apply(rules):
    # Hard rule: at most one person from the platform sub-team on call in any week.
    for w in rules.weeks():
        rules.require(sum(rules.on_call(p, w) for p in PLATFORM) <= 1)

    # Goal: whenever the new hire is on call, pair them with a senior.
    unpaired = []
    for w in rules.weeks():
        b = rules.model.new_bool_var(f"unpaired_{w}")
        # b must be 1 if the new hire is on and no senior is
        rules.require(b >= rules.on_call(NEW_HIRE, w) - sum(rules.on_call(s, w) for s in SENIORS))
        unpaired.append(b)
    rules.add_goal("Weeks the new hire is on call without a senior", sum(unpaired), "min")

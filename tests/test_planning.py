"""Tests for `oncall-scheduler plan` (oncall_scheduler.planning)."""

import datetime as dt
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from oncall_scheduler.cli import cli
from oncall_scheduler.planning import ConfigError, PlanError, load_config, plan
from oncall_scheduler.planning.planner import days_per_shift
from oncall_scheduler.planning.report import legal_checks
from oncall_scheduler.planning.verify import evaluate, monthly_days

EXAMPLES = Path(__file__).parent.parent / "examples" / "plan"
THREE = EXAMPLES / "three-offices.toml"

SMALL = """
[offices.Vienna]
timezone = "Europe/Vienna"
max_oncall_days = 10
per = 28

[offices.Toronto]
timezone = "America/Toronto"

[[people]]
name = "A"
office = "Vienna"
[[people]]
name = "B"
office = "Toronto"
[[people]]
name = "C"
office = "Toronto"
[[people]]
name = "D"
office = "Toronto"

[rotation]
start = 2027-01-05
handoff_time = "10:00"
handoff_timezone = "America/Toronto"
load = "balanced"      # A can only do 1 week in 4, so the others cover the difference
cycle_weeks = 8
"""


def write(tmp_path, body, name="team.toml"):
    p = tmp_path / name
    p.write_text(textwrap.dedent(body))
    return p


def assert_valid(result):
    assert all(ok for _, ok, _ in legal_checks(result))
    steady = evaluate(result.cycle, result.cfg.roles, result.cfg.people)
    if result.cfg.max_in_row:
        assert max(steady.longest_stretch.values()) <= result.cfg.max_in_row
    for wk in result.cycle:
        assert len(set(wk)) == len(wk)


class TestExamples:
    @pytest.mark.parametrize("example", sorted(EXAMPLES.glob("*.toml")), ids=lambda p: p.stem)
    def test_examples_solve(self, example):
        result = plan(load_config(example))
        assert_valid(result)
        assert all(result.proven.values())

    def test_same_input_same_schedule(self):
        assert plan(load_config(THREE)).schedule == plan(load_config(THREE)).schedule


class TestMonthlyCap:
    """Calendar-month caps are counted with the same day counter as `check`."""

    def test_late_handoff_makes_a_shift_count_8_days(self):
        # 10:00 Los Angeles is 19:00 Vienna: past the 17:00 workday end on both handoff days
        assert days_per_shift(load_config(THREE, handoff_time="10:00"), "Europe/Vienna") == 8
        assert days_per_shift(load_config(THREE, handoff_time="08:00"), "Europe/Vienna") == 7

    def test_handoff_after_midnight_counts_the_first_evening_in_the_west(self, tmp_path):
        # 01:00 Toronto is 22:00 the previous evening in Los Angeles, so the shift covers
        # 8 Los Angeles evenings: the first evening is the day before the Toronto handoff date
        cfg = load_config(write(tmp_path, SMALL), handoff_time="01:00")
        assert days_per_shift(cfg, "America/Los_Angeles") == 8

    def test_late_handoff_rules_out_equal_load_and_says_why(self):
        with pytest.raises(PlanError) as e:
            plan(load_config(THREE, handoff_time="10:00"))
        msg = str(e.value)
        assert "legal caps" in msg
        assert "counts as 8 on-call days in Vienna" in msg

    def test_early_handoff_keeps_every_month_within_the_cap(self):
        result = plan(load_config(THREE))  # 08:00 Los Angeles
        for person in ("Ana", "Ben"):
            months = monthly_days(result, person)
            assert len(months) >= 50
            assert max(months.values()) <= 10

    def test_balanced_load_works_with_late_handoff(self):
        cfg = load_config(THREE, handoff_time="10:00", load="balanced", cycle_weeks=16)
        result = plan(cfg)
        assert_valid(result)
        load = evaluate(result.cycle, cfg.roles, cfg.people).load
        assert sum(load["Ana"].values()) < 4  # fewer than an equal share of 4 per 16 weeks


class TestRollingCap:
    def test_cutover_respects_cap(self, tmp_path):
        # A did the last published week, so A's next shift must be at least 4 weeks after it.
        p = write(
            tmp_path,
            SMALL
            + """
            [[published]]
            week = 2026-12-29
            primary = "A"
            secondary = "B"
            """,
        )
        result = plan(load_config(p))
        first = next(w for w, wk in enumerate(result.cycle) if "A" in wk)
        assert first >= 3
        assert_valid(result)

    def test_equal_load_impossible_is_explained(self, tmp_path):
        p = write(tmp_path, SMALL.replace('load = "balanced"', 'load = "equal"'))
        with pytest.raises(PlanError, match="balanced"):
            plan(load_config(p))

    def test_checker_catches_violation(self):
        people = {"A": "Vienna", "B": "Toronto", "C": "Toronto", "D": "Toronto"}
        sched = [("A", "B"), ("C", "D"), ("D", "A"), ("B", "C")]  # A twice within 3 weeks
        rep = evaluate(sched, ["Primary", "Secondary"], people, limits_days={"Vienna": (10, 28)})
        assert not rep.legal_ok


class TestRules:
    def test_adding_a_person(self):
        cfg = load_config(THREE, add=["Zed=San Francisco"])
        assert cfg.cycle == 9
        assert any("Zed" in wk for wk in plan(cfg).cycle)

    def test_role_restrictions_never_together_and_rules_file(self):
        result = plan(load_config(EXAMPLES / "custom-rules.toml"))
        assert all(wk[0] != "Sol" for wk in result.cycle)  # Secondary only
        assert not any({"Nia", "Quin"} <= set(wk) for wk in result.cycle)
        platform = {"Oto", "Pam", "Rae"}  # rule from custom_rules.py
        assert all(len(platform & set(wk)) <= 1 for wk in result.cycle)
        assert "Weeks the new hire is on call without a senior" in result.goals

    def test_min_weeks_off(self):
        result = plan(load_config(EXAMPLES / "primary-only.toml"))
        steady = evaluate(result.cycle, result.cfg.roles, result.cfg.people)
        assert all(min(g) >= 3 for g in steady.gaps.values() if g)

    def test_diagnosis_names_the_blocking_rule(self, tmp_path):
        p = write(
            tmp_path,
            """
            [offices.X]
            timezone = "UTC"
            [[people]]
            name = "A"
            office = "X"
            [[people]]
            name = "B"
            office = "X"
            [[people]]
            name = "C"
            office = "X"
            [rotation]
            start = 2027-01-05
            never_together = [["A", "B"]]
            """,
        )
        with pytest.raises(PlanError, match="never_together"):
            plan(load_config(p))


class TestConfig:
    @pytest.mark.parametrize(
        "body, msg",
        [
            (
                '[offices.X]\ntimezone="UTC"\n[[people]]\nname="A"\noffice="Nope"\n'
                "[rotation]\nstart=2027-01-05",
                "unknown office",
            ),
            (
                '[offices.X]\ntimezone="UTC"\nmax_oncall_days=10\nper=30\n'
                '[[people]]\nname="A"\noffice="X"',
                "divisible by 7",
            ),
            ('[offices.X]\ntimezone="Mars/Olympus"', "unknown timezone"),
        ],
    )
    def test_config_errors(self, tmp_path, body, msg):
        with pytest.raises(ConfigError, match=msg):
            load_config(write(tmp_path, body))


class TestCli:
    def test_plan_writes_csv(self, tmp_path):
        out = tmp_path / "s.csv"
        res = CliRunner().invoke(
            cli, ["plan", str(EXAMPLES / "primary-only.toml"), "--csv", str(out), "--weeks", "10"]
        )
        assert res.exit_code == 0, res.output
        assert "# Example: primary only" in res.output
        lines = out.read_text().splitlines()
        assert lines[0] == "shift_start,on call,on call_office"
        assert len(lines) == 11
        assert lines[1].startswith(dt.date(2027, 2, 1).isoformat())

    def test_plan_reports_why_when_impossible(self):
        res = CliRunner().invoke(cli, ["plan", str(THREE), "--handoff-time", "10:00"])
        assert res.exit_code == 1
        assert "counts as 8 on-call days in Vienna" in res.output

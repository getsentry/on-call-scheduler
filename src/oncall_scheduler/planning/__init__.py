"""Plan weekly on-call rotations that meet a team's rules (`oncall-scheduler plan`).

Uses the OR-Tools CP-SAT solver. Calendar-month legal caps are counted with the same
after-hours day counter as `oncall-scheduler check`.
"""

from oncall_scheduler.planning.config import Config, ConfigError, LegalCap, load_config
from oncall_scheduler.planning.planner import Plan, PlanError, Rules, plan

__all__ = ["Config", "ConfigError", "LegalCap", "Plan", "PlanError", "Rules", "load_config", "plan"]

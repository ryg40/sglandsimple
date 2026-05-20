"""Stage-4 deep-agent package: planner + builder subagents.

Exposes the three MCP tool entry points the server registers:

- ``run_plan_task`` — emit a Plan from a goal (planner role)
- ``run_run_plan`` — execute a Plan (builder role) with optional re-plan
- ``run_deep_agent`` — plan -> run -> summarize convenience wrapper
"""

from .planner import run_plan_task  # noqa: F401
from .builder import run_run_plan, run_deep_agent  # noqa: F401
from .models import Plan, Step, StepResult  # noqa: F401

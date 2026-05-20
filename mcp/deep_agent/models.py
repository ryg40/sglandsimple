"""Typed models for deep-agent plans, steps, and results.

Validation is two-layered:

1. Pydantic ensures shape (required fields, types, defaults).
2. ``validate_against_catalog`` rejects any step whose tool name isn't in
   the current MCP tool allowlist. The catalog is resolved at runtime
   (not at import time) so tests and future tool additions don't bake a
   stale allowlist into the schema.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


StepStatus = Literal["ok", "error", "skipped"]


class Step(BaseModel):
    id: str = Field(..., description="Stable step id used by depends_on.")
    tool: str = Field(..., description="MCP tool name to invoke for this step.")
    args: dict[str, Any] = Field(default_factory=dict)
    parallel: bool = Field(False, description="May run concurrently with siblings sharing depends_on.")
    depends_on: list[str] = Field(default_factory=list)
    rationale: str = Field("", description="One-sentence reason this step is in the plan.")


class Plan(BaseModel):
    plan_id: str = Field("", description="Server-assigned UUID; filled in by the planner.")
    goal: str
    rationale: str = ""
    steps: list[Step]

    def validate_against_catalog(self, tool_names: set[str]) -> None:
        ids = {s.id for s in self.steps}
        if len(ids) != len(self.steps):
            raise ValueError("step ids must be unique")
        for s in self.steps:
            if s.tool not in tool_names:
                raise ValueError(f"step {s.id!r} uses unknown tool {s.tool!r}")
            for dep in s.depends_on:
                if dep not in ids:
                    raise ValueError(f"step {s.id!r} depends on unknown step {dep!r}")


class StepResult(BaseModel):
    step_id: str
    status: StepStatus
    output: str = ""
    error: str = ""


class RunSummary(BaseModel):
    plan_id: str
    goal: str
    results: list[StepResult]
    summary: str = ""
    replanned: bool = False
    error: str = ""

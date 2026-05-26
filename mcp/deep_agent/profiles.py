"""Deep Agent platform — profile schema + loader (Stage 21, S21.profile.1).

A *profile* is the declarative unit of scope for one system-specific agent
(see ``docs/deep_agent_platform.md``). Profiles live in ``profiles.yaml``
(path from ``DEEP_AGENT_PROFILES_FILE``) and are validated at load time —
**invalid profiles fail fast** so a typo can't silently widen an agent's reach.

Each profile compiles into a ``deepagents`` subagent spec:

- ``tools`` — LangChain tools resolved from ``allowed_tools`` (each wraps the
  MCP ``_dispatch_tool`` seam in ``server.py``).
- ``interrupt_on`` — ``{tool: True}`` for every tool in ``write_tools`` (per-tool
  HITL). ``write_tools`` must be a subset of ``allowed_tools``.
- ``model`` / ``system_prompt`` — per-agent overrides.

Agents with ``graph`` set compile to a ``CompiledSubAgent`` wrapping an existing
LangGraph (e.g. ``ask_data``, ``docs_agent``) instead of a prompt agent.

This module deliberately does **not** build the orchestrator or import
``deepagents`` at module load — it only parses/validates and exposes typed
profiles plus helpers. ``runtime.py`` (S21.orch.1) consumes these.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

WritePolicy = Literal["read_only", "dry_run_only", "write_capable"]

_DEFAULT_PROFILES_FILE = os.path.join(os.path.dirname(__file__), "profiles.yaml")

# Tools the orchestrator/runtime injects itself; a profile must never list them
# (the Stage-4 recursion guard: no agent re-enters the agent runtime).
_RESERVED_TOOLS = {"task", "write_todos", "plan_task", "run_plan", "deep_agent"}


class AgentProfile(BaseModel):
    """One system-specific agent's scope. Compiles to a deepagents subagent."""

    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    model: str = ""  # "" => inherit default/orchestrator model
    allowed_tools: list[str] = Field(default_factory=list)
    write_tools: list[str] = Field(default_factory=list)
    write_policy: WritePolicy = "read_only"
    required_capability: str | None = None
    context_packs: list[str] = Field(default_factory=list)
    # When set, this agent is a CompiledSubAgent wrapping an existing graph
    # (e.g. "ask_data", "docs_agent") rather than a prompt-driven subagent.
    graph: str | None = None
    budget_tokens: int = Field(default=40000, gt=0)
    max_steps: int = Field(default=15, gt=0)

    @model_validator(mode="after")
    def _check(self) -> "AgentProfile":
        # write_tools must be a subset of allowed_tools.
        extra = set(self.write_tools) - set(self.allowed_tools)
        if extra:
            raise ValueError(
                f"profile {self.name!r}: write_tools {sorted(extra)} not in allowed_tools"
            )
        # Reserved tools may not be listed by a profile.
        reserved = (set(self.allowed_tools) | set(self.write_tools)) & _RESERVED_TOOLS
        if reserved:
            raise ValueError(
                f"profile {self.name!r}: may not list reserved runtime tools {sorted(reserved)}"
            )
        # A read_only profile may not declare write tools.
        if self.write_policy == "read_only" and self.write_tools:
            raise ValueError(
                f"profile {self.name!r}: write_policy=read_only but write_tools is non-empty"
            )
        # write_capable / dry_run_only with write tools must name a capability
        # (least privilege: a writer agent is gated by a Stage-19 capability).
        if self.write_tools and not self.required_capability:
            raise ValueError(
                f"profile {self.name!r}: write_tools require a required_capability"
            )
        # Graph-backed agents don't take an allowlist (the graph owns its tools).
        if self.graph and self.allowed_tools:
            raise ValueError(
                f"profile {self.name!r}: graph-backed agent must not set allowed_tools"
            )
        return self

    def interrupt_on(self) -> dict[str, bool]:
        """deepagents per-tool HITL map for this profile's write tools."""
        return {t: True for t in self.write_tools}


class OrchestratorProfile(BaseModel):
    description: str = Field(..., min_length=1)
    model: str = ""
    budget_tokens: int = Field(default=20000, gt=0)
    max_steps: int = Field(default=8, gt=0)


class PlatformProfiles(BaseModel):
    orchestrator: OrchestratorProfile
    agents: list[AgentProfile]

    @model_validator(mode="after")
    def _unique_names(self) -> "PlatformProfiles":
        names = [a.name for a in self.agents]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate agent names: {sorted(dupes)}")
        return self

    def by_name(self, name: str) -> AgentProfile | None:
        return next((a for a in self.agents if a.name == name), None)


def profiles_path() -> str:
    return os.environ.get("DEEP_AGENT_PROFILES_FILE") or _DEFAULT_PROFILES_FILE


def load_profiles(path: str | None = None) -> PlatformProfiles:
    """Parse + validate profiles. Raises (fail-fast) on any invalid profile."""
    p = path or profiles_path()
    with open(p, "r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}
    try:
        return PlatformProfiles.model_validate(raw)
    except Exception as e:  # noqa: BLE001 — surface a clear startup error
        raise RuntimeError(f"invalid deep-agent profiles in {p}: {e}") from e


@lru_cache(maxsize=1)
def get_profiles() -> PlatformProfiles:
    """Cached profiles for the process. Call ``get_profiles.cache_clear()`` in tests."""
    return load_profiles()


def validate_against_catalog(profiles: PlatformProfiles, tool_names: set[str]) -> list[str]:
    """Return human-readable errors for allowed_tools that aren't real MCP tools.

    Kept separate from schema validation because the live tool catalog is only
    knowable at runtime (connectors register tools dynamically). ``runtime.py``
    calls this once the server's TOOLS + connector tools are known.
    """
    errors: list[str] = []
    for a in profiles.agents:
        if a.graph:
            continue
        unknown = [t for t in a.allowed_tools if t not in tool_names]
        if unknown:
            errors.append(f"profile {a.name!r}: unknown tools {sorted(unknown)}")
    return errors

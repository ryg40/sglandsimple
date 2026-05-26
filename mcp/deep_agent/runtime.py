"""Deep Agent platform runtime — orchestrator + per-tool allowlist (S21.orch.1).

Compiles the validated profiles (``profiles.py``) into a ``deepagents`` agent:

- The **orchestrator** is a thin router: ``create_deep_agent`` with the
  compiled subagents and *no system tools of its own* (deepagents injects the
  built-in ``task`` delegation + ``write_todos`` planning tools).
- Each profile becomes a subagent dict whose ``tools`` are LangChain tools that
  wrap the single MCP dispatch seam (``server._dispatch_tool``). A subagent can
  therefore only call the tools in its ``allowed_tools`` — anything else isn't
  in its toolset at all, and a fabricated call is reported as a **policy
  event** (fails closed), satisfying per-tool allowlist enforcement.
- Graph-backed profiles (``graph: ask_data`` / ``docs_agent``) compile to a
  ``CompiledSubAgent`` wrapping the existing LangGraph instead.

Model selection reuses the role system in ``llm.py`` (orchestrator → planner
role for routing; subagents → builder role by default, or their own ``model``).

Tool *execution*, HITL interrupts, and run persistence are layered on in
S21.runtime.1 / S21.hitl.1; this module provides the agent assembly + the
allowlist boundary they build on.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from langchain_core.tools import StructuredTool

from llm import chat_model
from .context import render_packs
from .profiles import AgentProfile, PlatformProfiles, get_profiles, validate_against_catalog

# Recorded policy events (denied / out-of-allowlist tool attempts). In S21.security.1
# these persist to Mongo; here we keep an in-process ring so the boundary is
# observable and testable without the DB.
_POLICY_EVENTS: list[dict[str, Any]] = []


def policy_events() -> list[dict[str, Any]]:
    return list(_POLICY_EVENTS)


def _record_policy_event(agent: str, tool: str, reason: str) -> None:
    _POLICY_EVENTS.append({"agent": agent, "tool": tool, "reason": reason})


def _live_tool_names() -> set[str]:
    """Every tool the MCP server can dispatch — static tools + *all* connector
    tools, whether or not the connector is currently enabled.

    Connectors register their tool definitions regardless of `enabled` (a
    disabled connector still answers, just in mock/dry-run form), so we build
    the known universe from the connector *classes*. That way a profile naming
    a real-but-disabled connector tool (e.g. `jira_apply_staged` while
    `CONN_JIRA_ENABLED=false`) is valid config — the agent simply can't get a
    live result until the connector is enabled — while a genuinely unknown tool
    is still caught.
    """
    import server  # late import; server imports this package indirectly

    names = {t["name"] for t in server.TOOLS}
    # Runtime registry (if init_connectors already ran).
    try:
        for conn in server.list_connectors():
            for t in conn.tools():
                if t.get("name"):
                    names.add(t["name"])
    except Exception:
        pass
    # Connector classes — complete set even before/without init.
    try:
        from connectors import _CONNECTOR_CLASSES

        for cls in _CONNECTOR_CLASSES.values():
            try:
                for t in cls(enabled=False).tools():
                    if t.get("name"):
                        names.add(t["name"])
            except Exception:
                continue
    except Exception:
        pass
    return names


def _make_mcp_tool(agent_name: str, tool_name: str, description: str, allowed: set[str]) -> StructuredTool:
    """Wrap one MCP tool as a LangChain tool bound to an agent's allowlist.

    The wrapper double-checks membership at call time (defense in depth: even if
    a tool object leaks across agents, calling a tool outside this agent's
    allowlist fails closed and is recorded).
    """
    import server

    async def _call(**kwargs: Any) -> str:
        if tool_name not in allowed:
            _record_policy_event(agent_name, tool_name, "outside allowlist")
            return f"[policy] tool {tool_name!r} is not permitted for agent {agent_name!r}"
        result = await server._dispatch_tool(tool_name, kwargs)
        # Flatten the MCP envelope to text for the agent loop.
        if isinstance(result, dict):
            blocks = result.get("content") or []
            text = "\n".join(b.get("text", "") for b in blocks if isinstance(b, dict))
            if result.get("isError"):
                return f"[tool error] {text}"
            return text or json.dumps(result)
        return str(result)

    return StructuredTool.from_function(
        coroutine=_call,
        name=tool_name,
        description=description or f"MCP tool {tool_name}",
    )


def _tool_description(tool_name: str) -> str:
    import server

    for t in server.TOOLS:
        if t.get("name") == tool_name:
            return t.get("description", "")
    try:
        from connectors import _CONNECTOR_CLASSES

        for cls in _CONNECTOR_CLASSES.values():
            try:
                for t in cls(enabled=False).tools():
                    if t.get("name") == tool_name:
                        return t.get("description", "")
            except Exception:
                continue
    except Exception:
        pass
    return ""


def _subagent_system_prompt(profile: AgentProfile) -> str:
    parts = [profile.description.strip()]
    pack = render_packs(profile.context_packs)
    if pack:
        parts += ["", "Reference material:", pack]
    if profile.write_tools:
        parts += [
            "",
            "Write tools require human approval (HITL); propose changes as dry-run "
            "and never assume a write succeeded without an approval.",
        ]
    return "\n".join(parts)


def _graph_runnable(name: str):
    """Return a compiled LangGraph for a graph-backed profile, or None."""
    # Imported lazily; these modules require the LLM env to import.
    if name == "ask_data":
        import ask_data

        return ask_data.build_graph()
    if name == "docs_agent":
        import docs_agent

        return docs_agent.build_docs_agent_graph()
    return None


def _compile_subagent(profile: AgentProfile, live_tools: set[str]) -> Any:
    """Compile one profile into a deepagents subagent dict or CompiledSubAgent."""
    from deepagents import CompiledSubAgent

    if profile.graph:
        runnable = _graph_runnable(profile.graph)
        if runnable is None:
            raise RuntimeError(f"profile {profile.name!r}: graph {profile.graph!r} not available")
        return CompiledSubAgent(
            name=profile.name,
            description=profile.description.strip(),
            runnable=runnable,
        )

    allowed = set(profile.allowed_tools)
    tools = [
        _make_mcp_tool(profile.name, t, _tool_description(t), allowed)
        for t in profile.allowed_tools
    ]
    sub: dict[str, Any] = {
        "name": profile.name,
        "description": profile.description.strip(),
        "system_prompt": _subagent_system_prompt(profile),
        "tools": tools,
    }
    # Model: every model in this stack goes through our single OpenAI-compatible
    # upstream, so we hand deepagents a configured BaseChatModel rather than a
    # provider string (which would resolve to a real OpenAI/Bedrock endpoint).
    # A profile's `model` selects the role ("planner"/"builder") used to resolve
    # base_url/model/key; default subagents run on the builder role.
    role = profile.model if profile.model in ("planner", "builder", "default") else "builder"
    sub["model"] = chat_model(role=role)
    if profile.write_tools:
        sub["interrupt_on"] = profile.interrupt_on()
    return sub


def build_orchestrator(profiles: PlatformProfiles | None = None, checkpointer: Any = None):
    """Assemble the thin router orchestrator over the compiled subagents.

    Validates every profile's tools against the live MCP catalog first
    (fail-fast): a profile naming a tool the server can't dispatch is a config
    error, surfaced here rather than at first run.
    """
    from deepagents import create_deep_agent

    profiles = profiles or get_profiles()

    catalog_errors = validate_against_catalog(profiles, _live_tool_names())
    if catalog_errors:
        raise RuntimeError("deep-agent profile/catalog mismatch: " + "; ".join(catalog_errors))

    live = _live_tool_names()
    subagents = [_compile_subagent(a, live) for a in profiles.agents]

    orch = profiles.orchestrator
    orch_prompt = (
        orch.description.strip()
        + "\n\nDelegate the goal to exactly one of the available subagents using the "
        "`task` tool, choosing by each subagent's description. Do not attempt the "
        "work yourself; you have no system tools."
    )
    # Orchestrator routes; it gets no system tools (only the built-in task/
    # write_todos that deepagents injects). Routing is a small classification
    # task → planner role. Pass a configured BaseChatModel (our upstream), not
    # a provider string.
    orch_role = orch.model if orch.model in ("planner", "builder", "default") else "planner"
    return create_deep_agent(
        model=chat_model(role=orch_role),
        tools=[],
        system_prompt=orch_prompt,
        subagents=subagents,
        checkpointer=checkpointer,
    )

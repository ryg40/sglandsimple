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

import asyncio
import json
import time
from typing import Any, Callable, Literal

from langchain_core.tools import StructuredTool

from llm import role_runtime
from .provider import chat_model_for_role
from . import observability as obs
from .context import render_packs
from .profiles import (
    AgentProfile,
    OrchestratorProfile,
    PlatformProfiles,
    get_profiles,
    validate_against_catalog,
)

# Recorded policy events (denied / out-of-allowlist tool attempts). In S21.security.1
# these persist to Mongo; here we keep an in-process ring so the boundary is
# observable and testable without the DB.
_POLICY_EVENTS: list[dict[str, Any]] = []


def policy_events() -> list[dict[str, Any]]:
    return list(_POLICY_EVENTS)


def _record_policy_event(agent: str, tool: str, reason: str, run_id: str = "", detail: dict[str, Any] | None = None) -> None:
    """Record an out-of-allowlist tool attempt.

    Kept in the in-process ring (back-compat + tests) and, via S21.security.1,
    also persisted to the audit trail and counted. Audit persistence is async;
    the wrapper that triggers this is already async so we schedule it without
    blocking the fail-closed return.
    """
    _POLICY_EVENTS.append({"agent": agent, "tool": tool, "reason": reason})
    obs.incr("policy_denied_total", agent=agent or "(none)")
    try:
        asyncio.get_running_loop().create_task(
            obs.record_audit("policy_denied", run_id=run_id, agent=agent, tool=tool, reason=reason, detail=detail)
        )
    except RuntimeError:
        # No running loop (sync/test path): the ring + counter still recorded it.
        pass


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
            # detail is redacted inside record_audit; pass the attempted args so
            # the audit trail shows *what* was attempted out of policy.
            _record_policy_event(agent_name, tool_name, "outside allowlist", detail={"args": kwargs})
            return f"[policy] tool {tool_name!r} is not permitted for agent {agent_name!r}"
        obs.incr("tool_calls_total", agent=agent_name, tool=tool_name)
        started = time.time()
        result = await server._dispatch_tool(tool_name, kwargs)
        obs.log_event(
            "tool",
            agent=agent_name,
            tool=tool_name,
            ms=int((time.time() - started) * 1000),
            error=bool(isinstance(result, dict) and result.get("isError")),
        )
        # Flatten the MCP envelope to text for the agent loop.
        if isinstance(result, dict):
            blocks = result.get("content") or []
            text = "\n".join(b.get("text", "") for b in blocks if isinstance(b, dict))
            if result.get("isError"):
                obs.incr("tool_errors_total", agent=agent_name, tool=tool_name)
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


def _last_human_text(messages: list[Any]) -> str:
    """Pull the task text deepagents' `task` tool handed the subagent.

    deepagents invokes a CompiledSubAgent with ``{"messages": [...]}`` where the
    last human turn carries the delegated instruction. The native ask_data /
    docs graphs don't speak `messages`, so the adapter below lifts this text and
    feeds it to their own input contract."""
    for m in reversed(messages or []):
        content = getattr(m, "content", None)
        role = getattr(m, "type", None) or (m.get("role") if isinstance(m, dict) else None)
        if content is None and isinstance(m, dict):
            content = m.get("content")
        if not content:
            continue
        if role in (None, "human", "user"):
            if isinstance(content, list):
                return "\n".join(str(c.get("text", c)) if isinstance(c, dict) else str(c) for c in content)
            return str(content)
    return ""


def _messages_adapter(run, label: str):
    """Wrap a native graph/coroutine as a deepagents-compatible CompiledSubAgent.

    deepagents requires a CompiledSubAgent's runnable to (a) accept a state with
    a ``messages`` key and (b) return one (validated in
    ``deepagents.middleware.subagents``). The native ask_data/docs graphs use
    their own state shapes (``AskDataState.question`` / ``DocsAgentState``), so
    this builds a tiny ``messages``-in / ``messages``-out graph whose single node
    runs ``run(question) -> markdown`` and emits the result as an ``AIMessage``.
    Without this, the orchestrator→graph delegation hangs/never resolves
    (the wrapped graph ignores ``messages`` and returns no ``messages`` key)."""
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph

    # MessagesState already declares `messages` with the add_messages reducer at
    # module load — avoids the forward-ref pitfalls of a locally-defined TypedDict
    # and satisfies the deepagents CompiledSubAgent `messages` contract.
    async def _node(state: dict) -> dict:
        question = _last_human_text(state.get("messages", []))
        try:
            text = await run(question)
        except Exception as e:  # noqa: BLE001 — surface as the agent's final report
            text = f"[{label}] failed: {type(e).__name__}: {e}"
        return {"messages": [AIMessage(content=text or f"[{label}] produced no output")]}

    g = StateGraph(MessagesState)
    g.add_node(label, _node)
    g.add_edge(START, label)
    g.add_edge(label, END)
    return g.compile()


def _graph_runnable(name: str):
    """Return a deepagents-compatible compiled graph for a graph-backed profile.

    The native graphs are wrapped in a ``messages``-in/out adapter so the
    orchestrator's CompiledSubAgent delegation works (see ``_messages_adapter``).
    """
    # Imported lazily; these modules require the LLM env to import.
    if name == "ask_data":
        import ask_data

        async def _run(question: str) -> str:
            state = await ask_data.run_ask_data(question or "Summarize the available data.")
            return ask_data.render_markdown(
                state.final, state.spec_error, question=question
            )

        return _messages_adapter(_run, "ask_data")
    if name == "docs_agent":
        import docs_agent

        async def _run(_question: str) -> str:
            result = await docs_agent.run_docs_agent()
            return json.dumps(result, indent=2, default=str)

        return _messages_adapter(_run, "docs_agent")
    return None


def _subagent_role(profile: AgentProfile) -> str:
    """The llm.py role a profile resolves to. A profile's ``model`` names a
    role ("planner"/"builder"/"default"); anything else falls back to builder."""
    return profile.model if profile.model in ("planner", "builder", "default") else "builder"


def _orchestrator_role(orch: OrchestratorProfile) -> str:
    """Routing is a small classification task → planner role by default."""
    return orch.model if orch.model in ("planner", "builder", "default") else "planner"


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
    # Model: hand deepagents a configured BaseChatModel rather than a provider
    # string. A profile's `model` selects the role ("planner"/"builder") used to
    # resolve base_url/model/key; default subagents run on the builder role.
    # `chat_model_for_role` honors the per-role provider switch (S21.bedrock.1):
    # OpenAI-compatible by default, ChatBedrockConverse when the role's provider
    # env is `bedrock`.
    sub["model"] = chat_model_for_role(role=_subagent_role(profile))
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
    return create_deep_agent(
        model=chat_model_for_role(role=_orchestrator_role(orch)),
        tools=[],
        system_prompt=orch_prompt,
        subagents=subagents,
        checkpointer=checkpointer,
    )


# ---------------------------------------------------------------------------
# Runtime API (S21.runtime.1 + S21.hitl.1)
#
# Typed run lifecycle over the orchestrator: start (route + run to the first
# HITL pause or completion), status, resume (approve/reject/edit), cancel,
# artifacts. Runs persist to DEEP_AGENT_RUN_COLLECTION; the orchestrator is
# compiled with the Mongo checkpointer so a paused run survives a restart.
# ---------------------------------------------------------------------------

import os
import uuid

from pydantic import BaseModel, Field

RUN_COLLECTION = os.environ.get("DEEP_AGENT_RUN_COLLECTION", "deep_agent_runs")
DRY_RUN_ONLY = os.environ.get("DEEP_AGENT_DRY_RUN_ONLY", "true").lower() == "true"

RunStatus = Literal["running", "waiting_approval", "completed", "rejected", "cancelled", "error"]


def _dry_run_only() -> bool:
    """Read the dry-run guardrail fresh each resume so an env change takes
    effect without re-importing the module (the import-time ``DRY_RUN_ONLY``
    constant is kept for back-compat/tests)."""
    return os.environ.get("DEEP_AGENT_DRY_RUN_ONLY", "true").lower() == "true"


class PermissionDeniedError(Exception):
    """Resuming actor lacks the capability that gates the pending write tool.
    Distinct from ValueError so the web layer can map it to HTTP 403."""


class AgentRunStartRequest(BaseModel):
    goal: str = Field(..., min_length=1)
    agent: str | None = None  # omit → orchestrator routes
    context_refs: list[str] = Field(default_factory=list)
    mode: Literal["dry_run", "live"] = "dry_run"
    actor: str | None = None


class ApprovalRequest(BaseModel):
    """Typed payload surfaced at a HITL interrupt.

    Parsed from the LangChain ``HumanInTheLoopMiddleware`` interrupt value, which
    is a ``HITLRequest`` ``{action_requests: [{name, args, description}], ...}``.
    ``tool``/``payload`` are the first pending action's name/args; an agent
    pauses on exactly one write tool at a time in this platform, but
    ``action_count`` is surfaced so a resume can answer every pending action.
    """

    run_id: str
    tool: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    # The Stage-19 capability the resuming actor must hold to approve this write
    # (resolved from the owning agent profile). Empty ⇒ no capability gate.
    required_capability: str = ""
    # Number of pending action_requests in the interrupt (decisions must match).
    action_count: int = 1


class AgentRunRecord(BaseModel):
    run_id: str
    goal: str
    agent: str | None = None
    status: RunStatus = "running"
    mode: str = "dry_run"
    actor: str | None = None
    result_text: str = ""
    approval: ApprovalRequest | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    error: str = ""
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


async def _persist_run(rec: AgentRunRecord) -> None:
    from db import get_db

    rec.updated_at = time.time()
    await get_db()[RUN_COLLECTION].replace_one({"run_id": rec.run_id}, rec.model_dump(), upsert=True)


async def _load_run(run_id: str) -> AgentRunRecord | None:
    from db import get_db

    doc = await get_db()[RUN_COLLECTION].find_one({"run_id": run_id})
    if not doc:
        return None
    doc.pop("_id", None)
    return AgentRunRecord.model_validate(doc)


def _result_text(state: Any) -> str:
    """Pull the final assistant text out of a deep-agent result state."""
    msgs = state.get("messages") if isinstance(state, dict) else None
    if not msgs:
        return ""
    last = msgs[-1]
    content = getattr(last, "content", None) or (last.get("content") if isinstance(last, dict) else "")
    if isinstance(content, list):
        return "\n".join(str(c.get("text", c)) if isinstance(c, dict) else str(c) for c in content)
    return str(content or "")


def _capability_for_tool(tool: str) -> str:
    """The Stage-19 capability that gates a write ``tool``, via its owning agent
    profile's ``required_capability``. Empty string ⇒ no profile claims it as a
    write tool (so no capability gate applies)."""
    if not tool:
        return ""
    try:
        profiles = get_profiles()
    except Exception:  # noqa: BLE001 — never let profile load break a resume
        return ""
    for a in profiles.agents:
        if tool in a.write_tools and a.required_capability:
            return a.required_capability
    return ""


def _extract_interrupt(snapshot: Any, run_id: str) -> ApprovalRequest | None:
    """Parse a LangChain HITL interrupt into a typed ApprovalRequest.

    The ``HumanInTheLoopMiddleware`` interrupts with a ``HITLRequest``
    (``{action_requests: [{name, args, description}], review_configs: [...]}``).
    We surface the first pending action's tool/args and resolve the capability
    that gates it from the owning agent profile. A non-dict/legacy value is
    tolerated as a bare rationale so older checkpoints don't crash a resume."""
    if not (snapshot.tasks and snapshot.tasks[0].interrupts):
        return None
    val = snapshot.tasks[0].interrupts[0].value
    if isinstance(val, dict) and val.get("action_requests"):
        actions = val["action_requests"]
        first = actions[0] if actions else {}
        tool = first.get("name", "")
        return ApprovalRequest(
            run_id=run_id,
            tool=tool,
            payload=first.get("args", {}) or {},
            rationale=first.get("description", ""),
            required_capability=_capability_for_tool(tool),
            action_count=len(actions) or 1,
        )
    # Legacy / non-middleware interrupt value: keep it visible as a rationale.
    if isinstance(val, dict):
        tool = val.get("tool", "")
        return ApprovalRequest(
            run_id=run_id,
            tool=tool,
            payload=val.get("payload", val),
            rationale=val.get("rationale", ""),
            required_capability=_capability_for_tool(tool),
        )
    return ApprovalRequest(run_id=run_id, rationale=str(val))


async def _execute_run(run_id: str) -> None:
    """Background worker: run the deep-agent graph to completion or HITL pause.

    S21.runtime.1 intentionally returns `agent_run_start` quickly so web/MCP
    callers poll status instead of sitting behind a long LLM/subagent request.
    """
    from checkpointer import checkpointer_context

    rec = await _load_run(run_id)
    if rec is None or rec.status != "running":
        return

    goal = rec.goal
    if rec.agent:
        goal = f"Delegate this to the {rec.agent} subagent: {rec.goal}"

    agent_label = rec.agent or "(orchestrator)"
    obs.incr("runs_started_total", agent=agent_label)
    started = time.time()
    obs.log_event("run", event="start", run_id=run_id, agent=agent_label, mode=rec.mode)
    try:
        async with checkpointer_context() as saver:
            orch = build_orchestrator(checkpointer=saver)
            config = {"configurable": {"thread_id": run_id}}
            state = await orch.ainvoke({"messages": [{"role": "user", "content": goal}]}, config)
            snapshot = await orch.aget_state(config)
            approval = _extract_interrupt(snapshot, run_id) if snapshot.next else None
            rec.result_text = _result_text(state)
            if approval:
                rec.status = "waiting_approval"
                rec.approval = approval
                obs.incr("runs_waiting_approval_total", agent=agent_label)
            else:
                rec.status = "completed"
                obs.incr("runs_completed_total", agent=agent_label)
    except Exception as e:  # noqa: BLE001
        rec.status = "error"
        rec.error = f"{type(e).__name__}: {e}"
        obs.incr("runs_failed_total", agent=agent_label)
    elapsed = time.time() - started
    obs.observe_latency(agent_label, elapsed)
    obs.log_event("run", event="end", run_id=run_id, agent=agent_label, status=rec.status, ms=int(elapsed * 1000))
    await _persist_run(rec)


def _spawn_run(run_id: str) -> None:
    try:
        asyncio.get_running_loop().create_task(_execute_run(run_id))
    except RuntimeError:
        # Fallback for direct CLI/tests that call without an event loop.
        asyncio.run(_execute_run(run_id))


async def agent_run_start(req: AgentRunStartRequest) -> AgentRunRecord:
    """Start a run and return immediately with a pollable run_id.

    The background graph continues until completion, error, or HITL interrupt.
    Always dry-run unless mode=live AND the global DEEP_AGENT_DRY_RUN_ONLY
    guardrail is off (write tools still enforce their own gates).
    """
    rid = f"agent-{uuid.uuid4().hex[:12]}"
    rec = AgentRunRecord(run_id=rid, goal=req.goal, agent=req.agent, mode=req.mode, actor=req.actor)
    await _persist_run(rec)
    _spawn_run(rid)
    return rec


async def agent_run_status(run_id: str) -> AgentRunRecord | None:
    return await _load_run(run_id)


def _normalize_decision(decision: Any) -> tuple[bool, dict[str, Any] | None, str]:
    """Map a high-level resume decision to (is_reject, edited_args, reject_msg).

    Accepts: ``True``/``"approve"`` → approve; ``False``/``"reject"``/``None`` →
    reject; a dict with ``{"type":"edit","args":{...}}`` or bare edited args →
    edit; ``{"type":"reject","message":...}`` → reject with a message."""
    if isinstance(decision, dict):
        dtype = decision.get("type")
        if dtype == "reject":
            return True, None, str(decision.get("message", "Rejected by approver"))
        if dtype == "edit":
            return False, dict(decision.get("args") or decision.get("edited_action", {}).get("args", {})), ""
        if dtype == "approve":
            return False, None, ""
        # Bare dict ⇒ treat as edited args.
        return False, dict(decision), ""
    if decision in (False, "reject", "rejected", None):
        return True, None, "Rejected by approver"
    return False, None, ""


def _build_resume_decisions(
    approval: ApprovalRequest | None, is_reject: bool, edited_args: dict[str, Any] | None, reject_msg: str
) -> dict[str, list[dict[str, Any]]]:
    """Build the HumanInTheLoopMiddleware resume payload: one Decision per pending
    action_request, wrapped as ``{"decisions": [...]}`` (its required shape)."""
    count = approval.action_count if approval else 1
    if is_reject:
        one: dict[str, Any] = {"type": "reject", "message": reject_msg or "Rejected by approver"}
    elif edited_args is not None and approval is not None:
        one = {"type": "edit", "edited_action": {"name": approval.tool, "args": edited_args}}
    else:
        one = {"type": "approve"}
    return {"decisions": [dict(one) for _ in range(max(count, 1))]}


async def agent_run_resume(
    run_id: str,
    decision: Any,
    actor: str | None = None,
    actor_capabilities: list[str] | None = None,
) -> AgentRunRecord:
    """Resume a waiting_approval run with approve / edit / reject.

    Enforcement done here (authoritative gate, next to the write):
    - **Capability**: to *approve or edit* a write whose owning agent profile
      declares a ``required_capability``, the resuming ``actor_capabilities``
      must include it (Stage-19). A reject needs no capability.
    - **Dry-run guardrail**: when ``DEEP_AGENT_DRY_RUN_ONLY`` is on, an approve/
      edit is downgraded to a reject so no write tool executes — the run still
      resolves cleanly as rejected with a clear reason. (Write tools also keep
      their own ``*_WRITES_ENABLED`` gate downstream.)

    The resume value is the middleware's required ``{"decisions": [...]}`` shape,
    one decision per pending action_request.
    """
    from checkpointer import checkpointer_context
    from langgraph.types import Command

    rec = await _load_run(run_id)
    if rec is None:
        raise ValueError(f"unknown run {run_id!r}")
    if rec.status != "waiting_approval":
        raise ValueError(f"run {run_id!r} is {rec.status}, not waiting_approval")

    is_reject, edited_args, reject_msg = _normalize_decision(decision)
    needed = rec.approval.required_capability if rec.approval else ""
    pending_tool = rec.approval.tool if rec.approval else ""
    decision_kind = "reject" if is_reject else ("edit" if edited_args is not None else "approve")

    # Capability gate: only approvals/edits of a capability-gated write are checked.
    if not is_reject and needed:
        caps = set(actor_capabilities or [])
        if needed not in caps:
            await obs.record_audit(
                "approval",
                run_id=run_id,
                agent=rec.agent or "",
                tool=pending_tool,
                actor=actor,
                actor_capabilities=actor_capabilities,
                reason=f"denied: missing capability {needed!r}",
                detail={"decision": decision_kind, "required_capability": needed},
            )
            obs.incr("approvals_denied_total")
            raise PermissionDeniedError(
                f"actor {actor or '(unknown)'} lacks capability {needed!r} required to "
                f"approve tool {rec.approval.tool!r}"
            )

    # Dry-run guardrail: never let an approve reach a live write tool.
    forced_dry_run = False
    if not is_reject and _dry_run_only():
        is_reject = True
        reject_msg = "DEEP_AGENT_DRY_RUN_ONLY is on — write not applied (dry-run)."
        forced_dry_run = True

    # Audit the decision (with actor + capabilities) before it executes; this is
    # the policy-flag enforcement record (read_only never reaches here; a
    # dry_run downgrade is captured by forced_dry_run).
    await obs.record_audit(
        "approval",
        run_id=run_id,
        agent=rec.agent or "",
        tool=pending_tool,
        actor=actor,
        actor_capabilities=actor_capabilities,
        reason=("dry_run downgrade" if forced_dry_run else f"{decision_kind} accepted"),
        detail={"decision": decision_kind, "forced_dry_run": forced_dry_run, "edited_args": edited_args},
    )
    obs.incr("approvals_total", decision=("dry_run" if forced_dry_run else decision_kind))

    resume_payload = _build_resume_decisions(rec.approval, is_reject, edited_args, reject_msg)

    try:
        async with checkpointer_context() as saver:
            orch = build_orchestrator(checkpointer=saver)
            config = {"configurable": {"thread_id": run_id}}
            state = await orch.ainvoke(Command(resume=resume_payload), config)
            snapshot = await orch.aget_state(config)
            rec.result_text = _result_text(state)
            if snapshot.next:
                rec.status = "waiting_approval"
                rec.approval = _extract_interrupt(snapshot, run_id)
            else:
                rec.status = "rejected" if is_reject else "completed"
                rec.approval = None
            rec.actor = actor or rec.actor
            if forced_dry_run:
                rec.error = ""  # not an error; the result_text carries the reason
    except Exception as e:  # noqa: BLE001
        rec.status = "error"
        rec.error = f"{type(e).__name__}: {e}"
    await _persist_run(rec)
    return rec


async def agent_run_cancel(run_id: str) -> AgentRunRecord:
    rec = await _load_run(run_id)
    if rec is None:
        raise ValueError(f"unknown run {run_id!r}")
    if rec.status in ("completed", "rejected", "error"):
        return rec
    rec.status = "cancelled"
    obs.incr("runs_cancelled_total", agent=rec.agent or "(orchestrator)")
    obs.log_event("run", event="cancel", run_id=run_id, agent=rec.agent or "(orchestrator)")
    await _persist_run(rec)
    return rec


async def agent_run_artifacts(run_id: str) -> list[dict[str, Any]]:
    rec = await _load_run(run_id)
    return rec.artifacts if rec else []


def agent_profiles_list() -> list[dict[str, Any]]:
    """Public profile listing for the runtime API / UI."""
    profiles = get_profiles()
    out: list[dict[str, Any]] = []
    for a in profiles.agents:
        out.append(
            {
                "name": a.name,
                "description": a.description.strip(),
                "write_policy": a.write_policy,
                "required_capability": a.required_capability,
                "allowed_tools": a.allowed_tools,
                "write_tools": a.write_tools,
                "graph": a.graph,
            }
        )
    return out


def runtime_info() -> dict[str, Any]:
    """Redacted runtime descriptor for the Deep Agent platform (Stage 26).

    Surfaces the resolved provider/endpoint/model each role uses, plus the
    orchestrator and every system agent mapped to its role. No API keys are
    included. ``inherits_default`` flags a role with no role-specific env
    overrides (it rides the ``UPSTREAM_*`` defaults).
    """
    profiles = get_profiles()
    # The distinct roles in play, resolved once so the UI can show the role
    # table and the per-agent mapping consistently.
    roles = {
        "default": role_runtime("default"),
        "planner": role_runtime("planner"),
        "builder": role_runtime("builder"),
    }
    orch_role = _orchestrator_role(profiles.orchestrator)
    agents = []
    for a in profiles.agents:
        role = _subagent_role(a)
        rt = roles[role]
        agents.append(
            {
                "name": a.name,
                "description": a.description.strip(),
                "role": role,
                "graph": a.graph,
                "write_policy": a.write_policy,
                "required_capability": a.required_capability,
                "provider": rt["provider"],
                "endpoint": rt["endpoint"],
                "model": rt["model"],
                "inherits_default": rt["inherits_default"],
            }
        )
    # Per-role provider mapping (S21.bedrock.1): mostly openai-compatible; a
    # bedrock role reports its resolved model id/region or the config gap.
    try:
        from .provider import provider_summary

        providers = provider_summary()
    except Exception as e:  # noqa: BLE001
        providers = {"error": str(e)}
    return {
        "roles": roles,
        "orchestrator": {
            "description": profiles.orchestrator.description.strip(),
            "role": orch_role,
            **{k: roles[orch_role][k] for k in ("provider", "endpoint", "model", "inherits_default")},
        },
        "agents": agents,
        "providers": providers,
    }


def runtime_metrics(fmt: str = "json") -> dict[str, Any] | str:
    """Observability snapshot for the platform (S21.obs.1).

    ``fmt="json"`` returns the structured metrics snapshot plus the recent
    policy-event ring and budget limit; ``fmt="prometheus"`` returns the text
    exposition format for a scraper.
    """
    if fmt == "prometheus":
        return obs.metrics_prometheus()
    snap = obs.metrics_snapshot()
    snap["policy_events_recent"] = policy_events()[-25:]
    snap["audit_recent"] = obs.audit_events(limit=25)
    try:
        from .budget import budget_limit

        snap["budget_per_call"] = budget_limit()
    except Exception:  # noqa: BLE001
        snap["budget_per_call"] = 0
    return snap

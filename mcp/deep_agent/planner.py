"""Planner subagent: goal -> Plan.

A single-node LangGraph runs one structured-LLM call against the
planner role (defaults to UPSTREAM_*) and persists the resulting Plan
to Mongo under ``db.deep_agent_plans``. Returning a typed Plan is the
hand-off contract with the builder.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from checkpointer import checkpointer_context
from db import get_db
from llm import structured

from .budget import budget_limit, log_event, token_count_estimate
from .catalog import catalog_markdown, tool_names
from .models import Plan


PLAN_SYSTEM = """\
You are a planner. Decompose the user's goal into the smallest sequence
of concrete tool calls that achieves it. Output ONLY a JSON Plan.

Rules:
- Each step.tool MUST be one of the tools in the catalog. Do not invent.
- Each step.id is a short stable string (e.g. "s1", "lookup", "draft").
- depends_on lists step ids that must finish first. Empty for the first step.
- Set parallel=true ONLY when a step has identical depends_on as another
  step AND they truly do not interact (e.g. researching N independent
  topics, or drafting N independent files). Otherwise leave false.
- args MUST match the tool's inputSchema. Use exact field names.
- Prefer fewer steps. Never add a step unless its output is needed.
- For data lookups, prefer ask_data over raw mongo_query.
- Files live under /sandbox; fs_* paths must be relative (e.g. "draft.md").

Output schema (Pydantic Plan): goal, rationale, steps[{id,tool,args,parallel,depends_on,rationale}].
plan_id is assigned by the server — leave it as "" or omit.
"""


class PlannerState(BaseModel):
    goal: str
    context: str = ""
    catalog: str = ""
    plan: Plan | None = None
    error: str = ""


async def _discover_catalog(state: PlannerState) -> dict[str, Any]:
    return {"catalog": catalog_markdown()}


async def _plan(state: PlannerState) -> dict[str, Any]:
    user_parts = [
        "Tool catalog:",
        state.catalog,
        "",
        f"Goal: {state.goal}",
    ]
    if state.context:
        user_parts += ["", f"Context: {state.context}"]
    user = "\n".join(user_parts)

    # Budget pre-flight.
    prompt_tokens = token_count_estimate(PLAN_SYSTEM) + token_count_estimate(user)
    log_event("planner", "request", prompt_tokens, where="plan")
    if prompt_tokens > budget_limit():
        # Hard fail: planner prompts are intrinsically small; if we're
        # over budget the caller has stuffed an enormous context blob.
        return {"error": f"planner prompt exceeds budget ({prompt_tokens} > {budget_limit()})"}

    try:
        plan = await structured(Plan, PLAN_SYSTEM, user, role="planner")
    except Exception as e:  # noqa: BLE001
        return {"error": f"planner LLM call failed: {e}"}

    # Server-side validation against the live tool catalog.
    try:
        plan.validate_against_catalog(tool_names())
    except ValueError as e:
        return {"error": f"plan rejected by catalog validation: {e}"}

    plan.plan_id = str(uuid.uuid4())
    return {"plan": plan}


def _build_graph(checkpointer=None):
    g = StateGraph(PlannerState)
    g.add_node("discover_catalog", _discover_catalog)
    g.add_node("emit_plan", _plan)
    g.add_edge(START, "discover_catalog")
    g.add_edge("discover_catalog", "emit_plan")
    g.add_edge("emit_plan", END)
    return g.compile(checkpointer=checkpointer)


async def _persist_plan(plan: Plan, goal: str, context: str) -> None:
    db = get_db()
    await db["deep_agent_plans"].insert_one(
        {
            "_id": plan.plan_id,
            "goal": goal,
            "context": context,
            "plan": plan.model_dump(),
            "created_at": time.time(),
        }
    )


async def run_plan_task(goal: str, context: str = "") -> dict[str, Any]:
    """Run the planner end-to-end. Returns ``{plan: Plan} | {error: str}``."""
    async with checkpointer_context() as saver:
        graph = _build_graph(checkpointer=saver)
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        out = await graph.ainvoke({"goal": goal, "context": context}, config=config)

    state = PlannerState.model_validate(out)
    if state.error or state.plan is None:
        return {"error": state.error or "planner produced no plan"}
    await _persist_plan(state.plan, goal, context)
    return {"plan": state.plan}


async def replan(original: Plan, failed_step_id: str, error: str) -> Plan | None:
    """Re-plan in response to a step failure. Used by the builder."""
    failed = next((s for s in original.steps if s.id == failed_step_id), None)
    user_parts = [
        "The previous plan failed at one step.",
        "",
        "Original plan:",
        original.model_dump_json(indent=2),
        "",
        f"Failed step id: {failed_step_id}",
        f"Failed step tool: {failed.tool if failed else 'unknown'}",
        f"Failed step args: {failed.args if failed else {}}",
        f"Error: {error}",
        "",
        f"Goal: {original.goal}",
        "",
        "Tool catalog:",
        catalog_markdown(),
        "",
        "Emit a corrected Plan covering the remaining work. You may keep "
        "any already-completed step (everything before the failed one) "
        "out of the new plan — focus on what still needs doing.",
    ]
    user = "\n\n".join(user_parts)
    prompt_tokens = token_count_estimate(PLAN_SYSTEM) + token_count_estimate(user)
    log_event("planner", "request", prompt_tokens, where="replan")
    if prompt_tokens > budget_limit():
        return None
    try:
        plan = await structured(Plan, PLAN_SYSTEM, user, role="planner")
        plan.validate_against_catalog(tool_names())
    except Exception as e:  # noqa: BLE001
        print(f"[deep_agent.replan] failed: {e}", flush=True)
        return None
    plan.plan_id = str(uuid.uuid4())
    await _persist_plan(plan, original.goal, f"replan after step {failed_step_id} failed: {error}")
    return plan

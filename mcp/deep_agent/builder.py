"""Builder/executor subagent: Plan -> StepResult[].

Each step is dispatched through the MCP tool surface (``server._dispatch_tool``)
so the builder inherits the same validation, error reporting, and
catalog the rest of the system uses.

Parallel fan-out: steps whose ``parallel=True`` and whose ``depends_on``
matches the most-recently-completed dependency frontier are launched
concurrently via ``Send(...)``. Their outputs reduce back into shared
state via ``operator.add``.

The builder LLM is consulted at two points:

1. Per-step summarization — when a step's stdout/json output is large,
   the builder model condenses it before it's stored as ``StepResult.output``
   so later steps and the final summary stay inside the token budget.
2. Final run summary — a short natural-language wrap-up across all
   completed steps, returned alongside the structured results.

Re-plan on failure is delegated back to ``planner.replan``; one attempt
only, then the run ends with ``RunSummary.error`` set.
"""

from __future__ import annotations

import asyncio
import json
import operator
import os
import time
import uuid
from typing import Annotated, Any

from langgraph.constants import Send
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from checkpointer import checkpointer_context
from db import get_db
from llm import llm_client, llm_model

from .budget import budget_limit, log_event, token_count_estimate
from .catalog import focused_catalog_markdown
from .models import Plan, RunSummary, Step, StepResult


MAX_STEPS = int(os.environ.get("DEEP_AGENT_MAX_STEPS", "25"))
MAX_SECONDS = float(os.environ.get("DEEP_AGENT_MAX_SECONDS", "600"))
STEP_OUTPUT_SOFT_LIMIT = int(os.environ.get("DEEP_AGENT_STEP_OUTPUT_LIMIT", "4000"))


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class BuilderState(BaseModel):
    plan: Plan
    started_at: float = Field(default_factory=time.time)
    results: Annotated[list[StepResult], operator.add] = Field(default_factory=list)
    # Frontier of step ids that have already finished. The router picks
    # the next batch by comparing each step's depends_on against this set.
    completed: Annotated[list[str], operator.add] = Field(default_factory=list)
    replanned: bool = False
    error: str = ""

    # NB: Pydantic v2 doesn't reduce Annotated[...] in the schema by default,
    # but LangGraph's StateGraph reads the Annotated metadata at compile time.

    class Config:
        arbitrary_types_allowed = True


# ---------------------------------------------------------------------------
# Step dispatch — direct call into the server's tool dispatcher
# ---------------------------------------------------------------------------


async def _dispatch_step(step: Step) -> StepResult:
    # Late import: server pulls deep_agent.* at startup; we only need
    # the dispatcher at runtime.
    import server  # type: ignore

    try:
        payload = await server._dispatch_tool(step.tool, dict(step.args))
    except Exception as e:  # noqa: BLE001
        return StepResult(step_id=step.id, status="error", error=f"{type(e).__name__}: {e}")

    is_error = bool(payload.get("isError"))
    content = payload.get("content") or []
    # Concatenate text parts into a single string output.
    text_parts: list[str] = []
    for block in content:
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
    output = "\n".join(text_parts).strip()
    if is_error:
        return StepResult(step_id=step.id, status="error", output="", error=output or "tool reported isError")
    return StepResult(step_id=step.id, status="ok", output=output)


async def _summarize_if_oversized(result: StepResult, plan_goal: str) -> StepResult:
    """If a step's output is too large, ask the builder model to condense."""
    if result.status != "ok" or not result.output:
        return result
    tokens = token_count_estimate(result.output)
    if tokens <= STEP_OUTPUT_SOFT_LIMIT:
        return result

    log_event("builder", "summarize_step", tokens, step_id=result.step_id)
    sys_prompt = (
        "You are condensing tool output for a downstream agent. Preserve "
        "exact identifiers, numbers, file paths, and direct quotes. Drop "
        "boilerplate. Target ~200 words."
    )
    user = (
        f"Goal: {plan_goal}\n"
        f"Tool output for step {result.step_id}:\n\n{result.output}"
    )
    prompt_tokens = token_count_estimate(sys_prompt) + token_count_estimate(user)
    if prompt_tokens > budget_limit():
        # Truncate input instead — keep the head and tail.
        keep = max(1000, STEP_OUTPUT_SOFT_LIMIT * 4)
        truncated = result.output[: keep // 2] + "\n…[middle truncated]…\n" + result.output[-(keep // 2) :]
        user = f"Goal: {plan_goal}\nTool output (truncated):\n\n{truncated}"

    cli = llm_client("builder")
    try:
        r = await cli.chat.completions.create(
            model=llm_model("builder"),
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        condensed = (r.choices[0].message.content or "").strip()
    except Exception as e:  # noqa: BLE001
        log_event("builder", "summarize_failed", 0, step_id=result.step_id, err=str(e))
        return result

    return StepResult(step_id=result.step_id, status="ok", output=condensed)


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


async def _execute_step(payload: dict[str, Any]) -> dict[str, Any]:
    step: Step = payload["step"]
    goal: str = payload["goal"]
    # Focused toolbelt log so we can audit what each step had access to.
    log_event("builder", "step_start", 0, step_id=step.id, tool=step.tool)
    result = await _dispatch_step(step)
    result = await _summarize_if_oversized(result, goal)
    return {"results": [result], "completed": [step.id]}


def _route_next(state: BuilderState):
    """Return Sends for the next batch of ready steps, or 'finalize' to stop."""
    # Hard caps.
    if time.time() - state.started_at > MAX_SECONDS:
        return "finalize"
    if len(state.results) >= MAX_STEPS:
        return "finalize"
    # If any step errored, hand off to the failure handler.
    if any(r.status == "error" for r in state.results):
        return "handle_failure"

    completed_ids = set(state.completed)
    done_ids = {r.step_id for r in state.results}
    ready: list[Step] = []
    for s in state.plan.steps:
        if s.id in done_ids:
            continue
        if all(dep in completed_ids for dep in s.depends_on):
            ready.append(s)
    if not ready:
        return "finalize"

    # If there are parallel-eligible siblings (more than one ready), fan
    # them out. Otherwise dispatch the first.
    batch = [s for s in ready if s.parallel] or ready[:1]
    return [Send("execute_step", {"step": s, "goal": state.plan.goal}) for s in batch]


async def _handle_failure(state: BuilderState) -> dict[str, Any]:
    """First failure → replan once; second failure → set error and end."""
    if state.replanned:
        return {"error": "second failure after re-plan; aborting run"}

    failed = next((r for r in state.results if r.status == "error"), None)
    if failed is None:
        return {}

    from .planner import replan

    new_plan = await replan(state.plan, failed.step_id, failed.error)
    if new_plan is None:
        return {"error": f"re-plan failed; original error: {failed.error}"}

    # The re-plan is the new plan; its step ids are fresh, so we reset the
    # completed/results frontier but keep prior results for the summary.
    return {"plan": new_plan, "replanned": True, "completed": [], "results": []}


async def _finalize(state: BuilderState) -> dict[str, Any]:
    return {}


def _route_after_failure(state: BuilderState) -> str:
    if state.error:
        return "finalize"
    # Loop back to the router to pick up the new plan.
    return "route"


# ---------------------------------------------------------------------------
# Graph wiring
# ---------------------------------------------------------------------------


def _build_graph(checkpointer=None):
    g = StateGraph(BuilderState)
    # `route` is a no-op landing node; its conditional edge fans out.
    g.add_node("route", lambda state: {})
    g.add_node("execute_step", _execute_step)
    g.add_node("handle_failure", _handle_failure)
    g.add_node("finalize", _finalize)

    g.add_edge(START, "route")
    g.add_conditional_edges(
        "route",
        _route_next,
        # Possible labels: a list of Sends OR one of the str sentinels.
        ["execute_step", "finalize", "handle_failure"],
    )
    g.add_edge("execute_step", "route")
    g.add_conditional_edges("handle_failure", _route_after_failure, {"route": "route", "finalize": "finalize"})
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# Top-level entry points
# ---------------------------------------------------------------------------


async def _final_summary(plan: Plan, results: list[StepResult]) -> str:
    if not results:
        return ""
    sys_prompt = (
        "You are summarising the outcome of an automated plan. Produce a "
        "2-4 sentence wrap-up covering what was achieved, key outputs, and "
        "any failed steps. No preamble."
    )
    bullets = []
    for r in results:
        if r.status == "ok":
            bullets.append(f"- [{r.step_id} ok] {r.output[:600]}")
        else:
            bullets.append(f"- [{r.step_id} ERROR] {r.error}")
    user = f"Goal: {plan.goal}\n\nResults:\n" + "\n".join(bullets)

    prompt_tokens = token_count_estimate(sys_prompt) + token_count_estimate(user)
    log_event("builder", "final_summary", prompt_tokens)
    if prompt_tokens > budget_limit():
        # Drop to a deterministic listing rather than fail.
        return "\n".join(bullets[:10])

    cli = llm_client("builder")
    try:
        r = await cli.chat.completions.create(
            model=llm_model("builder"),
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        return (r.choices[0].message.content or "").strip()
    except Exception as e:  # noqa: BLE001
        log_event("builder", "final_summary_failed", 0, err=str(e))
        return "\n".join(bullets[:10])


async def _persist_run(plan_id: str, summary: RunSummary) -> None:
    db = get_db()
    await db["deep_agent_runs"].insert_one(
        {
            "_id": str(uuid.uuid4()),
            "plan_id": plan_id,
            "summary": summary.model_dump(),
            "created_at": time.time(),
        }
    )


async def run_run_plan(plan: Plan | None = None, plan_id: str | None = None) -> RunSummary:
    """Execute a plan. Either pass an inline Plan or a plan_id to load from Mongo."""
    if plan is None:
        if not plan_id:
            return RunSummary(plan_id="", goal="", results=[], error="must pass either plan or plan_id")
        db = get_db()
        doc = await db["deep_agent_plans"].find_one({"_id": plan_id})
        if not doc:
            return RunSummary(plan_id=plan_id, goal="", results=[], error=f"plan {plan_id} not found")
        plan = Plan.model_validate(doc["plan"])

    async with checkpointer_context() as saver:
        graph = _build_graph(checkpointer=saver)
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        out = await graph.ainvoke({"plan": plan}, config=config)

    state = BuilderState.model_validate(out)
    summary_text = await _final_summary(state.plan, state.results)
    summary = RunSummary(
        plan_id=state.plan.plan_id,
        goal=state.plan.goal,
        results=state.results,
        summary=summary_text,
        replanned=state.replanned,
        error=state.error,
    )
    await _persist_run(state.plan.plan_id, summary)
    return summary


async def run_deep_agent(goal: str, context: str = "") -> dict[str, Any]:
    """Convenience: plan -> run -> summary, returned as a single payload."""
    from .planner import run_plan_task

    planned = await run_plan_task(goal, context=context)
    if "error" in planned:
        return {"error": planned["error"]}
    plan: Plan = planned["plan"]
    summary = await run_run_plan(plan=plan)
    return {"plan": plan, "summary": summary}

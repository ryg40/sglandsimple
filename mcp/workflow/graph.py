"""Compiled LangGraph workflow graph definition for Stage 9."""

from __future__ import annotations

import datetime
from typing import Any

from langgraph.graph import START, END, StateGraph
from langgraph.types import interrupt

import db as dbmod
from .models import WorkflowState
from . import nodes


def route_after_finding(state: dict[str, Any]) -> str:
    """Conditional routing check rule: continue to epic mapping."""
    return "link_epic"


def build_workflow_graph() -> Any:
    """Consists of a StateGraph representing the compliance control lifecycle."""
    builder = StateGraph(WorkflowState)

    # 1. Add all nodes
    builder.add_node("capture_finding", nodes.capture_finding)
    builder.add_node("link_epic", nodes.link_epic)
    builder.add_node("generate_ticket", nodes.generate_ticket)
    builder.add_node("coding_branch", nodes.coding_branch)
    builder.add_node("open_pr_node", nodes.open_pr)
    builder.add_node("post_approval_docs_node", nodes.post_approval_docs)

    # 2. Configure edges flow
    builder.add_edge(START, "capture_finding")
    builder.add_conditional_edges("capture_finding", route_after_finding)
    builder.add_edge("link_epic", "generate_ticket")
    builder.add_edge("generate_ticket", "coding_branch")

    # Gate 1: Approval Interrupt before open_pr
    def approve_pr_gate(state: dict[str, Any]) -> dict[str, Any]:
        branch = state["artifacts"]["branch_name"]
        # Trigger standard human-in-the-loop validation
        decision = interrupt({
            "message": "Approve PR creation?",
            "preview": f"Branch: {branch} (checks: compliance, tests, review)"
        })
        if decision != "approve":
            raise ValueError(f"Workflow rejected by human-gate: PR creation declined.")
        return state

    builder.add_node("approve_pr_gate", approve_pr_gate)
    builder.add_edge("coding_branch", "approve_pr_gate")
    builder.add_edge("approve_pr_gate", "open_pr_node")

    # Gate 2: Approval Interrupt before doc updating
    def approve_docs_gate(state: dict[str, Any]) -> dict[str, Any]:
        pr_url = state["artifacts"].get("pr_url", "MOCK")
        decision = interrupt({
            "message": f"Approve Confluence log update linked to Pull Request {pr_url}?",
            "preview": "Title: Epic database audit compliance logs"
        })
        if decision != "approve":
            raise ValueError(f"Workflow rejected by human-gate: Confluence update declined.")
        return state

    builder.add_node("approve_docs_gate", approve_docs_gate)
    builder.add_edge("open_pr_node", "approve_docs_gate")
    builder.add_edge("approve_docs_gate", "post_approval_docs_node")

    builder.add_edge("post_approval_docs_node", END)

    # Compile with checkpoint or raw memory
    return builder.compile()


# ---------------------------------------------------------------------------
# Direct workflow execution wrapper tools
# ---------------------------------------------------------------------------


async def run_compliance_workflow(finding_id: str, resume_decision: str | None = None, checkpoint_id: str | None = None) -> dict[str, Any]:
    """Execute or resume compile graph run, recording checkpoint states into db."""
    graph = build_workflow_graph()

    # Generate or recover standard state run id
    run_id = checkpoint_id or f"run-{finding_id}"

    # Verify if run exists in DB
    existing = await dbmod.find_workflow_run(run_id)

    # Prepare configuration state for checkpoints
    config = {"configurable": {"thread_id": run_id}}

    if existing and resume_decision:
        # Resume flow
        state_input = None
        # We resume from the interruption by feeding the decision
        res = await graph.ainvoke(resume_decision, config)
    else:
        # Direct fresh start
        state_input = {
            "finding_id": finding_id,
            "epic_id": "",
            "step_index": 0,
            "artifacts": {},
            "status": "running"
        }
        res = await graph.ainvoke(state_input, config)

    # Determine status of compiled outputs (Interrupted vs Completed)
    status = "completed"
    next_action_preview = None

    state_desc = await graph.aget_state(config)
    if state_desc.next:
        # Run is interrupted / waiting for human approval
        status = "waiting_approval"
        # Extract the interrupt question preview
        if state_desc.tasks and state_desc.tasks[0].interrupts:
            next_action_preview = state_desc.tasks[0].interrupts[0].value

    # Prepare state payload for upsert
    run_doc = {
        "_id": run_id,
        "finding_id": finding_id,
        "epic_id": res.get("epic_id", "epic-rds-001"),
        "step_index": res.get("step_index", 0),
        "status": status,
        "artifacts": res.get("artifacts", {}),
        "dry_run": not dbmod.WORKFLOW_WRITES_ENABLED,
        "source": "workflow_run",
        "updated_at": datetime.datetime.utcnow().isoformat()
    }

    if dbmod.WORKFLOW_WRITES_ENABLED:
        try:
            await dbmod.upsert_workflow_run(run_id, run_doc)
        except Exception as e:  # noqa: BLE001
            print(f"[workflow run wrapper] failed to upsert run state: {e}", flush=True)

    return {
        "run_id": run_id,
        "status": status,
        "step_index": res.get("step_index", 0),
        "artifacts": res.get("artifacts", {}),
        "next_action_preview": next_action_preview,
    }

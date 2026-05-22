"""Stage 14 — Docs agent workflow: reconcile → triage → suggest → apply-gate.

This is the **checkpointed LangGraph `StateGraph`** form of the docs agent
(S14.agent.1). The flow is:

    reconcile → triage → suggest → apply_gate (interrupt) → apply_approved → END

1. **reconcile** — run the Confluence sync for public docs (`docs_sync`); actions
   are logged to `doc_sync_log` there. Respects the same dry-run gates as sync.
2. **triage** — flag stale / unreferenced docs as needs_attention / archivable
   (via `docs.derive_status` over full bodies, so the "unreferenced" check is
   accurate).
3. **suggest** — for needs_attention docs, ask the LLM for a short rationale and
   a *proposed* revised body. Proposals only — never auto-applied.
4. **apply_gate** — `interrupt()` surfaces the proposals and waits for a human
   decision. On resume, the decision names which slugs to apply (or "reject").
5. **apply_approved** — apply only the approved slugs via the audited
   `docs_upsert` (one revision per applied doc). Anything not approved is left
   untouched.

Because the graph is compiled with a checkpointer and keyed by `thread_id`, a
run pauses at `apply_gate` and is resumed later with the human's choice — the
human-in-the-loop apply gate the spec asks for.

`run_docs_agent()` is kept as a thin back-compat wrapper: it runs the graph up
to the gate (reconcile/triage/suggest) and returns the proposals without
applying — matching the previous procedural behavior and the
`DocsAgentResponse` shape the web layer already consumes.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from langgraph.graph import START, END, StateGraph
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import MemorySaver

import db as dbmod
import docs as docsmod
from docs_sync import run_docs_sync
from llm import structured


class DocSuggestion(BaseModel):
    rationale: str = Field(default="", description="One-paragraph why this doc needs work.")
    proposed_body_md: str = Field(default="", description="A full proposed revised Markdown body.")


SUGGEST_SYSTEM = """\
You are a documentation reviewer. You are given one wiki document's title and
Markdown body. Propose concrete improvements: fix unclear wording, flag broken
or stale references, modernize outdated commands/paths, and add any obviously
missing sections (e.g. a short summary or prerequisites).

Return:
- rationale: one short paragraph naming the specific issues you found.
- proposed_body_md: the FULL revised Markdown body (keep the author's intent and
  structure; do not invent facts you cannot infer from the original).

This is a proposal for human review — be conservative and preserve meaning.
"""


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------


class DocsAgentState(TypedDict, total=False):
    limit_suggestions: int
    reconcile: dict[str, Any]
    triage: list[dict[str, Any]]
    suggestions: list[dict[str, Any]]
    applied: list[dict[str, Any]]
    applied_any: bool
    # Full doc bodies stashed by triage so suggest doesn't reload them.
    docs_full: list[dict[str, Any]]
    # Set when resumed: which slugs the human approved.
    approved_slugs: list[str]


# ---------------------------------------------------------------------------
# Triage helper (shared with the procedural wrapper)
# ---------------------------------------------------------------------------


async def _triage(docs_full: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ref = docsmod._now()
    referenced = docsmod._referenced_slugs(docs_full)
    out: list[dict[str, Any]] = []
    for d in docs_full:
        derived = docsmod.derive_status(d, ref=ref, referenced=referenced)
        if derived in ("needs_attention", "archivable") and d.get("status") != "archived":
            reason = (
                "stale and unreferenced by other docs"
                if derived == "archivable"
                else f"not reviewed in over {docsmod.DOCS_REVIEW_DAYS} days"
            )
            out.append(
                {
                    "slug": d["slug"],
                    "title": d.get("title"),
                    "current_status": d.get("status"),
                    "suggested_status": derived,
                    "reason": reason,
                }
            )
    return out


async def _load_full_docs() -> list[dict[str, Any]]:
    listing = await dbmod.docs_list(include_archived=False)
    docs_full: list[dict[str, Any]] = []
    for d in listing:
        fd = await dbmod.docs_get(d["slug"])
        if fd:
            docs_full.append(fd)
    return docs_full


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


async def _node_reconcile(state: DocsAgentState) -> dict[str, Any]:
    # Phase 1 — reconcile (dry-run unless all sync gates are on).
    return {"reconcile": await run_docs_sync()}


async def _node_triage(state: DocsAgentState) -> dict[str, Any]:
    docs_full = await _load_full_docs()
    return {"triage": await _triage(docs_full), "docs_full": docs_full}


async def _node_suggest(state: DocsAgentState) -> dict[str, Any]:
    limit = max(0, int(state.get("limit_suggestions", 3)))
    docs_full: list[dict[str, Any]] = state.get("docs_full", [])
    by_slug = {d["slug"]: d for d in docs_full}
    triage = state.get("triage", [])
    targets = [t for t in triage if t["suggested_status"] == "needs_attention"][:limit]

    suggestions: list[dict[str, Any]] = []
    for t in targets:
        doc = by_slug.get(t["slug"], {})
        user = f"Title: {doc.get('title')}\n\nBody:\n{doc.get('body_md','')}"
        try:
            out = await structured(DocSuggestion, SUGGEST_SYSTEM, user, temperature=0.2)
            suggestions.append(
                {
                    "slug": t["slug"],
                    "title": t["title"],
                    "rationale": out.rationale,
                    "proposed_body_md": out.proposed_body_md,
                    "applied": False,  # proposals are never auto-applied
                }
            )
        except Exception as e:  # noqa: BLE001 — a suggestion failure must not break the run
            suggestions.append(
                {
                    "slug": t["slug"],
                    "title": t["title"],
                    "rationale": f"(suggestion generation failed: {type(e).__name__})",
                    "proposed_body_md": "",
                    "applied": False,
                }
            )
    return {"suggestions": suggestions}


def _node_apply_gate(state: DocsAgentState) -> dict[str, Any]:
    """Human-in-the-loop gate. Pauses the run and surfaces the proposals; the
    resume value is the human's apply decision."""
    suggestions = state.get("suggestions", [])
    decision = interrupt(
        {
            "message": "Approve docs suggestions to apply? Resume with the slugs to apply, "
            "or 'reject' / [] to apply none.",
            "proposals": [
                {"slug": s["slug"], "title": s.get("title"), "rationale": s.get("rationale")}
                for s in suggestions
                if s.get("proposed_body_md")
            ],
        }
    )
    return {"approved_slugs": _normalize_decision(decision, suggestions)}


def _normalize_decision(decision: Any, suggestions: list[dict[str, Any]]) -> list[str]:
    """Coerce a resume value into a list of approved slugs.

    Accepts: a list of slugs, a comma-separated string, "all"/"approve"
    (every suggestion with a body), or "reject"/"none"/"" (nothing).
    """
    appliable = [s["slug"] for s in suggestions if s.get("proposed_body_md")]
    if decision is None:
        return []
    if isinstance(decision, list):
        return [s for s in decision if s in appliable]
    if isinstance(decision, dict):
        return _normalize_decision(decision.get("approved_slugs") or decision.get("slugs"), suggestions)
    if isinstance(decision, str):
        d = decision.strip().lower()
        if d in ("all", "approve", "approve_all", "yes"):
            return appliable
        if d in ("reject", "none", "no", ""):
            return []
        wanted = {p.strip() for p in decision.split(",") if p.strip()}
        return [s for s in appliable if s in wanted]
    return []


async def _node_apply_approved(state: DocsAgentState) -> dict[str, Any]:
    """Apply only the approved suggestions via the audited docs_upsert."""
    approved = set(state.get("approved_slugs", []))
    suggestions = state.get("suggestions", [])
    applied: list[dict[str, Any]] = []
    for s in suggestions:
        if s["slug"] not in approved or not s.get("proposed_body_md"):
            continue
        try:
            result = await dbmod.docs_upsert(
                slug=s["slug"],
                body_md=s["proposed_body_md"],
                status="up_to_date",
                owner="docs_agent",
                note=f"docs_agent suggestion applied (HIL-approved): {s.get('rationale','')[:120]}",
                source="docs_agent_apply",
            )
            s["applied"] = True
            applied.append({"slug": s["slug"], "version": result["doc"]["version"]})
        except Exception as e:  # noqa: BLE001 — one failed apply must not abort the rest
            applied.append({"slug": s["slug"], "error": f"{type(e).__name__}: {e}"})
    return {"applied": applied, "applied_any": bool(applied)}


# ---------------------------------------------------------------------------
# Graph assembly (compiled once, checkpointed)
# ---------------------------------------------------------------------------

_checkpointer = MemorySaver()
_graph = None


def build_docs_agent_graph() -> Any:
    # Node names are deliberately distinct from the state keys
    # (reconcile/triage/suggest) — LangGraph rejects a node whose name collides
    # with a channel/state key.
    builder = StateGraph(DocsAgentState)
    builder.add_node("do_reconcile", _node_reconcile)
    builder.add_node("do_triage", _node_triage)
    builder.add_node("do_suggest", _node_suggest)
    builder.add_node("apply_gate", _node_apply_gate)
    builder.add_node("apply_approved", _node_apply_approved)

    builder.add_edge(START, "do_reconcile")
    builder.add_edge("do_reconcile", "do_triage")
    builder.add_edge("do_triage", "do_suggest")
    builder.add_edge("do_suggest", "apply_gate")
    builder.add_edge("apply_gate", "apply_approved")
    builder.add_edge("apply_approved", END)

    return builder.compile(checkpointer=_checkpointer)


def _get_graph() -> Any:
    global _graph
    if _graph is None:
        _graph = build_docs_agent_graph()
    return _graph


def _public_payload(state: dict[str, Any], status: str, *, run_id: str, preview: Any = None) -> dict[str, Any]:
    """Shape the response. Keeps the historical DocsAgentResponse keys
    (reconcile / triage / suggestions / applied_any) and adds run/HIL fields."""
    return {
        "run_id": run_id,
        "status": status,  # "waiting_approval" | "completed"
        "reconcile": state.get("reconcile", {}),
        "triage": state.get("triage", []),
        "suggestions": state.get("suggestions", []),
        "applied": state.get("applied", []),
        "applied_any": bool(state.get("applied_any", False)),
        "approval_preview": preview,
    }


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


async def run_docs_agent_graph(
    *,
    limit_suggestions: int = 3,
    run_id: str | None = None,
    resume_decision: Any = None,
) -> dict[str, Any]:
    """Start a fresh docs-agent run (pauses at the apply gate) or resume an
    interrupted one with the human's apply decision."""
    import uuid

    graph = _get_graph()
    rid = run_id or f"docs-agent-{uuid.uuid4().hex[:12]}"
    config = {"configurable": {"thread_id": rid}}

    if resume_decision is not None and run_id:
        # Resume: feed the decision into the interrupted apply_gate.
        res = await graph.ainvoke(Command(resume=resume_decision), config)
    else:
        res = await graph.ainvoke(
            {"limit_suggestions": max(0, int(limit_suggestions))}, config
        )

    snapshot = await graph.aget_state(config)
    if snapshot.next:
        # Paused at the apply gate.
        preview = None
        if snapshot.tasks and snapshot.tasks[0].interrupts:
            preview = snapshot.tasks[0].interrupts[0].value
        return _public_payload(res, "waiting_approval", run_id=rid, preview=preview)

    return _public_payload(res, "completed", run_id=rid)


async def run_docs_agent(*, limit_suggestions: int = 3) -> dict[str, Any]:
    """Back-compat wrapper: run reconcile → triage → suggest and return the
    proposals WITHOUT applying (pauses at the apply gate). Matches the previous
    procedural shape (reconcile / triage / suggestions / applied_any=False) the
    web layer already consumes, plus a `run_id` callers can pass back to
    `run_docs_agent_graph(resume_decision=...)` to apply approved suggestions.
    """
    return await run_docs_agent_graph(limit_suggestions=limit_suggestions)

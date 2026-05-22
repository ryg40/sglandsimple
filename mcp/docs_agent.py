"""Stage 14 — Docs agent workflow: reconcile → triage → suggest.

Three phases, all read-only except the reconcile step (which respects the same
dry-run gates as docs_sync):

1. **Reconcile** — run the Confluence sync for public docs (docs_sync); the plan
   / actions are logged to doc_sync_log there.
2. **Triage** — flag stale / unreferenced docs as needs_attention / archivable,
   with a reason. Computed via docs.derive_status using full bodies so the
   "unreferenced" check (no other doc links to it) is accurate.
3. **Suggest** — for needs_attention docs, ask the LLM for a short improvement
   rationale and a *proposed* revised body. These are PROPOSALS ONLY — never
   auto-applied. Applying one is a separate, audited docs_upsert (the human-in-
   the-loop gate). The proposed body is returned for review, not written.

NOTE: The Stage-14 spec calls for this to run on the Stage-9 LangGraph +
checkpointer. This implementation is the procedural form of the same
reconcile→triage→suggest sequence; wiring it into a checkpointed LangGraph
StateGraph (so a run can be interrupted at the apply gate and resumed) is the
remaining piece of S14.agent.1 and is tracked in IMPLEMENT.md.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

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


async def run_docs_agent(*, limit_suggestions: int = 3) -> dict[str, Any]:
    # Phase 1 — reconcile (dry-run unless all sync gates are on).
    reconcile = await run_docs_sync()

    # Load full bodies once for triage + suggestion.
    listing = await dbmod.docs_list(include_archived=False)
    docs_full: list[dict[str, Any]] = []
    for d in listing:
        fd = await dbmod.docs_get(d["slug"])
        if fd:
            docs_full.append(fd)

    # Phase 2 — triage.
    triage = await _triage(docs_full)

    # Phase 3 — suggest (proposals only, capped).
    suggestions: list[dict[str, Any]] = []
    by_slug = {d["slug"]: d for d in docs_full}
    targets = [t for t in triage if t["suggested_status"] == "needs_attention"][: max(0, limit_suggestions)]
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

    return {
        "reconcile": reconcile,
        "triage": triage,
        "suggestions": suggestions,
        "applied_any": False,
    }

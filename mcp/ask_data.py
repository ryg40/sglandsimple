"""ask_data: a LangGraph workflow that turns a natural-language question
into a constrained-JSON Mongo query, executes it, and returns a cited
answer.

Flow:

    START
      └─ discover_schema   compact catalog of collections + sample fields
      └─ plan_query        structured(QuerySpec) call against the upstream
      └─ execute_query     validate_spec + db.find/db.aggregate
           ├─ on spec_error & retry_count < 1 → plan_query   (one retry)
           ├─ on spec_error & retry_count >= 1 → END         (fail closed)
           └─ on docs → fan_out_notes
      └─ fan_out_notes     Send(interpret_doc) per doc, capped by ASK_DATA_MAX_DOCS
      └─ interpret_doc     (parallel) one LLM call per doc → DocNote
      └─ synthesize        structured(FinalAnswer) producing cited answer
    END
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from langgraph.constants import Send
from langgraph.graph import END, START, StateGraph

from pydantic import BaseModel

import db as dbmod
from ask_data_models import AskDataState, DocNote, Evidence, FinalAnswer, QuerySpec
from llm import structured


class _SynthOut(BaseModel):
    """Synthesizer output schema. query_used is injected server-side from
    the actual spec, so the model doesn't have to emit it."""

    answer: str
    evidence: list[Evidence]

ASK_DATA_MAX_DOCS = int(os.environ.get("ASK_DATA_MAX_DOCS", "4"))
ASK_DATA_DEADLINE_SECONDS = float(os.environ.get("ASK_DATA_DEADLINE_SECONDS", "240"))
ASK_DATA_BATCH_NOTES = os.environ.get("ASK_DATA_BATCH_NOTES", "true").lower() in {"1", "true", "yes", "on"}
# Cap concurrent LLM calls so a parallel fan-out doesn't overrun the
# upstream's --max-num-seqs budget. Defaults to 2 to match a vLLM
# configured for a small machine.
LLM_CONCURRENCY = int(os.environ.get("LLM_CONCURRENCY", "2"))
_LLM_SEM = asyncio.Semaphore(LLM_CONCURRENCY)


class _BatchNotesOut(BaseModel):
    notes: list[DocNote]


# ---------------------------------------------------------------------------
# discover_schema (with module-level catalog cache)
# ---------------------------------------------------------------------------

_catalog_cache: tuple[float, str] | None = None
_CATALOG_TTL = 60.0


async def _build_catalog() -> str:
    cols = await dbmod.list_collections()
    blocks: list[str] = []
    for c in cols:
        desc = await dbmod.describe_collection(c["name"])
        field_lines = []
        for fname, info in desc["fields"].items():
            types = "|".join(info["types"])
            example = info["example"]
            ex_str = str(example)
            if len(ex_str) > 80:
                ex_str = ex_str[:80] + "…"
            field_lines.append(f"  - {fname} ({types}) e.g. {ex_str}")
        block = (
            f"## {c['name']} ({c['count']} docs)\n" + "\n".join(field_lines)
        )
        blocks.append(block)
    return "\n\n".join(blocks)


async def discover_schema(state: AskDataState) -> dict[str, Any]:
    global _catalog_cache
    now = time.time()
    if _catalog_cache and now - _catalog_cache[0] < _CATALOG_TTL:
        return {"catalog": _catalog_cache[1]}
    catalog = await _build_catalog()
    _catalog_cache = (now, catalog)
    return {"catalog": catalog}


# ---------------------------------------------------------------------------
# plan_query
# ---------------------------------------------------------------------------

PLAN_SYSTEM = """\
You are a careful Mongo query planner. Given a question and a collections
catalog, emit a single QuerySpec that, when executed, returns the documents
needed to answer the question.

Rules:
- Pick exactly one collection: employees, tickets, or documents.
- kind = "find" for direct lookups; "aggregate" for grouping/counting/joins.
- Never use $where, $function, $accumulator, $out, or $merge.
- For "aggregate", use a JSON pipeline of stages like [{"$match": {...}}, {"$group": {...}}].
  Each stage MUST be an object with exactly ONE key (e.g. {"$match":{}}), never [{}] or empty objects.
- limit: small (default 10-20, max 50).
- rationale: one short sentence explaining the plan.

Name matching:
- Names in the data are full names like "Alice Nguyen". When the user
  gives a first name only, use a case-insensitive regex prefix match:
  {"name": {"$regex": "^Alice", "$options": "i"}}.
- Same for tag/title searches: use $regex with options "i" rather than
  exact string equality.

If a previous attempt failed validation/execution or returned 0 rows,
the error is included. Produce a corrected spec — broaden the filter
(case-insensitive regex, $in, partial match) before changing collection.
"""


async def plan_query(state: AskDataState) -> dict[str, Any]:
    user_parts = [
        f"Catalog:\n{state.catalog}",
        f"Question: {state.question}",
    ]
    if state.spec_error:
        user_parts.append(f"Previous attempt failed: {state.spec_error}\nProduce a corrected spec.")
    user = "\n\n".join(user_parts)
    spec = await structured(QuerySpec, PLAN_SYSTEM, user)
    return {"spec": spec, "spec_error": None}


# ---------------------------------------------------------------------------
# execute_query
# ---------------------------------------------------------------------------


async def execute_query(state: AskDataState) -> dict[str, Any]:
    assert state.spec is not None
    spec_dict = state.spec.model_dump(exclude_none=True)
    try:
        if state.spec.kind == "find":
            rows = await dbmod.find(spec_dict)
        else:
            rows = await dbmod.aggregate(spec_dict)
    except (dbmod.SpecError, dbmod.ExecError) as e:
        return {
            "spec_error": str(e),
            "retry_count": state.retry_count + 1,
            "docs": [],
        }
    if not rows:
        # Empty result — give the planner a hint so a retry can broaden.
        return {
            "docs": [],
            "spec_error": (
                "query returned 0 rows; consider broader filters "
                "(case-insensitive regex, $in across enums, partial match)"
            ),
            "retry_count": state.retry_count + 1,
        }
    return {"docs": rows, "spec_error": None}


def route_after_exec(state: AskDataState) -> str:
    if state.spec_error:
        return "plan_query" if state.retry_count < 2 else "__end__"
    if not state.docs:
        return "synthesize"
    return "fan_out_notes"


# ---------------------------------------------------------------------------
# fan_out_notes -> interpret_doc (parallel) -> synthesize
# ---------------------------------------------------------------------------


def fan_out_notes(state: AskDataState) -> list[Send]:
    docs = state.docs[:ASK_DATA_MAX_DOCS]
    return [
        Send("interpret_doc", {"doc": d, "question": state.question})
        for d in docs
    ]


NOTE_SYSTEM = """\
You are a research analyst. Given a question and a single document, write
one short note (≤30 words) explaining how this document is or is not
relevant to the question. Do not invent facts beyond what the document says.
Respond with a JSON object {"doc_id": "...", "note": "..."}. doc_id must be
the document's _id field.
"""


async def interpret_doc(payload: dict[str, Any]) -> dict[str, Any]:
    doc = payload["doc"]
    question = payload["question"]
    user = f"Question: {question}\n\nDocument:\n{json.dumps(doc, default=str)}"
    async with _LLM_SEM:
        note = await structured(DocNote, NOTE_SYSTEM, user)
    # Ensure doc_id matches even if the model invented one.
    fixed = DocNote(doc_id=str(doc.get("_id", note.doc_id)), note=note.note)
    return {"per_doc_notes": [fixed]}


BATCH_NOTES_SYSTEM = """\
You are a research analyst. Given a question and a small list of database
rows, write one short note (≤30 words) for each row explaining how it is or
is not relevant. Do not invent facts beyond the rows. Respond as JSON:
{"notes":[{"doc_id":"...","note":"..."}]}. doc_id must match each row's _id.
"""


async def interpret_docs_batch(question: str, docs: list[dict[str, Any]]) -> list[DocNote]:
    """Summarize all selected docs in one LLM call.

    This replaces the previous one-call-per-document hot path for the normal
    manual runner. The graph nodes remain available, but the API path avoids
    multiplying slow upstream latency by ASK_DATA_MAX_DOCS.
    """
    compact = []
    for d in docs:
        compact.append({"_id": str(d.get("_id", "")), "row": d})
    user = f"Question: {question}\n\nRows:\n{json.dumps(compact, default=str)}"
    out = await structured(_BatchNotesOut, BATCH_NOTES_SYSTEM, user)
    by_id = {str(n.doc_id): n.note for n in out.notes}
    notes: list[DocNote] = []
    for d in docs:
        did = str(d.get("_id", ""))
        notes.append(DocNote(doc_id=did, note=by_id.get(did) or "Row returned by the database query."))
    return notes


# ---------------------------------------------------------------------------
# synthesize
# ---------------------------------------------------------------------------

SYNTH_SYSTEM = """\
You are a careful enterprise analyst. Given a question, the documents
returned by a database query, and per-document relevance notes, produce a
JSON object with:

- answer: a concise multi-sentence response. Every factual claim must end
  with a bracketed marker like [1] or [2,3] keyed to the evidence array.
- evidence: a list whose `index` matches those markers. Each entry has:
    - index (int)
    - doc_id (string): the _id field of the relevant document, or for
      aggregation rows the value of the _id group key
    - collection (string): one of employees, tickets, documents
    - quote (string): a short verbatim string drawn from one field of the
      relevant document or row (numbers may be stringified)
    - why (string): one short clause explaining the relevance

If the docs don't answer the question, say so plainly in `answer` with a
single Evidence entry summarizing what was checked.
"""


async def synthesize(state: AskDataState) -> dict[str, Any]:
    assert state.spec is not None
    user = (
        f"Question: {state.question}\n\n"
        f"Collection queried: {state.spec.collection}\n"
        f"Kind: {state.spec.kind}\n\n"
        f"Documents (rows):\n{json.dumps(state.docs, default=str, indent=2)}\n\n"
        f"Per-doc notes:\n"
        + "\n".join(f"- {n.doc_id}: {n.note}" for n in state.per_doc_notes)
    )
    partial = await structured(_SynthOut, SYNTH_SYSTEM, user)
    # Fill collection if the model omitted it, and inject the real query.
    fixed_evidence = []
    for e in partial.evidence:
        coll = e.collection or state.spec.collection
        fixed_evidence.append(e.model_copy(update={"collection": coll}))
    final = FinalAnswer(answer=partial.answer, evidence=fixed_evidence, query_used=state.spec)
    return {"final": final}


# ---------------------------------------------------------------------------
# Build / compile
# ---------------------------------------------------------------------------


def build_graph(checkpointer=None):
    g = StateGraph(AskDataState)
    g.add_node("discover_schema", discover_schema)
    g.add_node("plan_query", plan_query)
    g.add_node("execute_query", execute_query)
    g.add_node("fan_out_notes", lambda state: {})  # dummy node — Sends emitted via conditional edge
    g.add_node("interpret_doc", interpret_doc)
    g.add_node("synthesize", synthesize)

    g.add_edge(START, "discover_schema")
    g.add_edge("discover_schema", "plan_query")
    g.add_edge("plan_query", "execute_query")
    g.add_conditional_edges(
        "execute_query",
        route_after_exec,
        {
            "plan_query": "plan_query",
            "fan_out_notes": "fan_out_notes",
            "synthesize": "synthesize",
            END: END,
        },
    )
    g.add_conditional_edges("fan_out_notes", fan_out_notes, ["interpret_doc"])
    g.add_edge("interpret_doc", "synthesize")
    g.add_edge("synthesize", END)

    return g.compile(checkpointer=checkpointer)


def _remaining(deadline: float) -> float:
    return max(0.1, deadline - time.monotonic())


async def _with_budget(coro, deadline: float):
    return await asyncio.wait_for(coro, timeout=_remaining(deadline))


def _quote_from_doc(doc: dict[str, Any]) -> str:
    for key in ("title", "summary", "description", "name", "status", "priority"):
        val = doc.get(key)
        if val not in (None, ""):
            text = str(val)
            return text[:220] + ("…" if len(text) > 220 else "")
    text = json.dumps(doc, default=str, sort_keys=True)
    return text[:220] + ("…" if len(text) > 220 else "")


def _raw_fallback_final(state: AskDataState, reason: str) -> FinalAnswer | None:
    if state.spec is None or not state.docs:
        return None
    evidence: list[Evidence] = []
    for idx, doc in enumerate(state.docs[: min(len(state.docs), ASK_DATA_MAX_DOCS)], start=1):
        doc_id = str(doc.get("_id", doc.get("id", idx)))
        evidence.append(
            Evidence(
                index=idx,
                doc_id=doc_id,
                collection=state.spec.collection,
                quote=_quote_from_doc(doc),
                why="Raw row returned before LLM summarization completed.",
            )
        )
    answer = (
        f"Ask Data returned raw query results because {reason}. "
        f"The database query completed and returned {len(state.docs)} row(s); "
        "showing the available rows as evidence instead of an empty response."
    )
    return FinalAnswer(answer=answer, evidence=evidence, query_used=state.spec)


async def _run_ask_data_manual(question: str, deadline: float) -> AskDataState:
    """Run ask_data with explicit checkpoints between expensive LLM calls.

    The compiled graph is still available for development, but this runner is
    used by the MCP tool so timeout handling can return the latest completed
    state (especially executed rows) instead of losing everything when the
    outer request budget expires.
    """
    state = AskDataState(question=question)
    state = state.model_copy(update=await _with_budget(discover_schema(state), deadline))

    while True:
        state = state.model_copy(update=await _with_budget(plan_query(state), deadline))
        update = await _with_budget(execute_query(state), deadline)
        state = state.model_copy(update=update)
        if state.spec_error and state.retry_count < 2:
            continue
        break

    if state.spec_error:
        return state
    if not state.docs:
        return state

    docs = state.docs[:ASK_DATA_MAX_DOCS]
    try:
        if ASK_DATA_BATCH_NOTES:
            notes = await _with_budget(interpret_docs_batch(state.question, docs), deadline)
        else:
            note_updates = await _with_budget(
                asyncio.gather(*(interpret_doc({"doc": d, "question": state.question}) for d in docs)),
                deadline,
            )
            notes = [n for u in note_updates for n in u.get("per_doc_notes", [])]
        state = state.model_copy(update={"per_doc_notes": notes})
    except Exception:  # noqa: BLE001 - notes are helpful, not required
        state = state.model_copy(
            update={
                "per_doc_notes": [
                    DocNote(doc_id=str(d.get("_id", "")), note="Row returned by the database query.")
                    for d in docs
                ]
            }
        )

    try:
        state = state.model_copy(update=await _with_budget(synthesize(state), deadline))
    except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001
        state = state.model_copy(
            update={
                "final": _raw_fallback_final(state, "LLM summarization timed out or failed"),
                "spec_error": f"summarization fallback: {e}",
            }
        )
    return state


async def run_ask_data(question: str) -> AskDataState:
    """Run ask_data within a fixed wall-clock budget.

    Returns the final state object. If the expensive synthesis path times out
    after rows were fetched, `final` contains a raw-results fallback rather
    than leaving callers with a silent empty response.
    """
    deadline = time.monotonic() + ASK_DATA_DEADLINE_SECONDS
    try:
        return await asyncio.wait_for(_run_ask_data_manual(question, deadline), timeout=ASK_DATA_DEADLINE_SECONDS)
    except asyncio.TimeoutError:
        state = AskDataState(question=question)
        state.spec_error = f"ask_data exceeded {ASK_DATA_DEADLINE_SECONDS:.0f}s overall deadline before producing results"
        return state


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


def render_markdown(final: FinalAnswer | None, spec_error: str | None = None) -> str:
    if final is None:
        return f"# ask_data\n\n**Run failed.** {spec_error or 'no further detail'}\n"

    lines: list[str] = []
    lines.append("# Answer")
    lines.append("")
    lines.append(final.answer)
    lines.append("")
    lines.append("## Evidence")
    for e in final.evidence:
        lines.append(f"- **[{e.index}]** ({e.collection}/{e.doc_id})")
        lines.append(f"  > {e.quote}")
        lines.append(f"  {e.why}")
    lines.append("")
    lines.append("## Query used")
    lines.append("```json")
    lines.append(json.dumps(final.query_used.model_dump(exclude_none=True), indent=2, default=str))
    lines.append("```")
    return "\n".join(lines)

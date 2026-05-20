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

import json
import os
import time
import uuid
from typing import Any

from langgraph.constants import Send
from langgraph.graph import END, START, StateGraph

from ask_data_models import AskDataState, DocNote, Evidence, FinalAnswer, QuerySpec
from checkpointer import checkpointer_context
import db as dbmod
from llm import structured

ASK_DATA_MAX_DOCS = int(os.environ.get("ASK_DATA_MAX_DOCS", "10"))


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
- limit: small (default 10-20, max 50).
- rationale: one short sentence explaining the plan.

If a previous attempt failed validation/execution, the error is included.
Produce a corrected spec — change collection or operators as needed.
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
    return {"docs": rows, "spec_error": None}


def route_after_exec(state: AskDataState) -> str:
    if state.spec_error and state.retry_count < 2:
        return "plan_query"
    if not state.docs:
        return END
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
    note = await structured(DocNote, NOTE_SYSTEM, user)
    # Ensure doc_id matches even if the model invented one.
    fixed = DocNote(doc_id=str(doc.get("_id", note.doc_id)), note=note.note)
    return {"per_doc_notes": [fixed]}


# ---------------------------------------------------------------------------
# synthesize
# ---------------------------------------------------------------------------

SYNTH_SYSTEM = """\
You are a careful enterprise analyst. Given a question, the documents
returned by a database query, and per-document relevance notes, produce a
FinalAnswer that:

- answer: a concise multi-sentence response. Every factual claim must end
  with a bracketed marker like [1] or [2,3] keyed to the evidence array.
- evidence: a list whose `index` matches those markers. Each entry must
  reference a real document via doc_id (string _id from the docs) and
  contain a verbatim quote from a string field of that document, plus a
  short why.
- query_used: echo the QuerySpec you were given.

Do not invent doc_ids. Quotes must be verbatim from a string field. If the
docs don't answer the question, say so plainly.
"""


async def synthesize(state: AskDataState) -> dict[str, Any]:
    assert state.spec is not None
    user = (
        f"Question: {state.question}\n\n"
        f"QuerySpec used: {state.spec.model_dump_json()}\n\n"
        f"Documents:\n{json.dumps(state.docs, default=str, indent=2)}\n\n"
        f"Per-doc notes:\n"
        + "\n".join(f"- {n.doc_id}: {n.note}" for n in state.per_doc_notes)
    )
    final = await structured(FinalAnswer, SYNTH_SYSTEM, user)
    # Replace query_used with the actual spec we ran, regardless of what
    # the model produced (defense in depth against the model fabricating).
    final = final.model_copy(update={"query_used": state.spec})
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
        {"plan_query": "plan_query", "fan_out_notes": "fan_out_notes", END: END},
    )
    g.add_conditional_edges("fan_out_notes", fan_out_notes, ["interpret_doc"])
    g.add_edge("interpret_doc", "synthesize")
    g.add_edge("synthesize", END)

    return g.compile(checkpointer=checkpointer)


async def run_ask_data(question: str) -> AskDataState:
    """Run the graph end-to-end with a fresh thread id.

    Returns the final state object. If `final` is None, the run failed —
    `spec_error` carries the diagnostic.
    """
    with checkpointer_context() as saver:
        graph = build_graph(checkpointer=saver)
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        out = await graph.ainvoke({"question": question}, config=config)
    # `ainvoke` returns a dict-shaped state; coerce back to the model.
    return AskDataState.model_validate(out)


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

"""wrangler_suggest: ask the planner LLM for 2-3 useful, differently-shaped
aggregation pipelines to seed the builder.

Single structured() call on the planner role. The model is bounded to the
Stage-7 stage grammar; every suggestion is round-tripped through
`db.validate_spec()` server-side and dropped if it doesn't validate, so an
over-eager or malformed suggestion can never reach execution.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

import db as dbmod
import wrangler as wranglermod
from llm import structured


class SuggestedPipeline(BaseModel):
    name: str
    rationale: str = ""
    stages: list[dict[str, Any]] = Field(default_factory=list)


class SuggestOut(BaseModel):
    pipelines: list[SuggestedPipeline] = Field(default_factory=list)


SUGGEST_SYSTEM = """\
You design Mongo aggregation pipelines for a data-exploration UI. Given a
collection name and a compact field summary, propose 2-3 USEFUL and
DIFFERENTLY-SHAPED pipelines. Prefer this mix:
  1. a count-by-group (e.g. {"$group":{"_id":"$field","count":{"$sum":1}}}),
  2. a trend or breakdown over a second dimension,
  3. a rank / top-N (group + sort + limit).

Rules:
- Each pipeline is a JSON array of stages. Each stage is an object with
  EXACTLY ONE top-level key (e.g. {"$match":{...}}, {"$group":{...}},
  {"$sort":{...}}, {"$limit":N}, {"$project":{...}}).
- NEVER use $where, $function, $accumulator, $out, or $merge.
- Keep pipelines short (2-4 stages) and end ranked pipelines with a small $limit.
- Use only fields that appear in the provided summary.
- Give each pipeline a short human name and a one-sentence rationale.
"""


def _summary_text(field_summary: list[dict[str, Any]]) -> str:
    lines = []
    for f in field_summary:
        types = "|".join(f.get("types", []))
        card = f.get("cardinality")
        ex = ", ".join(str(x) for x in f.get("examples", [])[:3])
        lines.append(f"- {f['field']} ({types}) cardinality={card} e.g. {ex}")
    return "\n".join(lines)


async def run_wrangler_suggest(collection: str) -> dict[str, Any]:
    if collection not in dbmod.KNOWN_COLLECTIONS:
        return {"collection": collection, "pipelines": [], "error": f"unknown collection: {collection!r}"}

    sample = await wranglermod.sample(collection)
    user = (
        f"Collection: {collection}\n\n"
        f"Field summary (from a {sample['row_count']}-row sample):\n"
        f"{_summary_text(sample['field_summary'])}"
    )

    try:
        out = await structured(SuggestOut, SUGGEST_SYSTEM, user, role="planner")
    except Exception as e:  # noqa: BLE001
        return {"collection": collection, "pipelines": [], "error": f"planner error: {e}"}

    valid: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for p in out.pipelines:
        if not p.stages:
            dropped.append({"name": p.name, "reason": "empty pipeline"})
            continue
        try:
            dbmod.validate_spec(
                {"collection": collection, "kind": "aggregate", "pipeline": p.stages}
            )
        except dbmod.SpecError as e:
            dropped.append({"name": p.name, "reason": str(e)})
            continue
        valid.append({"name": p.name, "rationale": p.rationale, "stages": p.stages})

    return {"collection": collection, "pipelines": valid, "dropped": dropped}

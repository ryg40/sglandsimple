"""Server-side logic for the Stage-7 reactive aggregation builder.

Three responsibilities, all read-only against the enterprise data except
for the pipeline-persistence collection:

1. `sample()` — a light recent-doc sample + a per-field summary
   (types, cardinality, examples) the UI turns into clickable chips.
2. `run_prefix()` — execute a *prefix* of a pipeline so each stage can be
   run on its own (the Data-Wrangler experience). Goes through the same
   `db.aggregate()` / `validate_spec()` everything else uses.
3. `save_pipeline()` / `list_pipelines()` — persist builder state to
   `db.wrangler_pipelines`; each save writes a single audit_log row.

The aggregation execution path adds NO new validation surface: it reuses
`db.validate_spec` (which forbids $where/$function/$accumulator/$out/$merge
and requires single-key stages) and the hard LIMIT_CEILING.
"""

from __future__ import annotations

import datetime as _dt
import os
import uuid
from typing import Any

import db as dbmod

WRANGLER_PREVIEW_LIMIT = int(os.environ.get("WRANGLER_PREVIEW_LIMIT", "25"))
WRANGLER_MAX_STAGES = int(os.environ.get("WRANGLER_MAX_STAGES", "12"))
WRANGLER_SAMPLE_LIMIT = int(os.environ.get("WRANGLER_SAMPLE_LIMIT", "50"))

PIPELINES_COLLECTION = "wrangler_pipelines"


# ---------------------------------------------------------------------------
# 1. sample + field summary
# ---------------------------------------------------------------------------


def _field_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-field types, cardinality, and a few example values across the sample."""
    acc: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in rows:
        for k, v in row.items():
            if k not in acc:
                acc[k] = {"types": [], "values": [], "distinct": set(), "present": 0}
                order.append(k)
            entry = acc[k]
            entry["present"] += 1
            t = dbmod._summarize_type(v)
            if t not in entry["types"]:
                entry["types"].append(t)
            # Track distinct for cardinality (hashable scalars only).
            if isinstance(v, (str, int, float, bool)) or v is None:
                entry["distinct"].add(v)
            if len(entry["values"]) < 5 and v is not None:
                ex = dbmod._truncate_example(v)
                if ex not in entry["values"]:
                    entry["values"].append(ex)

    out: list[dict[str, Any]] = []
    n = max(1, len(rows))
    for k in order:
        e = acc[k]
        out.append(
            {
                "field": k,
                "types": e["types"],
                "cardinality": len(e["distinct"]) if e["distinct"] else None,
                "coverage": round(e["present"] / n, 2),
                "examples": [
                    x if isinstance(x, (str, int, float, bool, list, dict)) else str(x)
                    for x in e["values"]
                ],
            }
        )
    return out


async def sample(collection: str, *, limit: int | None = None) -> dict[str, Any]:
    lim = int(limit) if limit else WRANGLER_SAMPLE_LIMIT
    s = await dbmod.sample_recent(collection, limit=lim)
    return {
        "collection": s["collection"],
        "sort_field": s["sort_field"],
        "sort_dir": s["sort_dir"],
        "row_count": len(s["rows"]),
        "rows": s["rows"],
        "field_summary": _field_summary(s["rows"]),
    }


# ---------------------------------------------------------------------------
# 2. run a prefix of a pipeline
# ---------------------------------------------------------------------------


async def run_prefix(
    collection: str, pipeline: list[dict[str, Any]], upto: int
) -> dict[str, Any]:
    """Execute pipeline[:upto+1] and return its preview + row-count delta.

    `input_count` is the output count of pipeline[:upto] (the data flowing
    *into* the final stage); `output_count` is after pipeline[:upto+1].
    Both are computed under the same preview cap so the deltas are
    apples-to-apples for the UI.
    """
    if not isinstance(pipeline, list):
        raise dbmod.SpecError("pipeline must be an array")
    if len(pipeline) > WRANGLER_MAX_STAGES:
        raise dbmod.SpecError(
            f"pipeline has {len(pipeline)} stages > WRANGLER_MAX_STAGES={WRANGLER_MAX_STAGES}"
        )
    if not pipeline:
        raise dbmod.SpecError("pipeline is empty")
    upto = int(upto)
    if upto < 0 or upto >= len(pipeline):
        raise dbmod.SpecError(f"upto={upto} out of range for {len(pipeline)} stages")

    async def _count(prefix: list[dict[str, Any]]) -> int:
        if not prefix:
            # No stages yet: count of the bare collection (capped).
            rows = await dbmod.aggregate(
                {"collection": collection, "kind": "aggregate", "pipeline": [{"$limit": WRANGLER_PREVIEW_LIMIT}]}
            )
            return len(rows)
        rows = await dbmod.aggregate(
            {"collection": collection, "kind": "aggregate", "pipeline": prefix}
        )
        return len(rows)

    target = pipeline[: upto + 1]
    has_limit = any("$limit" in s for s in target)
    preview_pipeline = list(target)
    if not has_limit:
        preview_pipeline = preview_pipeline + [{"$limit": WRANGLER_PREVIEW_LIMIT}]

    rows = await dbmod.aggregate(
        {"collection": collection, "kind": "aggregate", "pipeline": preview_pipeline}
    )
    # input_count: rows flowing into this stage (prefix one shorter), capped.
    input_prefix = pipeline[:upto]
    if input_prefix and not any("$limit" in s for s in input_prefix):
        input_prefix = input_prefix + [{"$limit": WRANGLER_PREVIEW_LIMIT}]
    input_count = await _count(input_prefix)

    return {
        "collection": collection,
        "stage_index": upto,
        "input_count": input_count,
        "output_count": len(rows),
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# 3. persistence
# ---------------------------------------------------------------------------


async def save_pipeline(
    name: str,
    collection: str,
    stages: list[dict[str, Any]],
    pipeline_id: str | None = None,
) -> dict[str, Any]:
    if collection not in dbmod.KNOWN_COLLECTIONS:
        raise dbmod.SpecError(f"unknown collection: {collection!r}")
    if not isinstance(stages, list):
        raise dbmod.SpecError("stages must be an array")
    if len(stages) > WRANGLER_MAX_STAGES:
        raise dbmod.SpecError(
            f"pipeline has {len(stages)} stages > WRANGLER_MAX_STAGES={WRANGLER_MAX_STAGES}"
        )

    db = dbmod.get_db()
    now = _dt.datetime.utcnow()
    pid = pipeline_id or f"wp-{uuid.uuid4().hex[:12]}"
    existing = await db[PIPELINES_COLLECTION].find_one({"_id": pid})
    doc = {
        "_id": pid,
        "name": name,
        "collection": collection,
        "stages": stages,
        "created_at": existing["created_at"] if existing else now,
        "updated_at": now,
    }
    await db[PIPELINES_COLLECTION].replace_one({"_id": pid}, doc, upsert=True)
    await dbmod._audit(
        "replaceOne" if existing else "insertOne",
        PIPELINES_COLLECTION,
        pid,
        existing,
        {"name": name, "collection": collection, "stages": stages},
        "wrangler_save",
    )
    return {"_id": pid, "name": name, "collection": collection, "saved": True}


async def list_pipelines(collection: str | None = None) -> dict[str, Any]:
    db = dbmod.get_db()
    q: dict[str, Any] = {}
    if collection:
        q["collection"] = collection
    cursor = db[PIPELINES_COLLECTION].find(q).sort([("updated_at", -1)]).limit(100)
    rows = [d async for d in cursor]
    return {"pipelines": [dbmod._stringify_ids(r) for r in rows]}

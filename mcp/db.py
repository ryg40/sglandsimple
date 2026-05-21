"""Read-only Mongo access layer used by the LangGraph ask_data workflow
and by the direct mongo_query / mongo_aggregate MCP tools.

Two responsibilities:

1. Schema discovery the planner LLM can prompt against
   (`list_collections`, `describe_collection`).
2. A validated, hard-capped, read-only executor (`find`, `aggregate`)
   gated by `validate_spec`. The model is allowed to emit any spec; we
   reject anything that could mutate data or execute server-side
   JavaScript before it reaches the driver.

Mongo role-level enforcement is intentionally NOT relied on — the `app`
user has readWrite so the LangGraph checkpointer can persist runs.
Read-only behavior is an API-layer guarantee.
"""

from __future__ import annotations

import datetime as _dt
import os
import time
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://mongo:27017")
MONGO_DB = os.environ.get("MONGO_DB", "enterprise")
LIMIT_CEILING = int(os.environ.get("ASK_DATA_LIMIT_CEILING", "50"))

KNOWN_COLLECTIONS = (
    "employees",
    "tickets",
    "documents",
    "audit_findings",
    "epics",
    "work_items",
    "pr_records",
    "doc_records",
    "log_samples",
    "workflow_runs",
)

# Stage 9 — workflow collections
WORKFLOW_COLLECTIONS = (
    "audit_findings",
    "epics",
    "work_items",
    "pr_records",
    "doc_records",
    "log_samples",
    "workflow_runs",
)

# Stage 6 — write surface.
SHEET_WRITES_ENABLED = os.environ.get("SHEET_WRITES_ENABLED", "true").lower() == "true"
SHEET_AUDIT_COLLECTION = os.environ.get("SHEET_AUDIT_COLLECTION", "audit_log")

# Stage 9 — workflow write flag (defaults to dry-run / false)
WORKFLOW_WRITES_ENABLED = os.environ.get("WORKFLOW_WRITES_ENABLED", "false").lower() == "true"

# Update operators the sheet write-layer allows. Anything outside this set
# is rejected before the driver sees it.
_ALLOWED_UPDATE_OPERATORS = {"$set", "$unset", "$inc", "$push", "$pull", "$addToSet"}

_FORBIDDEN_OPERATORS = {
    "$where",
    "$function",
    "$accumulator",
    "$out",
    "$merge",
}


class SpecError(ValueError):
    """Raised when a planner-emitted spec fails validation."""


class ExecError(RuntimeError):
    """Raised when the driver layer fails to execute a validated spec."""


_client: AsyncIOMotorClient | None = None


def get_db():
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(MONGO_URL)
    return _client[MONGO_DB]


# ---------------------------------------------------------------------------
# Schema discovery
# ---------------------------------------------------------------------------


_describe_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_list_cache: tuple[float, list[dict[str, Any]]] | None = None
_CACHE_TTL = 60.0


async def list_collections() -> list[dict[str, Any]]:
    global _list_cache
    now = time.time()
    if _list_cache and now - _list_cache[0] < _CACHE_TTL:
        return _list_cache[1]

    db = get_db()
    names = await db.list_collection_names()
    visible = [n for n in names if n in KNOWN_COLLECTIONS or n in WORKFLOW_COLLECTIONS]
    out: list[dict[str, Any]] = []
    for name in visible:
        count = await db[name].estimated_document_count()
        out.append({"name": name, "count": int(count)})
    _list_cache = (now, out)
    return out


def _summarize_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    # ObjectId, datetime, etc.
    return type(value).__name__


def _truncate_example(value: Any, max_len: int = 80) -> Any:
    if isinstance(value, str):
        return value if len(value) <= max_len else value[:max_len] + "…"
    if isinstance(value, list):
        return value[:3]
    return value


async def describe_collection(name: str, sample: int = 5) -> dict[str, Any]:
    if name not in KNOWN_COLLECTIONS and name not in WORKFLOW_COLLECTIONS:
        raise SpecError(f"unknown collection: {name}")

    now = time.time()
    cached = _describe_cache.get(name)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    db = get_db()
    cursor = db[name].aggregate([{"$sample": {"size": sample}}])
    docs = [d async for d in cursor]
    fields: dict[str, dict[str, Any]] = {}
    for d in docs:
        for k, v in d.items():
            entry = fields.setdefault(k, {"types": [], "example": None})
            t = _summarize_type(v)
            if t not in entry["types"]:
                entry["types"].append(t)
            if entry["example"] is None and v is not None:
                entry["example"] = _truncate_example(v)
    # Stringify ObjectIds in examples for JSON-safety.
    for f in fields.values():
        if f["example"] is not None and not isinstance(
            f["example"], (str, int, float, bool, list, dict)
        ):
            f["example"] = str(f["example"])

    payload = {"collection": name, "sample_size": len(docs), "fields": fields}
    _describe_cache[name] = (now, payload)
    return payload


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _walk_forbidden(node: Any, path: str = "") -> None:
    """Recursively scan a value for forbidden operators."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _FORBIDDEN_OPERATORS:
                raise SpecError(f"forbidden operator {k!r} at {path}/{k}")
            if k == "$expr":
                # $expr is allowed, but only if it doesn't contain $function.
                _walk_forbidden(v, f"{path}/{k}")
            else:
                _walk_forbidden(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _walk_forbidden(item, f"{path}[{i}]")


def validate_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Validate a planner-emitted spec and return a normalized version.

    Spec shape:
        {collection, kind: "find"|"aggregate",
         filter?, projection?, sort?, limit?, skip?,
         pipeline?, rationale?}
    """
    if not isinstance(spec, dict):
        raise SpecError("spec must be an object")

    collection = spec.get("collection")
    if collection not in KNOWN_COLLECTIONS and collection not in WORKFLOW_COLLECTIONS:
        raise SpecError(f"unknown collection: {collection!r}")

    kind = spec.get("kind")
    if kind not in ("find", "aggregate"):
        raise SpecError(f"unknown kind: {kind!r}")

    allowed_keys_find = {"collection", "kind", "filter", "projection", "sort", "limit", "skip", "rationale"}
    allowed_keys_agg = {"collection", "kind", "pipeline", "limit", "rationale"}
    allowed = allowed_keys_find if kind == "find" else allowed_keys_agg
    extra = set(spec.keys()) - allowed
    if extra:
        raise SpecError(f"unknown spec keys for kind={kind}: {sorted(extra)}")

    out: dict[str, Any] = {"collection": collection, "kind": kind}

    if kind == "find":
        filt = spec.get("filter") or {}
        if not isinstance(filt, dict):
            raise SpecError("filter must be an object")
        _walk_forbidden(filt, "/filter")
        out["filter"] = filt

        if (proj := spec.get("projection")) is not None:
            if not isinstance(proj, dict):
                raise SpecError("projection must be an object")
            out["projection"] = proj

        if (sort := spec.get("sort")) is not None:
            if not isinstance(sort, dict):
                raise SpecError("sort must be an object")
            out["sort"] = sort

        limit = int(spec.get("limit") or LIMIT_CEILING)
        out["limit"] = max(1, min(limit, LIMIT_CEILING))

        if (skip := spec.get("skip")) is not None:
            out["skip"] = max(0, int(skip))

    else:  # aggregate
        pipeline = spec.get("pipeline")
        if not isinstance(pipeline, list) or not pipeline:
            raise SpecError("pipeline must be a non-empty array")
        for i, stage in enumerate(pipeline):
            if not isinstance(stage, dict):
                raise SpecError(f"pipeline[{i}] must be an object")
            if len(stage) != 1:
                raise SpecError(f"pipeline[{i}] must contain exactly one field; got {len(stage)}")
            for stage_key in stage.keys():
                if stage_key in _FORBIDDEN_OPERATORS:
                    raise SpecError(f"forbidden stage {stage_key!r} at pipeline[{i}]")
            _walk_forbidden(stage, f"/pipeline[{i}]")
        out["pipeline"] = pipeline

        limit = int(spec.get("limit") or LIMIT_CEILING)
        out["limit"] = max(1, min(limit, LIMIT_CEILING))

    return out


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------


def _stringify_ids(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _stringify_ids(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_stringify_ids(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    # ObjectId, datetime, Decimal128, etc. — fall back to str() for JSON-safety.
    return str(value)


async def find(spec: dict[str, Any]) -> list[dict[str, Any]]:
    spec = validate_spec(spec)
    db = get_db()
    coll = db[spec["collection"]]
    try:
        cursor = coll.find(spec.get("filter") or {}, spec.get("projection"))
        if "sort" in spec:
            cursor = cursor.sort(list(spec["sort"].items()))
        if "skip" in spec:
            cursor = cursor.skip(spec["skip"])
        cursor = cursor.limit(spec["limit"])
        rows = [d async for d in cursor]
    except Exception as e:  # noqa: BLE001
        raise ExecError(f"find failed: {e}") from e
    return [_stringify_ids(r) for r in rows]


async def aggregate(spec: dict[str, Any]) -> list[dict[str, Any]]:
    spec = validate_spec(spec)
    db = get_db()
    coll = db[spec["collection"]]
    pipeline = list(spec["pipeline"])
    # Append a $limit if none present.
    has_limit = any("$limit" in s for s in pipeline)
    if not has_limit:
        pipeline.append({"$limit": spec["limit"]})
    try:
        cursor = coll.aggregate(pipeline)
        rows = [d async for d in cursor]
    except Exception as e:  # noqa: BLE001
        raise ExecError(f"aggregate failed: {e}") from e
    return [_stringify_ids(r) for r in rows]


# ---------------------------------------------------------------------------
# Stage 6 — write layer + audit log
#
# Strict, narrow surface: insertOne / updateOne / deleteOne by _id only.
# No bulk ops, no pipelines, no multi-document filters. validate_write_spec
# is intentionally separate from validate_spec so the read-only invariant
# stays untouched.
# ---------------------------------------------------------------------------


def _require_writes_enabled() -> None:
    if not SHEET_WRITES_ENABLED:
        raise SpecError("writes disabled (SHEET_WRITES_ENABLED=false)")


def _require_known_collection(name: Any) -> str:
    if name not in KNOWN_COLLECTIONS and name not in WORKFLOW_COLLECTIONS:
        raise SpecError(f"unknown collection: {name!r}")
    return name


def _require_id(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise SpecError("_id must be a non-empty string")
    return value


def validate_write_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Validate a sheet-style write spec.

    Shape:
        {action: "insertOne"|"updateOne"|"deleteOne"|"replaceOne",
         collection: str,
         _id?: str, doc?: dict, update?: dict}
    """
    if not isinstance(spec, dict):
        raise SpecError("write spec must be an object")
    action = spec.get("action")
    if action not in ("insertOne", "updateOne", "deleteOne", "replaceOne"):
        raise SpecError(f"unknown write action: {action!r}")
    coll = _require_known_collection(spec.get("collection"))

    out: dict[str, Any] = {"action": action, "collection": coll}

    if action == "insertOne":
        doc = spec.get("doc")
        if not isinstance(doc, dict):
            raise SpecError("insertOne requires a `doc` object")
        if "_id" in doc:
            _require_id(doc["_id"])
        _walk_forbidden(doc, "/doc")
        out["doc"] = doc
        return out

    out["_id"] = _require_id(spec.get("_id"))

    if action == "deleteOne":
        return out

    if action == "replaceOne":
        doc = spec.get("doc")
        if not isinstance(doc, dict):
            raise SpecError("replaceOne requires a `doc` object")
        _walk_forbidden(doc, "/doc")
        out["doc"] = doc
        return out

    # updateOne
    update = spec.get("update")
    if not isinstance(update, dict) or not update:
        raise SpecError("updateOne requires an `update` object")
    extra = set(update.keys()) - _ALLOWED_UPDATE_OPERATORS
    if extra:
        raise SpecError(f"unknown update operators: {sorted(extra)}")
    _walk_forbidden(update, "/update")
    out["update"] = update
    return out


async def _audit(action: str, collection: str, _id: str | None, before: Any, after: Any, source: str) -> None:
    db = get_db()
    try:
        # Note: the audit-log doc must NOT use the row's _id as its own _id.
        # Store the row id under `doc_id` and let Mongo auto-assign _id.
        await db[SHEET_AUDIT_COLLECTION].insert_one(
            {
                "action": action,
                "collection": collection,
                "doc_id": _id,
                "before": before,
                "after": after,
                "ts": _dt.datetime.utcnow(),
                "source": source,
            }
        )
    except Exception as e:  # noqa: BLE001 — audit is best-effort, never fail the write
        print(f"[db] audit write failed: {e}", flush=True)


async def insert_one(collection: str, doc: dict[str, Any], *, source: str = "mcp_direct") -> dict[str, Any]:
    _require_writes_enabled()
    spec = validate_write_spec({"action": "insertOne", "collection": collection, "doc": doc})
    db = get_db()
    coll = db[spec["collection"]]
    try:
        result = await coll.insert_one(spec["doc"])
    except Exception as e:  # noqa: BLE001
        raise ExecError(f"insert_one failed: {e}") from e
    inserted_id = result.inserted_id
    after = await coll.find_one({"_id": inserted_id})
    after = _stringify_ids(after) if after is not None else None
    _id_str = str(inserted_id)
    await _audit("insertOne", spec["collection"], _id_str, None, after, source)
    return {"_id": _id_str, "after": after}


async def update_one(
    collection: str, _id: str, update: dict[str, Any], *, source: str = "mcp_direct"
) -> dict[str, Any]:
    _require_writes_enabled()
    spec = validate_write_spec(
        {"action": "updateOne", "collection": collection, "_id": _id, "update": update}
    )
    db = get_db()
    coll = db[spec["collection"]]
    before = await coll.find_one({"_id": spec["_id"]})
    if before is None:
        raise SpecError(f"no document with _id={spec['_id']!r}")
    try:
        result = await coll.update_one({"_id": spec["_id"]}, spec["update"])
    except Exception as e:  # noqa: BLE001
        raise ExecError(f"update_one failed: {e}") from e
    after = await coll.find_one({"_id": spec["_id"]})
    before_s = _stringify_ids(before)
    after_s = _stringify_ids(after) if after is not None else None
    await _audit("updateOne", spec["collection"], str(spec["_id"]), before_s, after_s, source)
    return {
        "_id": str(spec["_id"]),
        "matched": result.matched_count,
        "modified": result.modified_count,
        "before": before_s,
        "after": after_s,
    }


async def delete_one(collection: str, _id: str, *, source: str = "mcp_direct") -> dict[str, Any]:
    _require_writes_enabled()
    spec = validate_write_spec({"action": "deleteOne", "collection": collection, "_id": _id})
    db = get_db()
    coll = db[spec["collection"]]
    before = await coll.find_one({"_id": spec["_id"]})
    if before is None:
        raise SpecError(f"no document with _id={spec['_id']!r}")
    try:
        result = await coll.delete_one({"_id": spec["_id"]})
    except Exception as e:  # noqa: BLE001
        raise ExecError(f"delete_one failed: {e}") from e
    before_s = _stringify_ids(before)
    await _audit("deleteOne", spec["collection"], str(spec["_id"]), before_s, None, source)
    return {"_id": str(spec["_id"]), "deleted": result.deleted_count, "before": before_s}


# ---------------------------------------------------------------------------
# Stage 6 — paginated reads for the spreadsheet UI
# ---------------------------------------------------------------------------


async def get_rows(
    collection: str, *, skip: int = 0, limit: int = 50, sort: dict[str, int] | None = None
) -> dict[str, Any]:
    """Paginated find() used by the spreadsheet grid. Returns rows + total count."""
    coll_name = _require_known_collection(collection)
    db = get_db()
    coll = db[coll_name]
    skip = max(0, int(skip))
    limit = max(1, min(int(limit), LIMIT_CEILING))
    try:
        total = await coll.estimated_document_count()
        cursor = coll.find({})
        if sort:
            cursor = cursor.sort(list(sort.items()))
        cursor = cursor.skip(skip).limit(limit)
        rows = [d async for d in cursor]
    except Exception as e:  # noqa: BLE001
        raise ExecError(f"get_rows failed: {e}") from e
    return {
        "collection": coll_name,
        "skip": skip,
        "limit": limit,
        "total": int(total),
        "rows": [_stringify_ids(r) for r in rows],
    }


# ---------------------------------------------------------------------------
# Stage 7 — light recent-doc sample for the aggregation builder
# ---------------------------------------------------------------------------

# Order matters: the first field that actually exists on a sampled doc wins.
_RECENCY_FIELDS = ("updated_at", "ts", "created_at", "hire_date", "_id")


async def sample_recent(
    collection: str, *, limit: int = 50, sort_by: str | None = None
) -> dict[str, Any]:
    """A light, recency-ordered sample for the wrangler UI.

    Picks the first recency field that exists on the collection (unless
    `sort_by` is given), sorts descending, and caps at LIMIT_CEILING.
    Returns {collection, rows, sort_field, sort_dir}.
    """
    coll_name = _require_known_collection(collection)
    db = get_db()
    coll = db[coll_name]
    limit = max(1, min(int(limit), LIMIT_CEILING))

    sort_field = sort_by
    if not sort_field:
        # Probe one doc to see which recency field is present.
        probe = await coll.find_one({})
        if probe:
            for f in _RECENCY_FIELDS:
                if f in probe:
                    sort_field = f
                    break
        sort_field = sort_field or "_id"

    try:
        cursor = coll.find({}).sort([(sort_field, -1)]).limit(limit)
        rows = [d async for d in cursor]
    except Exception as e:  # noqa: BLE001
        raise ExecError(f"sample_recent failed: {e}") from e

    return {
        "collection": coll_name,
        "sort_field": sort_field,
        "sort_dir": -1,
        "rows": [_stringify_ids(r) for r in rows],
    }


# ---------------------------------------------------------------------------
# Stage 8 — recent audit feed for the admin Overview dashboard
# ---------------------------------------------------------------------------


async def audit_recent(limit: int = 25) -> dict[str, Any]:
    """Latest audit-log entries (newest first) for the Overview activity table.

    Read-only against the audit collection. `audit_log` is intentionally
    NOT in KNOWN_COLLECTIONS (so the generic mongo_query allowlist can't
    touch it); this dedicated reader is the only path the UI uses.
    """
    db = get_db()
    limit = max(1, min(int(limit), 200))
    try:
        cursor = db[SHEET_AUDIT_COLLECTION].find({}).sort([("ts", -1)]).limit(limit)
        rows = [d async for d in cursor]
    except Exception as e:  # noqa: BLE001
        raise ExecError(f"audit_recent failed: {e}") from e
    return {"collection": SHEET_AUDIT_COLLECTION, "rows": [_stringify_ids(r) for r in rows]}


# ---------------------------------------------------------------------------
# Stage 9 — workflow collections helpers
# ---------------------------------------------------------------------------


def _require_workflow_collection(name: Any) -> str:
    if name not in WORKFLOW_COLLECTIONS:
        raise SpecError(f"unknown workflow collection: {name!r}")
    return name


async def find_workflow(collection: str, _id: str) -> dict[str, Any] | None:
    """Read a single workflow document by its string _id."""
    coll_name = _require_workflow_collection(collection)
    db = get_db()
    doc = await db[coll_name].find_one({"_id": _id})
    return _stringify_ids(doc) if doc else None


async def insert_workflow(collection: str, doc: dict[str, Any], *, source: str = "workflow_direct") -> dict[str, Any]:
    """Insert a document into a workflow collection with audit logging."""
    if not WORKFLOW_WRITES_ENABLED:
        raise SpecError("workflow writes disabled (WORKFLOW_WRITES_ENABLED=false)")
    coll_name = _require_workflow_collection(collection)
    if not isinstance(doc, dict):
        raise SpecError("doc must be a dict")
    if "_id" not in doc:
        doc["_id"] = str(ObjectId())
    db = get_db()
    try:
        result = await db[coll_name].insert_one(doc)
    except Exception as e:  # noqa: BLE001
        raise ExecError(f"insert_workflow failed: {e}") from e
    inserted_id = result.inserted_id
    after = await db[coll_name].find_one({"_id": inserted_id})
    after_s = _stringify_ids(after) if after is not None else None
    await _audit("insertOne", coll_name, str(inserted_id), None, after_s, source)
    return {"_id": str(inserted_id), "after": after_s}


async def update_workflow(
    collection: str, _id: str, update: dict[str, Any], *, source: str = "workflow_direct"
) -> dict[str, Any]:
    """Update a workflow document by its string _id with audit logging."""
    if not WORKFLOW_WRITES_ENABLED:
        raise SpecError("workflow writes disabled (WORKFLOW_WRITES_ENABLED=false)")
    coll_name = _require_workflow_collection(collection)
    extra = set(update.keys()) - _ALLOWED_UPDATE_OPERATORS
    if extra:
        raise SpecError(f"unknown update operators: {sorted(extra)}")
    _walk_forbidden(update, "/update")
    db = get_db()
    before = await db[coll_name].find_one({"_id": _id})
    if before is None:
        raise SpecError(f"no document with _id={_id!r}")
    try:
        result = await db[coll_name].update_one({"_id": _id}, update)
    except Exception as e:  # noqa: BLE001
        raise ExecError(f"update_workflow failed: {e}") from e
    after = await db[coll_name].find_one({"_id": _id})
    before_s = _stringify_ids(before)
    after_s = _stringify_ids(after) if after is not None else None
    await _audit("updateOne", coll_name, _id, before_s, after_s, source)
    return {
        "_id": _id,
        "matched": result.matched_count,
        "modified": result.modified_count,
        "before": before_s,
        "after": after_s,
    }


async def find_workflow_run(run_id: str) -> dict[str, Any] | None:
    """Read a workflow run document by its string _id."""
    return await find_workflow("workflow_runs", run_id)


async def upsert_workflow_run(run_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    """Replace-or-insert a workflow run document with audit logging."""
    if not WORKFLOW_WRITES_ENABLED:
        raise SpecError("workflow writes disabled (WORKFLOW_WRITES_ENABLED=false)")
    db = get_db()
    before = await db["workflow_runs"].find_one({"_id": run_id})
    try:
        result = await db["workflow_runs"].replace_one(
            {"_id": run_id}, doc, upsert=True
        )
    except Exception as e:  # noqa: BLE001
        raise ExecError(f"upsert_workflow_run failed: {e}") from e
    after = await db["workflow_runs"].find_one({"_id": run_id})
    before_s = _stringify_ids(before) if before else None
    after_s = _stringify_ids(after) if after else None
    source = doc.get("source", "workflow_run")
    await _audit("replaceOne" if before else "insertOne", "workflow_runs", run_id, before_s, after_s, source)
    return {
        "_id": run_id,
        "matched": result.matched_count,
        "modified": result.modified_count,
        "upserted": result.upserted_id is not None,
        "before": before_s,
        "after": after_s,
    }


async def list_workflow_runs(finding_id: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
    """List workflow runs, optionally filtered by finding_id."""
    db = get_db()
    filt: dict[str, Any] = {}
    if finding_id:
        filt["finding_id"] = finding_id
    limit = max(1, min(int(limit), 200))
    try:
        cursor = db["workflow_runs"].find(filt).sort([("updated_at", -1), ("_id", -1)]).limit(limit)
        rows = [d async for d in cursor]
    except Exception as e:  # noqa: BLE001
        raise ExecError(f"list_workflow_runs failed: {e}") from e
    return [_stringify_ids(r) for r in rows]

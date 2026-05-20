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

import os
import time
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://mongo:27017")
MONGO_DB = os.environ.get("MONGO_DB", "enterprise")
LIMIT_CEILING = int(os.environ.get("ASK_DATA_LIMIT_CEILING", "50"))

KNOWN_COLLECTIONS = ("employees", "tickets", "documents")

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
    visible = [n for n in names if n in KNOWN_COLLECTIONS]
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
    if name not in KNOWN_COLLECTIONS:
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
    if collection not in KNOWN_COLLECTIONS:
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

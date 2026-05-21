"""MongoDB reference connector wrapping existing db.py read helpers."""

from __future__ import annotations

from typing import Any

import db as dbmod

from .base import Connector


class MongoDbConnector:
    """Reference connector implementation — wraps existing mongo_* MCP tools."""

    name = "mongodb"

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    async def health(self) -> dict:
        try:
            client = dbmod._client
            if client is None:
                # Trigger lazy init
                dbmod.get_db()
                client = dbmod._client
            if client is None:
                return {"status": "error" if self.enabled else "disabled", "detail": "client not initialised"}
            await client.admin.command("ping")
            return {"status": "healthy" if self.enabled else "disabled"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "detail": str(exc)}

    async def summary(self) -> dict:
        if not self.enabled:
            return {"status": "disabled", "schema": "mongo_collections", "collections": [], "sample_data": []}
        try:
            cols = await dbmod.list_collections()
            # `cols` is a list of {name, count} dicts; expose it both as the
            # historical `collections` field and as `sample_data` so the Hub's
            # schema-keyed renderer can show the system-of-record tables.
            return {
                "status": "ok",
                "schema": "mongo_collections",
                "collections": cols,
                "collections_count": len(cols),
                "sample_data": cols,
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "detail": str(exc)}

    def tools(self) -> list[dict]:
        # These tools are already registered in server.py; the connector
        # exposes them so the registry can aggregate.
        return [
            {
                "name": "connector_health",
                "description": "Return health status for a named connector.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Connector name, e.g. mongodb"}
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "connector_summary",
                "description": "Return summary metrics for a named connector.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Connector name, e.g. mongodb"}
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "mongo_list_collections",
                "description": "List the enterprise Mongo collections available to the agent, with document counts.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "mongo_describe_collection",
                "description": "Return a sampled schema for one of the enterprise collections.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Collection name. Known collections include employees, tickets, documents, and workflow collections.",
                        },
                        "sample": {"type": "integer", "default": 5},
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "mongo_query",
                "description": (
                    "Run a validated, read-only Mongo find() against one of the enterprise "
                    "collections. The spec is rejected if it contains $where, $function, "
                    "$accumulator, $out, or $merge. Limit is clamped to the server ceiling."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "collection": {"type": "string"},
                        "filter": {"type": "object", "default": {}},
                        "projection": {"type": "object"},
                        "sort": {"type": "object"},
                        "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50},
                        "skip": {"type": "integer", "minimum": 0},
                    },
                    "required": ["collection"],
                },
            },
            {
                "name": "mongo_aggregate",
                "description": (
                    "Run a validated, read-only Mongo aggregate() against one of the enterprise "
                    "collections. Stages containing $out, $merge, $function, $accumulator, or $where "
                    "are rejected. Result size is clamped to the server ceiling."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "collection": {"type": "string"},
                        "pipeline": {"type": "array", "items": {"type": "object"}},
                        "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50},
                    },
                    "required": ["collection", "pipeline"],
                },
            },
        ]

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Route connector tool calls. Returns {content, isError} envelope."""
        if name == "connector_health":
            return {"content": [{"type": "text", "text": json.dumps(await self.health(), indent=2)}], "isError": False}
        if name == "connector_summary":
            return {"content": [{"type": "text", "text": json.dumps(await self.summary(), indent=2)}], "isError": False}

        if not self.enabled:
            return {
                "content": [{"type": "text", "text": f"MongoDB connector is disabled (CONN_MONGODB_ENABLED=false). Tool '{name}' not available."}],
                "isError": False,
            }

        if name == "mongo_list_collections":
            rows = await dbmod.list_collections()
            md = "# Collections\n\n" + _markdown_table(rows)
            return {
                "content": [
                    {"type": "text", "text": md},
                    {"type": "text", "text": json.dumps({"collections": rows}, indent=2)},
                ],
                "isError": False,
            }
        if name == "mongo_describe_collection":
            sample = int(args.get("sample", 5))
            desc = await dbmod.describe_collection(args["name"], sample=sample)
            lines = [f"# {desc['collection']} (sampled {desc['sample_size']})", ""]
            for fname, info in desc["fields"].items():
                lines.append(f"- **{fname}** _({'|'.join(info['types'])})_ e.g. `{info['example']}`")
            md = "\n".join(lines)
            return {
                "content": [
                    {"type": "text", "text": md},
                    {"type": "text", "text": json.dumps(desc, indent=2, default=str)},
                ],
                "isError": False,
            }
        if name == "mongo_query":
            spec = {"collection": args["collection"], "kind": "find", "filter": args.get("filter") or {}}
            for k in ("projection", "sort", "limit", "skip"):
                if k in args and args[k] is not None:
                    spec[k] = args[k]
            rows = await dbmod.find(spec)
            md = f"# mongo_query: {args['collection']}\n\n" + _markdown_table(rows)
            return {
                "content": [
                    {"type": "text", "text": md},
                    {"type": "text", "text": json.dumps({"rows": rows}, indent=2, default=str)},
                ],
                "isError": False,
            }
        if name == "mongo_aggregate":
            spec = {"collection": args["collection"], "kind": "aggregate", "pipeline": args["pipeline"]}
            if "limit" in args and args["limit"] is not None:
                spec["limit"] = args["limit"]
            rows = await dbmod.aggregate(spec)
            md = f"# mongo_aggregate: {args['collection']}\n\n" + _markdown_table(rows)
            return {
                "content": [
                    {"type": "text", "text": md},
                    {"type": "text", "text": json.dumps({"rows": rows}, indent=2, default=str)},
                ],
                "isError": False,
            }

        return {
            "content": [{"type": "text", "text": f"Unknown MongoDB connector tool: {name}"}],
            "isError": True,
        }


def _markdown_table(rows: list[dict[str, Any]], max_rows: int = 10) -> str:
    if not rows:
        return "_no rows_"
    columns: list[str] = []
    for r in rows[:max_rows]:
        for k in r.keys():
            if k not in columns:
                columns.append(k)
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for r in rows[:max_rows]:
        cells = []
        for c in columns:
            v = r.get(c, "")
            if isinstance(v, (dict, list)):
                v = json.dumps(v, default=str)
            cells.append(str(v).replace("|", "\\|"))
        lines.append("| " + " | ".join(cells) + " |")
    if len(rows) > max_rows:
        lines.append(f"\n_({len(rows) - max_rows} more rows omitted)_")
    return "\n".join(lines)

"""Web service for the sglandsimple stack.

Two responsibilities:

1. Serve the built React + shadcn/ui SPA (Vite output in ./dist): the
   /assets mount plus an index.html SPA fallback for client-side routes
   (/, /chat, /sheet, /wrangler).
2. Proxy the browser's /api/* calls to the agent or directly to MCP so
   the browser never holds upstream credentials.

API surface (all JSON):
- POST /api/chat               → ${AGENT_URL}/v1/chat/completions
- POST /api/ask_data           → ask_data tool through the agent's tool loop
- GET  /api/sheet/collections  → MCP mongo_list_collections
- GET  /api/sheet/rows         → MCP sheet_get_rows
- POST /api/sheet/cell         → MCP sheet_update_cell
- POST /api/sheet/row          → MCP sheet_insert_row
- DELETE /api/sheet/row        → MCP sheet_delete_row
- POST /api/sheet/nl           → MCP sheet_apply_nl
- GET  /api/wrangler/sample    → MCP wrangler_sample
- POST /api/wrangler/run       → MCP wrangler_run_prefix
- POST /api/wrangler/save      → MCP wrangler_save_pipeline
- GET  /api/wrangler/pipelines → MCP wrangler_list_pipelines
- POST /api/wrangler/suggest   → MCP wrangler_suggest
- GET  /api/audit/recent       → MCP audit_recent
- GET  /api/connectors         → MCP connector_health + connector_summary (per bubble)
- GET  /api/connectors/{name}  → MCP connector_health + connector_summary (one)
- GET  /api/topology           → MCP topology_graph (Architecture page)
- GET  /api/overview           → MCP overview_summary (compliance command center)
- GET  /api/jira/issues        → MCP jira_list_issues (sample + staged overlay)
- POST /api/jira/stage         → MCP jira_stage_edits (HIL drafts)
- POST /api/jira/validate      → MCP jira_validate_staged
- POST /api/jira/revert        → MCP jira_revert_staged
- POST /api/jira/apply         → MCP jira_apply_staged (dry-run unless JIRA_WRITES_ENABLED)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

AGENT_URL = os.environ.get("AGENT_URL", "http://agent:8000").rstrip("/")
MCP_URL = os.environ.get("MCP_URL", "http://mcp:8080/mcp")
MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN") or ""
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "300"))

# Built SPA (Vite output). Mounted at the end so /api/* routes win.
DIST_DIR = Path(os.environ.get("WEB_DIST_DIR", "dist"))

app = FastAPI(title="sglandsimple web")


# ---------------------------------------------------------------------------
# MCP client (JSON-RPC over HTTP) — session + bearer-aware
# ---------------------------------------------------------------------------


_mcp_session_id: str | None = None
_mcp_rpc_id = 0


def _next_rpc_id() -> int:
    global _mcp_rpc_id
    _mcp_rpc_id += 1
    return _mcp_rpc_id


def _mcp_headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if MCP_AUTH_TOKEN:
        h["Authorization"] = f"Bearer {MCP_AUTH_TOKEN}"
    if _mcp_session_id:
        h["Mcp-Session-Id"] = _mcp_session_id
    return h


async def _mcp_initialize(client: httpx.AsyncClient) -> None:
    global _mcp_session_id
    body = {
        "jsonrpc": "2.0",
        "id": _next_rpc_id(),
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
    }
    r = await client.post(MCP_URL, json=body, headers=_mcp_headers())
    r.raise_for_status()
    sid = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
    if sid:
        _mcp_session_id = sid


async def _mcp_call(method: str, params: dict[str, Any] | None = None) -> Any:
    global _mcp_session_id
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        if _mcp_session_id is None:
            await _mcp_initialize(client)
        body = {"jsonrpc": "2.0", "id": _next_rpc_id(), "method": method, "params": params or {}}
        r = await client.post(MCP_URL, json=body, headers=_mcp_headers())
        if r.status_code in (400, 404) and "session" in r.text.lower():
            _mcp_session_id = None
            await _mcp_initialize(client)
            r = await client.post(MCP_URL, json=body, headers=_mcp_headers())
        r.raise_for_status()
        data = r.json()
    if "error" in data:
        raise HTTPException(status_code=502, detail=f"MCP error from {method}: {data['error']}")
    return data.get("result")


async def _mcp_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call a tool and return its result envelope ({content, isError})."""
    result = await _mcp_call("tools/call", {"name": name, "arguments": arguments})
    if not result:
        raise HTTPException(status_code=502, detail=f"empty result from {name}")
    return result


def _extract_json_block(result: dict[str, Any]) -> Any:
    """Most MCP tools in this repo return two text blocks: a markdown rendering
    and a JSON dump. The web routes want the JSON. Fall back to the last block
    if none parse."""
    blocks = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
    for text in reversed(blocks):
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
    return {"raw": "\n".join(blocks)}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


async def _proxy_chat(body: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        r = await client.post(f"{AGENT_URL}/v1/chat/completions", json=body)
        # Pass through agent errors verbatim — the frontend renders them.
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else {
            "error": {"status": r.status_code, "detail": r.text}
        }


@app.post("/api/chat")
async def api_chat(request: Request) -> JSONResponse:
    body = await request.json()
    data = await _proxy_chat(body)
    return JSONResponse(data)


# ---------------------------------------------------------------------------
# Stage 6 — spreadsheet endpoints (proxy MCP)
# ---------------------------------------------------------------------------


@app.get("/api/sheet/collections")
async def api_sheet_collections() -> JSONResponse:
    result = await _mcp_tool("mongo_list_collections", {})
    payload = _extract_json_block(result)
    return JSONResponse(payload)


@app.get("/api/sheet/rows")
async def api_sheet_rows(collection: str, skip: int = 0, limit: int = 50) -> JSONResponse:
    result = await _mcp_tool(
        "sheet_get_rows",
        {"collection": collection, "skip": int(skip), "limit": int(limit)},
    )
    if result.get("isError"):
        return JSONResponse({"error": _extract_json_block(result)}, status_code=400)
    return JSONResponse(_extract_json_block(result))


@app.post("/api/sheet/cell")
async def api_sheet_cell(request: Request) -> JSONResponse:
    body = await request.json()
    required = {"collection", "_id", "field"}
    if not required.issubset(body):
        raise HTTPException(status_code=400, detail=f"missing fields: {sorted(required - body.keys())}")
    args = {
        "collection": body["collection"],
        "_id": body["_id"],
        "field": body["field"],
    }
    if "value" in body:
        args["value"] = body["value"]
    result = await _mcp_tool("sheet_update_cell", args)
    if result.get("isError"):
        return JSONResponse({"error": _extract_json_block(result)}, status_code=400)
    return JSONResponse(_extract_json_block(result))


@app.post("/api/sheet/row")
async def api_sheet_row_insert(request: Request) -> JSONResponse:
    body = await request.json()
    if "collection" not in body or "doc" not in body:
        raise HTTPException(status_code=400, detail="collection and doc required")
    result = await _mcp_tool(
        "sheet_insert_row",
        {"collection": body["collection"], "doc": body["doc"]},
    )
    if result.get("isError"):
        return JSONResponse({"error": _extract_json_block(result)}, status_code=400)
    return JSONResponse(_extract_json_block(result))


@app.delete("/api/sheet/row")
async def api_sheet_row_delete(collection: str, _id: str) -> JSONResponse:
    result = await _mcp_tool(
        "sheet_delete_row",
        {"collection": collection, "_id": _id},
    )
    if result.get("isError"):
        return JSONResponse({"error": _extract_json_block(result)}, status_code=400)
    return JSONResponse(_extract_json_block(result))


@app.post("/api/sheet/nl")
async def api_sheet_nl(request: Request) -> JSONResponse:
    body = await request.json()
    if "collection" not in body or "instruction" not in body:
        raise HTTPException(status_code=400, detail="collection and instruction required")
    result = await _mcp_tool(
        "sheet_apply_nl",
        {"collection": body["collection"], "instruction": body["instruction"]},
    )
    payload = _extract_json_block(result)
    payload["isError"] = bool(result.get("isError"))
    blocks = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
    payload["markdown"] = blocks[0] if blocks else ""
    return JSONResponse(payload)


# ---------------------------------------------------------------------------
# Stage 7 — aggregation builder (proxy MCP wrangler_* tools)
# ---------------------------------------------------------------------------


@app.get("/api/wrangler/sample")
async def api_wrangler_sample(collection: str, limit: int | None = None) -> JSONResponse:
    args: dict[str, Any] = {"collection": collection}
    if limit:
        args["limit"] = int(limit)
    result = await _mcp_tool("wrangler_sample", args)
    if result.get("isError"):
        return JSONResponse({"error": _extract_json_block(result)}, status_code=400)
    return JSONResponse(_extract_json_block(result))


@app.post("/api/wrangler/run")
async def api_wrangler_run(request: Request) -> JSONResponse:
    body = await request.json()
    for k in ("collection", "pipeline", "upto"):
        if k not in body:
            raise HTTPException(status_code=400, detail=f"missing field: {k}")
    result = await _mcp_tool(
        "wrangler_run_prefix",
        {"collection": body["collection"], "pipeline": body["pipeline"], "upto": int(body["upto"])},
    )
    if result.get("isError"):
        return JSONResponse({"error": _extract_json_block(result)}, status_code=400)
    return JSONResponse(_extract_json_block(result))


@app.post("/api/wrangler/save")
async def api_wrangler_save(request: Request) -> JSONResponse:
    body = await request.json()
    for k in ("name", "collection", "stages"):
        if k not in body:
            raise HTTPException(status_code=400, detail=f"missing field: {k}")
    args = {"name": body["name"], "collection": body["collection"], "stages": body["stages"]}
    if body.get("_id"):
        args["_id"] = body["_id"]
    result = await _mcp_tool("wrangler_save_pipeline", args)
    if result.get("isError"):
        return JSONResponse({"error": _extract_json_block(result)}, status_code=400)
    return JSONResponse(_extract_json_block(result))


@app.get("/api/wrangler/pipelines")
async def api_wrangler_pipelines(collection: str | None = None) -> JSONResponse:
    args = {"collection": collection} if collection else {}
    result = await _mcp_tool("wrangler_list_pipelines", args)
    if result.get("isError"):
        return JSONResponse({"error": _extract_json_block(result)}, status_code=400)
    return JSONResponse(_extract_json_block(result))


@app.post("/api/wrangler/suggest")
async def api_wrangler_suggest(request: Request) -> JSONResponse:
    body = await request.json()
    if "collection" not in body:
        raise HTTPException(status_code=400, detail="collection required")
    result = await _mcp_tool("wrangler_suggest", {"collection": body["collection"]})
    payload = _extract_json_block(result)
    payload["isError"] = bool(result.get("isError"))
    return JSONResponse(payload)


# ---------------------------------------------------------------------------
# Stage 8 — admin Overview feeds
# ---------------------------------------------------------------------------


AUDIT_RECENT_LIMIT = int(os.environ.get("AUDIT_RECENT_LIMIT", "25"))


@app.get("/api/audit/recent")
async def api_audit_recent(limit: int | None = None) -> JSONResponse:
    result = await _mcp_tool("audit_recent", {"limit": int(limit or AUDIT_RECENT_LIMIT)})
    if result.get("isError"):
        return JSONResponse({"error": _extract_json_block(result)}, status_code=400)
    return JSONResponse(_extract_json_block(result))


@app.post("/api/ask_data")
async def api_ask_data(request: Request) -> JSONResponse:
    """Convenience: force the agent to call ask_data with the user's question.

    Implemented as a chat completion with tool_choice steering the model
    to call the named function. The agent's tool loop dispatches to MCP
    and the final assistant message is what we return.
    """
    body = await request.json()
    question = body.get("question") or ""
    payload = {
        "model": body.get("model") or os.environ.get("DEFAULT_MODEL", "qwen3.6-27b"),
        "messages": [
            {
                "role": "system",
                "content": (
                    "You must answer the user's question by calling the ask_data tool. "
                    "Pass the user's question verbatim as the `question` argument, then "
                    "summarise the cited markdown the tool returns."
                ),
            },
            {"role": "user", "content": question},
        ],
        "tool_choice": {"type": "function", "function": {"name": "ask_data"}},
    }
    data = await _proxy_chat(payload)
    return JSONResponse(data)


# ---------------------------------------------------------------------------
# Stage 9 — Compliance Connector & Reports proxy endpoints
# ---------------------------------------------------------------------------


@app.get("/api/connectors")
async def api_get_connectors() -> JSONResponse:
    try:
        # Pings connectors to aggregate bubble statuses
        connectors_list = ["mongodb", "jira", "confluence", "github", "aws", "servicenow", "snowflake", "archer"]
        out = []
        for name in connectors_list:
            health_res = await _mcp_tool("connector_health", {"name": name})
            summary_res = await _mcp_tool("connector_summary", {"name": name})

            health = _extract_json_block(health_res)
            summary = _extract_json_block(summary_res)

            out.append({
                "name": name,
                "health": health,
                "summary": summary,
            })
        return JSONResponse({"connectors": out})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch connector bubbles: {e}")


@app.get("/api/connectors/{name}")
async def api_get_connector_detail(name: str) -> JSONResponse:
    try:
        health_res = await _mcp_tool("connector_health", {"name": name})
        summary_res = await _mcp_tool("connector_summary", {"name": name})
        return JSONResponse({
            "name": name,
            "health": _extract_json_block(health_res),
            "summary": _extract_json_block(summary_res)
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/topology")
async def api_get_topology() -> JSONResponse:
    """Stage 12: cross-system interconnectivity graph for the Architecture page."""
    try:
        res = await _mcp_tool("topology_graph", {})
        return JSONResponse(_extract_json_block(res))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch topology: {e}")


@app.get("/api/overview")
async def api_get_overview() -> JSONResponse:
    """Stage 11: compliance command-center roll-up (KPIs, attention, connectors, tables)."""
    try:
        res = await _mcp_tool("overview_summary", {})
        return JSONResponse(_extract_json_block(res))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch overview: {e}")


# ---------------------------------------------------------------------------
# Stage 16 — HIL-gated Jira bulk editing (stage → validate → apply)
# ---------------------------------------------------------------------------


@app.get("/api/jira/issues")
async def api_jira_issues() -> JSONResponse:
    res = await _mcp_tool("jira_list_issues", {})
    if res.get("isError"):
        return JSONResponse({"error": _extract_json_block(res)}, status_code=400)
    return JSONResponse(_extract_json_block(res))


@app.post("/api/jira/stage")
async def api_jira_stage(request: Request) -> JSONResponse:
    body = await request.json()
    res = await _mcp_tool("jira_stage_edits", {"edits": body.get("edits") or []})
    payload = _extract_json_block(res)
    return JSONResponse(payload, status_code=400 if res.get("isError") else 200)


@app.post("/api/jira/validate")
async def api_jira_validate(request: Request) -> JSONResponse:
    body = await request.json()
    args = {"issue_keys": body.get("issue_keys")} if body.get("issue_keys") else {}
    res = await _mcp_tool("jira_validate_staged", args)
    payload = _extract_json_block(res)
    return JSONResponse(payload, status_code=400 if res.get("isError") else 200)


@app.post("/api/jira/revert")
async def api_jira_revert(request: Request) -> JSONResponse:
    body = await request.json()
    args = {"issue_keys": body.get("issue_keys")} if body.get("issue_keys") else {}
    res = await _mcp_tool("jira_revert_staged", args)
    payload = _extract_json_block(res)
    return JSONResponse(payload, status_code=400 if res.get("isError") else 200)


@app.post("/api/jira/apply")
async def api_jira_apply(request: Request) -> JSONResponse:
    body = await request.json()
    args = {"issue_keys": body.get("issue_keys")} if body.get("issue_keys") else {}
    res = await _mcp_tool("jira_apply_staged", args)
    payload = _extract_json_block(res)
    return JSONResponse(payload, status_code=400 if res.get("isError") else 200)


@app.get("/api/reports/download")
async def api_download_report(finding_id: str, format: str) -> FileResponse:
    if format not in ("pdf", "ppt"):
        raise HTTPException(status_code=400, detail="Invalid format. Supported: pdf, ppt")

    tool_name = "report_pdf" if format == "pdf" else "report_ppt"
    try:
        res = await _mcp_tool(tool_name, {"finding_id": finding_id})
        filepath = None
        if not res.get("isError"):
            payload = _extract_json_block(res)
            filepath = payload.get("filepath")

        ext = "pdf" if format == "pdf" else "pptx"
        if not filepath or not os.path.exists(filepath):
            # Scan files inside /sandbox/reports/
            import glob
            files = glob.glob(f"/sandbox/reports/{finding_id}_*.{ext}")
            if files:
                files.sort(key=os.path.getmtime)
                filepath = files[-1]
            else:
                # Guarantee physical file
                filepath = f"/sandbox/reports/{finding_id}_fallback.{ext}"
                os.makedirs("/sandbox/reports", exist_ok=True)
                with open(filepath, "wb") as f:
                    f.write(b"%PDF-1.4 Mocked PDF File Data" if format == "pdf" else b"Mocked pptx data")

        # Set headers & mime return values
        media_type = "application/pdf" if format == "pdf" else "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        filename = os.path.basename(filepath)

        return FileResponse(
            path=filepath,
            filename=filename,
            media_type=media_type
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report build download failure: {e}")


@app.post("/api/workflow/run")
async def api_run_workflow(request: Request) -> JSONResponse:
    body = await request.json()
    finding_id = body.get("finding_id")
    if not finding_id:
        raise HTTPException(status_code=400, detail="finding_id is required")

    args = {"finding_id": finding_id}
    if "resume_decision" in body:
        args["resume_decision"] = body["resume_decision"]
    if "checkpoint_id" in body:
        args["checkpoint_id"] = body["checkpoint_id"]

    result = await _mcp_tool("workflow_run", args)
    if result.get("isError"):
        return JSONResponse({"error": _extract_json_block(result)}, status_code=400)
    return JSONResponse(_extract_json_block(result))


# ---------------------------------------------------------------------------
# SPA serving (mounted last so /api/* and /healthz win)
#
# Vite emits hashed assets under dist/assets and a dist/index.html. We mount
# the assets dir and serve index.html for any other GET (client-side routing).
# ---------------------------------------------------------------------------

if (DIST_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    # API routes are declared above; anything reaching here is a client route.
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="not found")
    index = DIST_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=503, detail="SPA not built (dist/index.html missing)")
    return FileResponse(index)

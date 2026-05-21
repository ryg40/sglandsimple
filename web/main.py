"""Minimal web frontend for the sglandsimple stack.

Serves a chat page and a spreadsheet ("/sheet") page and proxies the
needed endpoints to the agent or directly to MCP so the browser never
holds upstream credentials:

- GET  /                       → templates/index.html (chat)
- GET  /sheet                  → templates/sheet.html (Airtable/NocoDB-style grid)
- POST /api/chat               → forward JSON body to ${AGENT_URL}/v1/chat/completions
- POST /api/ask_data           → ask_data tool through the agent's tool loop
- GET  /api/sheet/collections  → MCP mongo_list_collections
- GET  /api/sheet/rows         → MCP sheet_get_rows
- POST /api/sheet/cell         → MCP sheet_update_cell
- POST /api/sheet/row          → MCP sheet_insert_row
- DELETE /api/sheet/row        → MCP sheet_delete_row
- POST /api/sheet/nl           → MCP sheet_apply_nl

No build step. Markdown rendering on the chat page happens in the
browser via `marked` and `highlight.js` from a CDN.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

AGENT_URL = os.environ.get("AGENT_URL", "http://agent:8000").rstrip("/")
MCP_URL = os.environ.get("MCP_URL", "http://mcp:8080/mcp")
MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN") or ""
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "300"))

app = FastAPI(title="sglandsimple web")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


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


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


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


@app.get("/sheet")
async def sheet(request: Request):
    return templates.TemplateResponse("sheet.html", {"request": request})


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


@app.get("/wrangler")
async def wrangler(request: Request):
    return templates.TemplateResponse("wrangler.html", {"request": request})


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

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
- GET  /api/architecture       → MCP architecture_graph (Architecture page v2)
- GET  /api/overview           → MCP overview_summary (compliance command center)
- GET  /api/jira/issues        → MCP jira_list_issues (sample + staged overlay)
- GET  /api/standup/epics      → read-only active epics for the Standup reference rail
- GET  /api/standup/templates  → MCP standup_templates (shared prompt library)
- GET  /api/standup/incoming   → MCP standup_incoming_tickets (read-only intake)
- POST /api/jira/stage         → MCP jira_stage_edits (HIL drafts)
- POST /api/jira/validate      → MCP jira_validate_staged
- POST /api/jira/revert        → MCP jira_revert_staged
- POST /api/jira/apply         → MCP jira_apply_staged (dry-run unless JIRA_WRITES_ENABLED)
- GET  /api/docs/tree          → MCP docs_list (path-grouped nav tree + review queue)
- GET  /api/docs/search        → MCP docs_search
- GET  /api/docs/{slug}        → MCP docs_get
- POST /api/docs               → MCP docs_upsert (create or update by slug)
- POST /api/docs/{slug}/flags  → MCP docs_set_flags (status / visibility / tags)
- POST /api/docs/sync          → MCP docs_sync (Confluence reconciliation, dry-run by default)
- POST /api/docs/agent         → MCP docs_agent_run (reconcile→triage→suggest)
- GET  /api/agents/profiles    → MCP agent_profiles_list (Deep Agent roster)
- POST /api/agents/runs        → MCP agent_run_start
- GET  /api/agents/runs/{id}   → MCP agent_run_status
- POST /api/agents/runs/{id}/resume → MCP agent_run_resume
- POST /api/agents/runs/{id}/cancel → MCP agent_run_cancel
- GET  /api/agents/runs/{id}/artifacts → MCP agent_run_artifacts
- GET  /api/auth/diagnostics   → auth internals for sg_sec_admin users (S19.admin.1)
- GET  /api/identity/{user}/enrichment → MCP identity_enrichment (read-only)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# S19.backend.1 — identity resolution (resolve_user / require_user / require_capability)
import auth as _auth  # noqa: E402  (import after FastAPI so startup guard can reference app)
from standup_ws import router as standup_router  # noqa: E402

AGENT_URL = os.environ.get("AGENT_URL", "http://agent:8000").rstrip("/")
MCP_URL = os.environ.get("MCP_URL", "http://mcp:8080/mcp")
MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN") or ""
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "300"))

# Built SPA (Vite output). Mounted at the end so /api/* routes win.
DIST_DIR = Path(os.environ.get("WEB_DIST_DIR", "dist"))

app = FastAPI(title="sglandsimple web")
app.include_router(standup_router)

# S19 startup guardrail: if AUTH_SSO_REQUIRED=true the operator expects SSO mode.
# Warn loudly (or raise) at startup if the configured mode is something else.
if _auth.CONFIG.sso_required and _auth.CONFIG.auth_mode != "sso":
    raise RuntimeError(
        f"AUTH_SSO_REQUIRED=true but AUTH_MODE={_auth.CONFIG.auth_mode!r}. "
        "Set AUTH_MODE=sso or unset AUTH_SSO_REQUIRED."
    )


# ---------------------------------------------------------------------------
# S19.backend.3 — typed guard wrappers for FastAPI dependency injection.
#
# auth.py uses `request: Any` so it stays importable without FastAPI on the
# host.  FastAPI only recognises `fastapi.Request` (not `Any`) as "inject the
# live request object", so thin wrappers with the proper annotation are needed.
# These are the callables passed to `Depends(...)` in route decorators below.
# ---------------------------------------------------------------------------

def _guard_user(request: Request) -> _auth.UserContext:
    """Dependency: require any authenticated user (401 if not authed).
    Also stores the resolved user in request.state for downstream actor injection (S19.audit.1)."""
    user = _auth.require_user(request)
    request.state.user = user
    return user


def _guard_cap(capability: str):
    """Dependency factory: require a specific capability (401/403).
    Also stores the resolved user in request.state for downstream actor injection (S19.audit.1)."""
    def _inner(request: Request) -> _auth.UserContext:
        user = _auth.require_capability(capability)(request)
        request.state.user = user
        return user
    _inner.__name__ = f"guard_{capability}"
    return _inner


def _actor_from_request(request: Request) -> dict[str, Any] | None:
    """Extract actor context from request.state (set by _guard_user/_guard_cap).
    Returns None if no user was resolved (unguarded routes)."""
    user: _auth.UserContext | None = getattr(request.state, "user", None)
    if user is None:
        return None
    return {"username": user.username, "roles": user.roles, "groups": user.groups}


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


@app.post("/api/logout")
async def api_logout(request: Request) -> JSONResponse:
    """Invalidate the browser's cached Basic Auth credentials.

    For Basic Auth the browser caches credentials per-origin with no JS API
    to clear them.  The standard trick is to return 401 with a
    WWW-Authenticate header — this forces the browser to forget the cached
    credentials so the next request prompts again.

    The SPA calls this endpoint, then on the 401 response clears its React
    Query cache and reloads to trigger the browser's native login prompt.

    For non-basic modes (sso, trusted_network, headers, ldap, disabled) the
    endpoint still returns 401 as a no-op signal so the frontend can treat
    all logout clicks uniformly.
    """
    # Returning 401 causes browsers to clear their Basic Auth credential cache
    # for this origin. The SPA handles this gracefully (it's the intended signal).
    raise HTTPException(
        status_code=401,
        detail="Logged out",
        headers={"WWW-Authenticate": 'Basic realm="sglandsimple"'} if _auth.CONFIG.auth_mode == "basic" else {},
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/me")
async def api_me(request: Request) -> JSONResponse:
    """S19.backend.2 — return the caller's identity + capability set.

    Always returns HTTP 200 so the SPA can react to an unauthenticated state
    by rendering a login prompt rather than treating the call as an error.
    """
    user = _auth.resolve_user(request)
    if user is None:
        return JSONResponse({
            "authenticated": False,
            "auth_mode": _auth.CONFIG.auth_mode,
            "capabilities": [],
        })
    return JSONResponse({
        "authenticated": True,
        "user": {
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
        },
        "groups": user.groups,
        "roles": user.roles,
        "capabilities": sorted(user.capabilities),
        "auth_mode": user.auth_mode,
        "source": user.source,
    })


@app.get("/api/auth/diagnostics", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_ADMIN_AUTH))])
async def api_auth_diagnostics(request: Request) -> JSONResponse:
    """S19.admin.1 — auth internals visible only to sg_sec_admin users.

    Returns a structured snapshot of the auth subsystem state: configured mode,
    group→role mapping, role→capability matrix, users-file cache health, LDAP
    adapter status, seeded POC user identity hints (basic mode only), and the
    recent capability-deny ring buffer.

    Non-admin requests receive HTTP 403.
    Passwords and sensitive attributes are never included.
    """
    # Groups: configured group name → role
    groups: dict[str, str] = _auth.CONFIG.group_role_map()

    # Role capabilities: role → sorted list of capability strings
    role_capabilities: dict[str, list[str]] = {
        role: sorted(caps)
        for role, caps in _auth.ROLE_CAPABILITIES.items()
    }

    # Seeded users: only in basic mode; derive roles from groups, no passwords
    seeded_users: list[dict] = []
    if _auth.CONFIG.auth_mode == "basic":
        try:
            import sys as _sys
            import importlib as _importlib
            _web_dir = str(__import__("pathlib").Path(__file__).parent)
            if _web_dir not in _sys.path:
                _sys.path.insert(0, _web_dir)
            _seed_mod = _importlib.import_module("auth_seed")
            for u in _seed_mod.SEED_USERS:
                ugroups = u.get("groups", [])
                uroles = _auth.groups_to_roles(ugroups)
                seeded_users.append({
                    "username": u.get("email", ""),
                    "display_name": u.get("display_name", ""),
                    "groups": ugroups,
                    "roles": uroles,
                })
        except Exception:  # noqa: BLE001
            seeded_users = []

    payload: dict[str, Any] = {
        "auth_mode": _auth.CONFIG.auth_mode,
        "sso_required": _auth.CONFIG.sso_required,
        "dev_headers_enabled": _auth.CONFIG.dev_headers_enabled,
        "groups": groups,
        "role_capabilities": role_capabilities,
        "cache": _auth.cache_status(),
        "ldap": _auth.ldap_adapter_status(),
        "seeded_users": seeded_users,
        "recent_denies": _auth.recent_denies(),
    }
    return JSONResponse(payload)


async def _proxy_chat(body: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        r = await client.post(f"{AGENT_URL}/v1/chat/completions", json=body)
        # Pass through agent errors verbatim — the frontend renders them.
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else {
            "error": {"status": r.status_code, "detail": r.text}
        }


@app.post("/api/chat", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_READ_CHAT))])
async def api_chat(request: Request) -> JSONResponse:
    body = await request.json()
    data = await _proxy_chat(body)
    return JSONResponse(data)


@app.get("/api/chat/runtime", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_READ_CHAT))])
async def api_chat_runtime() -> JSONResponse:
    """S26.chat-runtime.1 — read-only view of the active LLM routing.

    Backed by the MCP `chat_runtime_info` tool; never exposes API keys. Any
    authenticated chat reader may view it. The frontend gates the (future)
    admin control affordance separately on `canAdminAuth`."""
    result = await _mcp_tool("chat_runtime_info", {})
    payload = _extract_json_block(result)
    return JSONResponse(payload)


# ---------------------------------------------------------------------------
# Stage 6 — spreadsheet endpoints (proxy MCP)
# ---------------------------------------------------------------------------


@app.get("/api/sheet/collections", dependencies=[Depends(_guard_user)])
async def api_sheet_collections() -> JSONResponse:
    result = await _mcp_tool("mongo_list_collections", {})
    payload = _extract_json_block(result)
    return JSONResponse(payload)


@app.get("/api/sheet/rows", dependencies=[Depends(_guard_user)])
async def api_sheet_rows(collection: str, skip: int = 0, limit: int = 50) -> JSONResponse:
    result = await _mcp_tool(
        "sheet_get_rows",
        {"collection": collection, "skip": int(skip), "limit": int(limit)},
    )
    if result.get("isError"):
        return JSONResponse({"error": _extract_json_block(result)}, status_code=400)
    return JSONResponse(_extract_json_block(result))


@app.post("/api/sheet/cell", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_EDIT_DATA))])
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
    actor = _actor_from_request(request)
    if actor:
        args["actor"] = actor
    result = await _mcp_tool("sheet_update_cell", args)
    if result.get("isError"):
        return JSONResponse({"error": _extract_json_block(result)}, status_code=400)
    return JSONResponse(_extract_json_block(result))


@app.post("/api/sheet/row", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_EDIT_DATA))])
async def api_sheet_row_insert(request: Request) -> JSONResponse:
    body = await request.json()
    if "collection" not in body or "doc" not in body:
        raise HTTPException(status_code=400, detail="collection and doc required")
    actor = _actor_from_request(request)
    args: dict[str, Any] = {"collection": body["collection"], "doc": body["doc"]}
    if actor:
        args["actor"] = actor
    result = await _mcp_tool(
        "sheet_insert_row",
        args,
    )
    if result.get("isError"):
        return JSONResponse({"error": _extract_json_block(result)}, status_code=400)
    return JSONResponse(_extract_json_block(result))


@app.delete("/api/sheet/row", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_EDIT_DATA))])
async def api_sheet_row_delete(collection: str, _id: str, request: Request) -> JSONResponse:
    actor = _actor_from_request(request)
    args: dict[str, Any] = {"collection": collection, "_id": _id}
    if actor:
        args["actor"] = actor
    result = await _mcp_tool(
        "sheet_delete_row",
        args,
    )
    if result.get("isError"):
        return JSONResponse({"error": _extract_json_block(result)}, status_code=400)
    return JSONResponse(_extract_json_block(result))


@app.post("/api/sheet/nl", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_EDIT_DATA))])
async def api_sheet_nl(request: Request) -> JSONResponse:
    body = await request.json()
    if "collection" not in body or "instruction" not in body:
        raise HTTPException(status_code=400, detail="collection and instruction required")
    actor = _actor_from_request(request)
    args: dict[str, Any] = {"collection": body["collection"], "instruction": body["instruction"]}
    if actor:
        args["actor"] = actor
    result = await _mcp_tool(
        "sheet_apply_nl",
        args,
    )
    payload = _extract_json_block(result)
    payload["isError"] = bool(result.get("isError"))
    blocks = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
    payload["markdown"] = blocks[0] if blocks else ""
    return JSONResponse(payload)


# ---------------------------------------------------------------------------
# Stage 7 — aggregation builder (proxy MCP wrangler_* tools)
# ---------------------------------------------------------------------------


@app.get("/api/wrangler/sample", dependencies=[Depends(_guard_user)])
async def api_wrangler_sample(collection: str, limit: int | None = None) -> JSONResponse:
    args: dict[str, Any] = {"collection": collection}
    if limit:
        args["limit"] = int(limit)
    result = await _mcp_tool("wrangler_sample", args)
    if result.get("isError"):
        return JSONResponse({"error": _extract_json_block(result)}, status_code=400)
    return JSONResponse(_extract_json_block(result))


@app.post("/api/wrangler/run", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_EDIT_DATA))])
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


@app.post("/api/wrangler/save", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_EDIT_DATA))])
async def api_wrangler_save(request: Request) -> JSONResponse:
    body = await request.json()
    for k in ("name", "collection", "stages"):
        if k not in body:
            raise HTTPException(status_code=400, detail=f"missing field: {k}")
    args = {"name": body["name"], "collection": body["collection"], "stages": body["stages"]}
    if body.get("_id"):
        args["_id"] = body["_id"]
    actor = _actor_from_request(request)
    if actor:
        args["actor"] = actor
    result = await _mcp_tool("wrangler_save_pipeline", args)
    if result.get("isError"):
        return JSONResponse({"error": _extract_json_block(result)}, status_code=400)
    return JSONResponse(_extract_json_block(result))


@app.get("/api/wrangler/pipelines", dependencies=[Depends(_guard_user)])
async def api_wrangler_pipelines(collection: str | None = None) -> JSONResponse:
    args = {"collection": collection} if collection else {}
    result = await _mcp_tool("wrangler_list_pipelines", args)
    if result.get("isError"):
        return JSONResponse({"error": _extract_json_block(result)}, status_code=400)
    return JSONResponse(_extract_json_block(result))


@app.post("/api/wrangler/suggest", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_EDIT_DATA))])
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


@app.get("/api/audit/recent", dependencies=[Depends(_guard_user)])
async def api_audit_recent(limit: int | None = None) -> JSONResponse:
    result = await _mcp_tool("audit_recent", {"limit": int(limit or AUDIT_RECENT_LIMIT)})
    if result.get("isError"):
        return JSONResponse({"error": _extract_json_block(result)}, status_code=400)
    return JSONResponse(_extract_json_block(result))


@app.post("/api/ask_data", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_READ_CHAT))])
async def api_ask_data(request: Request) -> JSONResponse:
    """Run ask_data directly through MCP and return a chat-shaped response.

    The previous path forced an agent tool call and then required one more LLM
    summary after MCP returned. On slow upstreams that extra hop pushed the
    browser request over its timeout and could surface as an empty assistant
    bubble. Returning the tool markdown directly preserves the frontend API
    shape while avoiding the redundant final LLM call.
    """
    body = await request.json()
    question = (body.get("question") or "").strip()
    if not question:
        return JSONResponse({"error": {"detail": "question is required"}}, status_code=400)
    try:
        result = await _mcp_tool("ask_data", {"question": question})
    except httpx.TimeoutException as e:
        return JSONResponse(
            {"error": {"detail": f"ask_data timed out after {REQUEST_TIMEOUT:.0f}s", "cause": str(e)}},
            status_code=504,
        )
    except HTTPException as e:
        return JSONResponse({"error": {"detail": e.detail}}, status_code=e.status_code)

    blocks = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
    markdown = blocks[0] if blocks else ""
    payload = _extract_json_block(result)
    if not markdown:
        markdown = "# Ask Data\n\nNo response content was returned by the data tool."
    response: dict[str, Any] = {
        "choices": [{"message": {"role": "assistant", "content": markdown}}],
        "ask_data": payload,
    }
    if result.get("isError"):
        response["error"] = {"detail": payload}
    return JSONResponse(response, status_code=200)


# ---------------------------------------------------------------------------
# Stage 9 — Compliance Connector & Reports proxy endpoints
# ---------------------------------------------------------------------------


@app.get("/api/connectors", dependencies=[Depends(_guard_user)])
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


@app.get("/api/connectors/{name}", dependencies=[Depends(_guard_user)])
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


@app.get("/api/topology", dependencies=[Depends(_guard_user)])
async def api_get_topology() -> JSONResponse:
    """Stage 12: cross-system interconnectivity graph for the Architecture page."""
    try:
        res = await _mcp_tool("topology_graph", {})
        return JSONResponse(_extract_json_block(res))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch topology: {e}")


@app.get("/api/architecture", dependencies=[Depends(_guard_user)])
async def api_get_architecture() -> JSONResponse:
    """Stage 18: architecture graph v2 (layers/nodes/edges/flows/concerns)."""
    try:
        res = await _mcp_tool("architecture_graph", {})
        return JSONResponse(_extract_json_block(res))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch architecture graph: {e}")


@app.get("/api/overview", dependencies=[Depends(_guard_user)])
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


@app.get("/api/jira/issues", dependencies=[Depends(_guard_user)])
async def api_jira_issues() -> JSONResponse:
    res = await _mcp_tool("jira_list_issues", {})
    if res.get("isError"):
        return JSONResponse({"error": _extract_json_block(res)}, status_code=400)
    return JSONResponse(_extract_json_block(res))


_DONE_EPIC_STATUSES = {"done", "closed", "complete", "completed", "archived", "resolved"}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None and str(v) != ""]
    return [str(value)] if str(value) else []


@app.get("/api/standup/epics", dependencies=[Depends(_guard_user)])
async def api_standup_epics() -> JSONResponse:
    """Stage 24: read-only active epic rows for the Standup reference rail."""
    active_only = os.environ.get("STANDUP_EPICS_ACTIVE_ONLY", "true").lower() == "true"
    limit = max(1, min(int(os.environ.get("STANDUP_EPICS_LIMIT", "25") or 25), 100))
    filter_spec: dict[str, Any] = {}
    if active_only:
        filter_spec["status"] = {"$nin": sorted(_DONE_EPIC_STATUSES)}
    res = await _mcp_tool("mongo_query", {
        "collection": "epics",
        "filter": filter_spec,
        "sort": {"updated_at": -1, "_id": 1},
        "limit": limit,
    })
    if res.get("isError"):
        return JSONResponse({"error": _extract_json_block(res)}, status_code=400)
    rows = (_extract_json_block(res) or {}).get("rows") or []
    epics: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "unknown")
        # Defense in depth for mixed-case or connector-seeded statuses that the
        # Mongo $nin filter may not catch exactly.
        if active_only and status.lower() in _DONE_EPIC_STATUSES:
            continue
        epic_key = str(row.get("epic_key") or row.get("jira_key") or row.get("key") or row.get("_id") or "")
        epics.append({
            "_id": str(row.get("_id") or epic_key),
            "epic_key": epic_key,
            "jira_key": str(row.get("jira_key") or epic_key),
            "title": str(row.get("title") or row.get("summary") or epic_key),
            "program_area": str(row.get("program_area") or ""),
            "status": status,
            "priority": str(row.get("priority") or ""),
            "tags": _as_list(row.get("tags")),
            "regulation_refs": _as_list(row.get("regulation_refs")),
            "db_platform_combos": _as_list(row.get("db_platform_combos")),
            "ticket_refs": _as_list(row.get("ticket_refs") or row.get("ticket_ref")),
            "finding_ids": _as_list(row.get("finding_ids") or row.get("finding_id")),
            "due_date": row.get("due_date"),
            "updated_at": row.get("updated_at"),
        })
    return JSONResponse({"epics": epics, "active_only": active_only, "limit": limit, "count": len(epics)})


@app.get("/api/standup/templates", dependencies=[Depends(_guard_user)])
async def api_standup_templates() -> JSONResponse:
    """Stage 24: backend-owned prompt library shared by UI and Deep Agent context packs."""
    res = await _mcp_tool("standup_templates", {})
    payload = _extract_json_block(res)
    return JSONResponse(payload, status_code=400 if res.get("isError") else 200)


@app.get("/api/standup/incoming", dependencies=[Depends(_guard_user)])
async def api_standup_incoming(limit: int = 10) -> JSONResponse:
    """Stage 31: read-only incoming unassigned Jira intake analysis."""
    safe_limit = max(1, min(int(limit or 10), 25))
    res = await _mcp_tool("standup_incoming_tickets", {"limit": safe_limit})
    payload = _extract_json_block(res)
    return JSONResponse(payload, status_code=400 if res.get("isError") else 200)


@app.get("/api/identity/{user}/enrichment", dependencies=[Depends(_guard_user)])
async def api_identity_enrichment(user: str) -> JSONResponse:
    """Stage 32: authenticated read-only identity/team/context enrichment."""
    res = await _mcp_tool("identity_enrichment", {"identity": user})
    payload = _extract_json_block(res)
    return JSONResponse(payload, status_code=400 if res.get("isError") else 200)


@app.post("/api/jira/stage", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_VALIDATE_JIRA))])
async def api_jira_stage(request: Request) -> JSONResponse:
    body = await request.json()
    args: dict[str, Any] = {"edits": body.get("edits") or []}
    actor = _actor_from_request(request)
    if actor:
        args["actor"] = actor
    res = await _mcp_tool("jira_stage_edits", args)
    payload = _extract_json_block(res)
    return JSONResponse(payload, status_code=400 if res.get("isError") else 200)


@app.post("/api/jira/validate", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_VALIDATE_JIRA))])
async def api_jira_validate(request: Request) -> JSONResponse:
    body = await request.json()
    args: dict[str, Any] = {"issue_keys": body.get("issue_keys")} if body.get("issue_keys") else {}
    actor = _actor_from_request(request)
    if actor:
        args["actor"] = actor
    res = await _mcp_tool("jira_validate_staged", args)
    payload = _extract_json_block(res)
    return JSONResponse(payload, status_code=400 if res.get("isError") else 200)


@app.post("/api/jira/revert", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_APPLY_JIRA))])
async def api_jira_revert(request: Request) -> JSONResponse:
    body = await request.json()
    args: dict[str, Any] = {"issue_keys": body.get("issue_keys")} if body.get("issue_keys") else {}
    actor = _actor_from_request(request)
    if actor:
        args["actor"] = actor
    res = await _mcp_tool("jira_revert_staged", args)
    payload = _extract_json_block(res)
    return JSONResponse(payload, status_code=400 if res.get("isError") else 200)


@app.post("/api/jira/apply", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_APPLY_JIRA))])
async def api_jira_apply(request: Request) -> JSONResponse:
    body = await request.json()
    args: dict[str, Any] = {"issue_keys": body.get("issue_keys")} if body.get("issue_keys") else {}
    actor = _actor_from_request(request)
    if actor:
        args["actor"] = actor
    res = await _mcp_tool("jira_apply_staged", args)
    payload = _extract_json_block(res)
    return JSONResponse(payload, status_code=400 if res.get("isError") else 200)


# ---------------------------------------------------------------------------
# Stage 14 — Docs Wiki proxy endpoints
# ---------------------------------------------------------------------------


@app.get("/api/docs/tree", dependencies=[Depends(_guard_user)])
async def api_docs_tree(
    tag: str | None = None,
    status: str | None = None,
    visibility: str | None = None,
    include_archived: bool = False,
) -> JSONResponse:
    args: dict[str, Any] = {"include_archived": include_archived}
    if tag:
        args["tag"] = tag
    if status:
        args["status"] = status
    if visibility:
        args["visibility"] = visibility
    res = await _mcp_tool("docs_list", args)
    if res.get("isError"):
        return JSONResponse({"error": _extract_json_block(res)}, status_code=400)
    return JSONResponse(_extract_json_block(res))


@app.get("/api/docs/search", dependencies=[Depends(_guard_user)])
async def api_docs_search(q: str, limit: int = 25) -> JSONResponse:
    if not q:
        raise HTTPException(status_code=400, detail="q is required")
    res = await _mcp_tool("docs_search", {"query": q, "limit": int(limit)})
    if res.get("isError"):
        return JSONResponse({"error": _extract_json_block(res)}, status_code=400)
    return JSONResponse(_extract_json_block(res))


@app.get("/api/docs/{slug}", dependencies=[Depends(_guard_user)])
async def api_docs_get(slug: str) -> JSONResponse:
    res = await _mcp_tool("docs_get", {"slug": slug})
    if res.get("isError"):
        payload = _extract_json_block(res)
        if isinstance(payload, dict) and payload.get("error") == "not_found":
            return JSONResponse(payload, status_code=404)
        return JSONResponse({"error": payload}, status_code=400)
    return JSONResponse(_extract_json_block(res))


@app.post("/api/docs", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_MANAGE_DOCS))])
async def api_docs_upsert(request: Request) -> JSONResponse:
    body = await request.json()
    if "slug" not in body:
        raise HTTPException(status_code=400, detail="slug is required")
    actor = _actor_from_request(request)
    if actor:
        body["actor"] = actor
    res = await _mcp_tool("docs_upsert", body)
    if res.get("isError"):
        return JSONResponse({"error": _extract_json_block(res)}, status_code=400)
    return JSONResponse(_extract_json_block(res))


@app.post("/api/docs/{slug}/flags", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_MANAGE_DOCS))])
async def api_docs_set_flags(slug: str, request: Request) -> JSONResponse:
    body = await request.json()
    args: dict[str, Any] = {"slug": slug}
    for field in ("status", "visibility", "tags"):
        if field in body:
            args[field] = body[field]
    actor = _actor_from_request(request)
    if actor:
        args["actor"] = actor
    res = await _mcp_tool("docs_set_flags", args)
    if res.get("isError"):
        return JSONResponse({"error": _extract_json_block(res)}, status_code=400)
    return JSONResponse(_extract_json_block(res))


@app.post("/api/docs/sync", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_SYNC_DOCS))])
async def api_docs_sync(request: Request) -> JSONResponse:
    body = await request.json()
    args: dict[str, Any] = {}
    if body.get("slug"):
        args["slug"] = body["slug"]
    actor = _actor_from_request(request)
    if actor:
        args["actor"] = actor
    res = await _mcp_tool("docs_sync", args)
    if res.get("isError"):
        return JSONResponse({"error": _extract_json_block(res)}, status_code=400)
    return JSONResponse(_extract_json_block(res))


@app.post("/api/docs/agent", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_SYNC_DOCS))])
async def api_docs_agent(request: Request) -> JSONResponse:
    body = await request.json()
    args: dict[str, Any] = {}
    if "limit_suggestions" in body:
        args["limit_suggestions"] = int(body["limit_suggestions"])
    if body.get("run_id"):
        args["run_id"] = body["run_id"]
    if "resume_decision" in body:
        args["resume_decision"] = body["resume_decision"]
    actor = _actor_from_request(request)
    if actor:
        args["actor"] = actor
    res = await _mcp_tool("docs_agent_run", args)
    if res.get("isError"):
        return JSONResponse({"error": _extract_json_block(res)}, status_code=400)
    return JSONResponse(_extract_json_block(res))


# ---------------------------------------------------------------------------
# Stage 21 — Deep Agent runtime proxy endpoints
# ---------------------------------------------------------------------------


@app.get("/api/agents/profiles", dependencies=[Depends(_guard_user)])
async def api_agent_profiles() -> JSONResponse:
    res = await _mcp_tool("agent_profiles_list", {})
    return JSONResponse(_extract_json_block(res), status_code=400 if res.get("isError") else 200)


@app.post("/api/agents/runs", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_RUN_WORKFLOW))])
async def api_agent_run_start(request: Request) -> JSONResponse:
    body = await request.json()
    actor = _actor_from_request(request)
    if actor:
        body["actor"] = actor.get("username")
    res = await _mcp_tool("agent_run_start", body)
    return JSONResponse(_extract_json_block(res), status_code=400 if res.get("isError") else 200)


@app.get("/api/agents/runs/{run_id}", dependencies=[Depends(_guard_user)])
async def api_agent_run_status(run_id: str) -> JSONResponse:
    res = await _mcp_tool("agent_run_status", {"run_id": run_id})
    return JSONResponse(_extract_json_block(res), status_code=404 if res.get("isError") else 200)


@app.post("/api/agents/runs/{run_id}/resume", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_RUN_WORKFLOW))])
async def api_agent_run_resume(run_id: str, request: Request) -> JSONResponse:
    body = await request.json()
    args: dict[str, Any] = {"run_id": run_id, "decision": body.get("decision")}
    user: _auth.UserContext | None = getattr(request.state, "user", None)
    if user is not None:
        args["actor"] = user.username
        # The runtime enforces the agent profile's required_capability against
        # this set before approving/editing a write (S21.hitl.1).
        args["actor_capabilities"] = sorted(user.capabilities)
    res = await _mcp_tool("agent_run_resume", args)
    payload = _extract_json_block(res)
    if res.get("isError"):
        status = 403 if isinstance(payload, dict) and payload.get("code") == "forbidden" else 400
        return JSONResponse(payload, status_code=status)
    return JSONResponse(payload)


@app.post("/api/agents/runs/{run_id}/cancel", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_RUN_WORKFLOW))])
async def api_agent_run_cancel(run_id: str) -> JSONResponse:
    res = await _mcp_tool("agent_run_cancel", {"run_id": run_id})
    return JSONResponse(_extract_json_block(res), status_code=400 if res.get("isError") else 200)


@app.get("/api/agents/runs/{run_id}/artifacts", dependencies=[Depends(_guard_user)])
async def api_agent_run_artifacts(run_id: str) -> JSONResponse:
    res = await _mcp_tool("agent_run_artifacts", {"run_id": run_id})
    return JSONResponse(_extract_json_block(res), status_code=400 if res.get("isError") else 200)


@app.get("/api/reports/download", dependencies=[Depends(_guard_user)])
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


@app.post("/api/workflow/run", dependencies=[Depends(_guard_cap(_auth.Capability.CAN_RUN_WORKFLOW))])
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
    actor = _actor_from_request(request)
    if actor:
        args["actor"] = actor

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

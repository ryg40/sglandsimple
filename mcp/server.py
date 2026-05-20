"""MCP server exposing summarize_text, chat, echo, web_research, and the
stage-1 mongo/ask_data tools.

Implements the subset of the Model Context Protocol needed for tools:
- initialize / initialized
- tools/list
- tools/call

Transport is JSON-RPC 2.0 over HTTP POST at /mcp. A simple GET at /mcp
returns an SSE stream that stays open for clients that expect one; this
server is stateless and does not push server-initiated messages.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

import db as dbmod
from ask_data import render_markdown as render_ask_data_markdown
from ask_data import run_ask_data
from web_research import render_markdown as render_web_research_markdown
from web_research import run_web_research


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} environment variable is required")
    return value


UPSTREAM_BASE_URL = _required_env("UPSTREAM_BASE_URL")
UPSTREAM_API_KEY = os.environ.get("UPSTREAM_API_KEY", "dummy")
UPSTREAM_MODEL = _required_env("UPSTREAM_MODEL")
REQUEST_TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "120"))

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "sglandsimple-mcp", "version": "0.2.0"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "summarize_text",
        "description": "Summarize the user-provided text into a short paragraph capturing the key points.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to summarize."},
                "max_words": {
                    "type": "integer",
                    "description": "Soft cap on summary length in words.",
                    "default": 80,
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "chat",
        "description": "Engage in a multi-turn conversation. Pass the running message history; receive the assistant's next reply.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "description": "OpenAI-style messages, each {role, content}.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string", "enum": ["system", "user", "assistant"]},
                            "content": {"type": "string"},
                        },
                        "required": ["role", "content"],
                    },
                },
                "system": {
                    "type": "string",
                    "description": "Optional system prompt prepended to the conversation.",
                },
            },
            "required": ["messages"],
        },
    },
    {
        "name": "echo",
        "description": "Diagnostic: return the input verbatim. Useful for confirming MCP wiring.",
        "inputSchema": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    },
    {
        "name": "web_research",
        "description": (
            "Research a topic on the web. Searches SearXNG for relevant results, "
            "annotates each in parallel, then produces a constrained-JSON synthesis "
            "with citations and a verbatim quote from the best result. Returns both "
            "Markdown and JSON renderings."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "The topic or question to research."},
                "k": {
                    "type": "integer",
                    "description": "Number of search results to consider (minimum 5).",
                    "default": 5,
                    "minimum": 5,
                },
            },
            "required": ["topic"],
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
                    "description": "Collection name. One of: employees, tickets, documents.",
                },
                "sample": {
                    "type": "integer",
                    "description": "Number of documents to sample for the schema (default 5).",
                    "default": 5,
                },
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
                "collection": {"type": "string", "enum": ["employees", "tickets", "documents"]},
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
                "collection": {"type": "string", "enum": ["employees", "tickets", "documents"]},
                "pipeline": {"type": "array", "items": {"type": "object"}},
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50},
            },
            "required": ["collection", "pipeline"],
        },
    },
    {
        "name": "ask_data",
        "description": (
            "Answer a natural-language question about the enterprise data by planning "
            "a Mongo query, executing it, and synthesising a cited answer. Returns "
            "markdown plus the structured JSON result."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to answer."},
            },
            "required": ["question"],
        },
    },
]


async def _upstream_chat(messages: list[dict[str, str]]) -> str:
    payload = {
        "model": UPSTREAM_MODEL,
        "messages": messages,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    headers = {"Authorization": f"Bearer {UPSTREAM_API_KEY}"}
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        r = await client.post(f"{UPSTREAM_BASE_URL}/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    return data["choices"][0]["message"]["content"]


async def _tool_summarize_text(args: dict[str, Any]) -> str:
    text = args["text"]
    max_words = int(args.get("max_words", 80))
    system = (
        "You are a concise summarizer. Produce a single paragraph capturing the key points "
        f"of the user's text in at most {max_words} words. Do not editorialize."
    )
    return await _upstream_chat(
        [{"role": "system", "content": system}, {"role": "user", "content": text}]
    )


async def _tool_chat(args: dict[str, Any]) -> str:
    messages = list(args["messages"])
    if (system := args.get("system")):
        messages = [{"role": "system", "content": system}, *messages]
    return await _upstream_chat(messages)


def _tool_echo(args: dict[str, Any]) -> str:
    return str(args.get("value", ""))


async def _tool_web_research(args: dict[str, Any]) -> list[dict[str, Any]]:
    topic = args["topic"]
    k = int(args.get("k", 5))
    payload = await run_web_research(topic, k=k)
    markdown = render_web_research_markdown(payload)
    return [
        {"type": "text", "text": markdown},
        {"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False, default=str)},
    ]


# ---------------------------------------------------------------------------
# Mongo / ask_data tools
# ---------------------------------------------------------------------------


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


async def _tool_mongo_list_collections(args: dict[str, Any]) -> list[dict[str, Any]]:
    rows = await dbmod.list_collections()
    md = "# Collections\n\n" + _markdown_table(rows)
    return [
        {"type": "text", "text": md},
        {"type": "text", "text": json.dumps({"collections": rows}, indent=2)},
    ]


async def _tool_mongo_describe_collection(args: dict[str, Any]) -> list[dict[str, Any]]:
    name = args["name"]
    sample = int(args.get("sample", 5))
    desc = await dbmod.describe_collection(name, sample=sample)
    lines = [f"# {desc['collection']} (sampled {desc['sample_size']})", ""]
    for fname, info in desc["fields"].items():
        lines.append(f"- **{fname}** _({'|'.join(info['types'])})_ e.g. `{info['example']}`")
    md = "\n".join(lines)
    return [
        {"type": "text", "text": md},
        {"type": "text", "text": json.dumps(desc, indent=2, default=str)},
    ]


async def _tool_mongo_query(args: dict[str, Any]) -> list[dict[str, Any]]:
    spec = {
        "collection": args["collection"],
        "kind": "find",
        "filter": args.get("filter") or {},
    }
    for k in ("projection", "sort", "limit", "skip"):
        if k in args and args[k] is not None:
            spec[k] = args[k]
    rows = await dbmod.find(spec)
    md = f"# mongo_query: {args['collection']}\n\n" + _markdown_table(rows)
    return [
        {"type": "text", "text": md},
        {"type": "text", "text": json.dumps({"rows": rows}, indent=2, default=str)},
    ]


async def _tool_mongo_aggregate(args: dict[str, Any]) -> list[dict[str, Any]]:
    spec = {
        "collection": args["collection"],
        "kind": "aggregate",
        "pipeline": args["pipeline"],
    }
    if "limit" in args and args["limit"] is not None:
        spec["limit"] = args["limit"]
    rows = await dbmod.aggregate(spec)
    md = f"# mongo_aggregate: {args['collection']}\n\n" + _markdown_table(rows)
    return [
        {"type": "text", "text": md},
        {"type": "text", "text": json.dumps({"rows": rows}, indent=2, default=str)},
    ]


async def _tool_ask_data(args: dict[str, Any]) -> dict[str, Any]:
    question = args["question"]
    state = await run_ask_data(question)
    if state.final is None:
        md = render_ask_data_markdown(None, spec_error=state.spec_error)
        return {
            "content": [
                {"type": "text", "text": md},
                {"type": "text", "text": json.dumps({"spec_error": state.spec_error}, indent=2)},
            ],
            "isError": True,
        }
    md = render_ask_data_markdown(state.final)
    payload = state.final.model_dump(exclude_none=True)
    return {
        "content": [
            {"type": "text", "text": md},
            {"type": "text", "text": json.dumps(payload, indent=2, default=str)},
        ],
        "isError": False,
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


async def _dispatch_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    # Tools returning a content list of multiple blocks.
    multi_content_tools = {
        "web_research": _tool_web_research,
        "mongo_list_collections": _tool_mongo_list_collections,
        "mongo_describe_collection": _tool_mongo_describe_collection,
        "mongo_query": _tool_mongo_query,
        "mongo_aggregate": _tool_mongo_aggregate,
    }
    if name in multi_content_tools:
        content = await multi_content_tools[name](args)
        return {"content": content, "isError": False}

    if name == "ask_data":
        return await _tool_ask_data(args)

    if name == "summarize_text":
        text = await _tool_summarize_text(args)
    elif name == "chat":
        text = await _tool_chat(args)
    elif name == "echo":
        text = _tool_echo(args)
    else:
        return {
            "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
            "isError": True,
        }
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _result(rpc_id: Any, value: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": value}


def _error(rpc_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


async def _handle_rpc(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method")
    rpc_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return _result(
            rpc_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": SERVER_INFO,
                "capabilities": {"tools": {"listChanged": False}},
            },
        )
    if method in ("notifications/initialized", "initialized"):
        return None  # notification, no response
    if method == "ping":
        return _result(rpc_id, {})
    if method == "tools/list":
        return _result(rpc_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            payload = await _dispatch_tool(name, args)
        except (dbmod.SpecError, dbmod.ExecError) as e:
            return _result(
                rpc_id,
                {"content": [{"type": "text", "text": f"[{type(e).__name__}] {e}"}], "isError": True},
            )
        except httpx.HTTPError as e:
            return _error(rpc_id, -32000, f"Upstream error: {e}")
        except Exception as e:  # noqa: BLE001
            import traceback
            tb = traceback.format_exc()
            print(f"[mcp tool error] name={name} args={args}\n{tb}", flush=True)
            return _error(rpc_id, -32000, f"Tool error: {type(e).__name__}: {e}")
        return _result(rpc_id, payload)

    if rpc_id is None:
        return None
    return _error(rpc_id, -32601, f"Method not found: {method}")


app = FastAPI(title="sglandsimple MCP server")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/mcp")
async def mcp_post(request: Request) -> Response:
    body = await request.body()
    try:
        msg = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse(_error(None, -32700, "Parse error"), status_code=400)

    if isinstance(msg, list):
        responses = [r for r in [await _handle_rpc(m) for m in msg] if r is not None]
        if not responses:
            return Response(status_code=202)
        return JSONResponse(responses)

    resp = await _handle_rpc(msg)
    if resp is None:
        return Response(status_code=202)
    return JSONResponse(resp)


@app.get("/mcp")
async def mcp_get() -> StreamingResponse:
    async def event_stream():
        # Stateless server: keep the SSE connection open with periodic comments.
        # Clients that don't need server-pushed messages can ignore this.
        import asyncio

        while True:
            yield ": keepalive\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(event_stream(), media_type="text/event-stream")

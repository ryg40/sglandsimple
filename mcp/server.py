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
import sandbox as sbx
from ask_data import render_markdown as render_ask_data_markdown
from ask_data import run_ask_data
from deep_agent import Plan, run_deep_agent, run_plan_task, run_run_plan
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
    {
        "name": "fs_read",
        "description": "Read a UTF-8 file from the sandbox (/sandbox). Paths must be relative; traversal is rejected.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to /sandbox."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "fs_write",
        "description": "Write/replace a UTF-8 file in the sandbox. Creates parent directories as needed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to /sandbox."},
                "content": {"type": "string", "description": "Full file contents."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "fs_edit",
        "description": "Exact-string replace in a sandbox file. old_string must be unique within the file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "shell_exec",
        "description": (
            "Run a bash command inside /sandbox as the non-root sandbox user. "
            "stdout/stderr are returned along with the exit code. Times out after "
            "timeout_sec seconds (default 30)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string", "description": "Command line passed to `bash -lc`."},
                "timeout_sec": {"type": "number", "description": "Hard timeout in seconds.", "default": 30},
            },
            "required": ["cmd"],
        },
    },
    {
        "name": "plan_task",
        "description": (
            "Planner subagent. Decomposes a goal into a typed Plan of MCP tool "
            "calls (with depends_on and parallel flags). Persists the plan to "
            "db.deep_agent_plans and returns it. Does not execute."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "The user goal to plan for."},
                "context": {"type": "string", "description": "Optional extra context.", "default": ""},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "run_plan",
        "description": (
            "Builder/executor subagent. Executes a previously-produced Plan "
            "(by plan_id) or an inline Plan, fanning out parallel-marked steps. "
            "Returns per-step results and a final natural-language summary."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "Plan id returned by plan_task."},
                "plan": {"type": "object", "description": "Inline Plan object (alternative to plan_id)."},
            },
        },
    },
    {
        "name": "deep_agent",
        "description": (
            "One-shot deep-agent: plan_task -> run_plan -> summary. Use this "
            "for goals that should be planned and executed in a single call."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "The goal to achieve."},
                "context": {"type": "string", "description": "Optional context.", "default": ""},
            },
            "required": ["goal"],
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


# ---------------------------------------------------------------------------
# Sandbox tools (stage 4)
# ---------------------------------------------------------------------------


async def _tool_fs_read(args: dict[str, Any]) -> list[dict[str, Any]]:
    text = sbx.fs_read(args["path"])
    return [{"type": "text", "text": text}]


async def _tool_fs_write(args: dict[str, Any]) -> list[dict[str, Any]]:
    info = sbx.fs_write(args["path"], args.get("content", ""))
    return [{"type": "text", "text": json.dumps(info, indent=2)}]


async def _tool_fs_edit(args: dict[str, Any]) -> list[dict[str, Any]]:
    info = sbx.fs_edit(args["path"], args["old_string"], args["new_string"])
    return [{"type": "text", "text": json.dumps(info, indent=2)}]


async def _tool_shell_exec(args: dict[str, Any]) -> list[dict[str, Any]]:
    result = await sbx.shell_exec(args["cmd"], timeout_sec=args.get("timeout_sec"))
    head = f"$ {result['cmd']}\nexit={result['exit_code']}{' (timed out)' if result['timed_out'] else ''}\n"
    body = ""
    if result["stdout"]:
        body += "--- stdout ---\n" + result["stdout"] + "\n"
    if result["stderr"]:
        body += "--- stderr ---\n" + result["stderr"] + "\n"
    return [
        {"type": "text", "text": head + body},
        {"type": "text", "text": json.dumps(result, indent=2)},
    ]


# ---------------------------------------------------------------------------
# Deep-agent tools (stage 4)
# ---------------------------------------------------------------------------


def _plan_markdown(plan: Plan) -> str:
    lines = [f"# Plan {plan.plan_id or '(new)'}", "", f"**Goal:** {plan.goal}", ""]
    if plan.rationale:
        lines += [plan.rationale, ""]
    lines.append("## Steps")
    for s in plan.steps:
        deps = ", ".join(s.depends_on) or "—"
        par = " · parallel" if s.parallel else ""
        lines.append(f"- **{s.id}** → `{s.tool}` (deps: {deps}){par}")
        if s.rationale:
            lines.append(f"  - {s.rationale}")
    return "\n".join(lines)


async def _tool_plan_task(args: dict[str, Any]) -> dict[str, Any]:
    goal = args.get("goal")
    if not goal:
        return {"content": [{"type": "text", "text": "goal is required"}], "isError": True}
    result = await run_plan_task(goal, context=args.get("context", "") or "")
    if "error" in result:
        return {
            "content": [{"type": "text", "text": f"[planner error] {result['error']}"}],
            "isError": True,
        }
    plan: Plan = result["plan"]
    return {
        "content": [
            {"type": "text", "text": _plan_markdown(plan)},
            {"type": "text", "text": plan.model_dump_json(indent=2)},
        ],
        "isError": False,
    }


async def _tool_run_plan(args: dict[str, Any]) -> dict[str, Any]:
    plan = None
    if args.get("plan"):
        try:
            plan = Plan.model_validate(args["plan"])
        except Exception as e:  # noqa: BLE001
            return {
                "content": [{"type": "text", "text": f"[plan validation error] {e}"}],
                "isError": True,
            }
    summary = await run_run_plan(plan=plan, plan_id=args.get("plan_id"))
    md_lines = [f"# Run of plan {summary.plan_id}", "", f"**Goal:** {summary.goal}", ""]
    if summary.replanned:
        md_lines.append("_(plan was re-planned once after a step failure)_")
    if summary.error:
        md_lines += ["", f"**Error:** {summary.error}"]
    md_lines.append("\n## Step results")
    for r in summary.results:
        if r.status == "ok":
            md_lines.append(f"- **{r.step_id}** ✓")
            if r.output:
                snippet = r.output if len(r.output) < 400 else r.output[:400] + "…"
                md_lines.append(f"  > {snippet}")
        else:
            md_lines.append(f"- **{r.step_id}** ✗ {r.error}")
    if summary.summary:
        md_lines += ["", "## Summary", summary.summary]
    return {
        "content": [
            {"type": "text", "text": "\n".join(md_lines)},
            {"type": "text", "text": summary.model_dump_json(indent=2)},
        ],
        "isError": bool(summary.error),
    }


async def _tool_deep_agent(args: dict[str, Any]) -> dict[str, Any]:
    goal = args.get("goal")
    if not goal:
        return {"content": [{"type": "text", "text": "goal is required"}], "isError": True}
    result = await run_deep_agent(goal, context=args.get("context", "") or "")
    if "error" in result:
        return {
            "content": [{"type": "text", "text": f"[deep_agent error] {result['error']}"}],
            "isError": True,
        }
    plan: Plan = result["plan"]
    summary = result["summary"]
    md = _plan_markdown(plan) + "\n\n"
    md += f"## Run\n\n"
    if summary.replanned:
        md += "_(plan was re-planned once after a step failure)_\n\n"
    for r in summary.results:
        if r.status == "ok":
            md += f"- **{r.step_id}** ✓\n"
        else:
            md += f"- **{r.step_id}** ✗ {r.error}\n"
    if summary.summary:
        md += f"\n## Summary\n\n{summary.summary}\n"
    payload = {"plan": plan.model_dump(), "summary": summary.model_dump()}
    return {
        "content": [
            {"type": "text", "text": md},
            {"type": "text", "text": json.dumps(payload, indent=2, default=str)},
        ],
        "isError": bool(summary.error),
    }


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
        "fs_read": _tool_fs_read,
        "fs_write": _tool_fs_write,
        "fs_edit": _tool_fs_edit,
        "shell_exec": _tool_shell_exec,
    }
    if name in multi_content_tools:
        try:
            content = await multi_content_tools[name](args)
        except sbx.SandboxError as e:
            return {"content": [{"type": "text", "text": f"[SandboxError] {e}"}], "isError": True}
        return {"content": content, "isError": False}

    if name == "ask_data":
        return await _tool_ask_data(args)
    if name == "plan_task":
        return await _tool_plan_task(args)
    if name == "run_plan":
        return await _tool_run_plan(args)
    if name == "deep_agent":
        return await _tool_deep_agent(args)

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


# ---------------------------------------------------------------------------
# Session + auth + rate limit (stage 3)
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402
import time as _time  # noqa: E402
import uuid  # noqa: E402

MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN") or ""
MCP_RATE_PER_MIN = int(os.environ.get("MCP_RATE_PER_MIN", "60"))
SESSION_TTL = float(os.environ.get("MCP_SESSION_TTL", "1800"))  # 30 min idle
SESSION_HEADER = "Mcp-Session-Id"


class _Session:
    __slots__ = ("id", "last_seen", "tokens", "last_refill")

    def __init__(self, sid: str):
        self.id = sid
        self.last_seen = _time.time()
        # Token-bucket: full to start, refills at MCP_RATE_PER_MIN per 60s.
        self.tokens = float(MCP_RATE_PER_MIN)
        self.last_refill = _time.time()


_sessions: dict[str, _Session] = {}
_sessions_lock = asyncio.Lock()


async def _gc_sessions() -> None:
    now = _time.time()
    stale = [sid for sid, s in _sessions.items() if now - s.last_seen > SESSION_TTL]
    for sid in stale:
        _sessions.pop(sid, None)


def _refill(sess: _Session) -> None:
    now = _time.time()
    elapsed = now - sess.last_refill
    sess.tokens = min(float(MCP_RATE_PER_MIN), sess.tokens + (MCP_RATE_PER_MIN * elapsed / 60.0))
    sess.last_refill = now


def _auth_ok(request: Request) -> bool:
    if not MCP_AUTH_TOKEN:
        return True
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    return auth[len("Bearer "):].strip() == MCP_AUTH_TOKEN


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        _error(None, -32001, "Unauthorized"),
        status_code=401,
        headers={"WWW-Authenticate": 'Bearer realm="mcp"'},
    )


def _too_many() -> JSONResponse:
    return JSONResponse(_error(None, -32002, "Rate limit exceeded"), status_code=429)


app = FastAPI(title="sglandsimple MCP server")


@app.on_event("startup")
async def _startup_log() -> None:
    if not MCP_AUTH_TOKEN:
        print(
            "[mcp] WARNING: MCP_AUTH_TOKEN is not set; /mcp is open. "
            "Set MCP_AUTH_TOKEN in .env.local to require bearer auth.",
            flush=True,
        )
    else:
        print(f"[mcp] bearer auth enabled (token length {len(MCP_AUTH_TOKEN)})", flush=True)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/mcp")
async def mcp_post(request: Request) -> Response:
    if not _auth_ok(request):
        return _unauthorized()

    body = await request.body()
    try:
        msg = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse(_error(None, -32700, "Parse error"), status_code=400)

    # initialize is the only method that may arrive without a session id —
    # the response carries a freshly-minted one.
    is_initialize = (
        isinstance(msg, dict) and msg.get("method") == "initialize"
    )
    incoming_sid = request.headers.get(SESSION_HEADER)
    response_headers: dict[str, str] = {}

    async with _sessions_lock:
        await _gc_sessions()
        if is_initialize:
            sid = incoming_sid or str(uuid.uuid4())
            sess = _sessions.setdefault(sid, _Session(sid))
            sess.last_seen = _time.time()
            response_headers[SESSION_HEADER] = sid
        else:
            if not incoming_sid:
                # Lenient mode: if no sessions exist yet, allow the first
                # non-initialize request (legacy clients, our own agent).
                if not _sessions:
                    sid = str(uuid.uuid4())
                    sess = _sessions.setdefault(sid, _Session(sid))
                    response_headers[SESSION_HEADER] = sid
                else:
                    return JSONResponse(
                        _error(None, -32003, f"Missing {SESSION_HEADER} header"),
                        status_code=400,
                    )
            else:
                sess = _sessions.get(incoming_sid)
                if sess is None:
                    return JSONResponse(
                        _error(None, -32004, "Unknown or expired session"),
                        status_code=400,
                    )
                sess.last_seen = _time.time()

        # Rate limit: one token per request (batched JSON-RPC = one token).
        _refill(sess)
        if sess.tokens < 1.0:
            return _too_many()
        sess.tokens -= 1.0

    if isinstance(msg, list):
        responses = [r for r in [await _handle_rpc(m) for m in msg] if r is not None]
        if not responses:
            return Response(status_code=202, headers=response_headers)
        return JSONResponse(responses, headers=response_headers)

    resp = await _handle_rpc(msg)
    if resp is None:
        return Response(status_code=202, headers=response_headers)
    return JSONResponse(resp, headers=response_headers)


@app.get("/mcp")
async def mcp_get(request: Request) -> Response:
    if not _auth_ok(request):
        return _unauthorized()

    async def event_stream():
        # Stateless server: keep the SSE connection open with periodic
        # comments. Clients that don't need server-pushed messages can
        # ignore this. Stage 3.2 would route per-session responses here.
        i = 0
        while True:
            i += 1
            yield f"id: {i}\nevent: ping\ndata: {{}}\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(event_stream(), media_type="text/event-stream")

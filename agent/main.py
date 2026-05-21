"""OpenAI-compatible agent endpoint.

Exposes /v1/chat/completions and /v1/models. Forwards chat completions to the
configured upstream (an OpenAI-compatible server, e.g. SGLang or vLLM), with
tools fetched from the MCP server merged into each request. When the upstream
returns tool_calls, the agent executes them against the MCP server and feeds
the results back into a follow-up completion, looping until the model returns
a final assistant message.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} environment variable is required")
    return value


UPSTREAM_BASE_URL = _required_env("UPSTREAM_BASE_URL").rstrip("/")
UPSTREAM_API_KEY = os.environ.get("UPSTREAM_API_KEY", "dummy")
UPSTREAM_MODEL = _required_env("UPSTREAM_MODEL")
UPSTREAM_MAX_TOKENS = int(os.environ.get("UPSTREAM_MAX_TOKENS", "0"))
MCP_URL = os.environ.get("MCP_URL", "http://mcp:8080/mcp")
REQUEST_TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "180"))
MAX_TOOL_ITERATIONS = int(os.environ.get("MAX_TOOL_ITERATIONS", "5"))

app = FastAPI(title="sglandsimple agent")


# ---------------------------------------------------------------------------
# MCP client (JSON-RPC over HTTP)
# ---------------------------------------------------------------------------

_rpc_id = 0


def _next_id() -> int:
    global _rpc_id
    _rpc_id += 1
    return _rpc_id


MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN") or ""
_mcp_session_id: str | None = None
_mcp_session_lock = None  # set in chat_completions when needed


def _mcp_headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if MCP_AUTH_TOKEN:
        h["Authorization"] = f"Bearer {MCP_AUTH_TOKEN}"
    if _mcp_session_id:
        h["Mcp-Session-Id"] = _mcp_session_id
    return h


async def _mcp_initialize(client: httpx.AsyncClient) -> None:
    """Open a session with the MCP server and stash the returned id."""
    global _mcp_session_id
    body = {
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
    }
    r = await client.post(MCP_URL, json=body, headers=_mcp_headers())
    r.raise_for_status()
    sid = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
    if sid:
        _mcp_session_id = sid


async def _mcp_call(client: httpx.AsyncClient, method: str, params: dict[str, Any] | None = None) -> Any:
    global _mcp_session_id
    if _mcp_session_id is None:
        await _mcp_initialize(client)
    body = {"jsonrpc": "2.0", "id": _next_id(), "method": method, "params": params or {}}
    r = await client.post(MCP_URL, json=body, headers=_mcp_headers())
    if r.status_code in (400, 404) and "session" in r.text.lower():
        # Session expired or invalidated — re-initialize once.
        _mcp_session_id = None
        await _mcp_initialize(client)
        r = await client.post(MCP_URL, json=body, headers=_mcp_headers())
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"MCP error from {method}: {data['error']}")
    return data.get("result")


async def _list_mcp_tools(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    result = await _mcp_call(client, "tools/list")
    tools = result.get("tools", []) if result else []
    # Convert MCP tool schema to OpenAI tools schema.
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


async def _call_mcp_tool(client: httpx.AsyncClient, name: str, arguments: dict[str, Any]) -> str:
    result = await _mcp_call(client, "tools/call", {"name": name, "arguments": arguments})
    if not result:
        return ""
    if result.get("isError"):
        parts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        return f"[tool error] {' '.join(parts)}"
    return "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")


# ---------------------------------------------------------------------------
# Upstream client
# ---------------------------------------------------------------------------


async def _upstream_chat(client: httpx.AsyncClient, payload: dict[str, Any]) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {UPSTREAM_API_KEY}"}
    r = await client.post(f"{UPSTREAM_BASE_URL}/chat/completions", json=payload, headers=headers)
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": UPSTREAM_MODEL,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "sglandsimple",
            }
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    if body.get("stream"):
        # Streaming not implemented in this simple agent; ask the caller to retry without stream.
        raise HTTPException(
            status_code=400,
            detail="Streaming is not supported by this agent. Send stream=false.",
        )

    messages: list[dict[str, Any]] = list(body.get("messages") or [])
    if not messages:
        raise HTTPException(status_code=400, detail="messages is required")

    # Force our upstream model regardless of what the client asked for, but echo
    # the client-supplied id back so OpenAI clients see a stable model name.
    client_model = body.get("model") or UPSTREAM_MODEL

    forward_keys = {
        "temperature",
        "top_p",
        "max_tokens",
        "presence_penalty",
        "frequency_penalty",
        "stop",
        "seed",
        "response_format",
        "tool_choice",
        "user",
        "chat_template_kwargs",
    }
    forwarded = {k: body[k] for k in forward_keys if k in body}

    # Qwen3 emits a long "reasoning" trace before the actual answer when
    # enable_thinking=True (default on the upstream). Tool-loop callers
    # almost never want that — it dramatically inflates latency. Default
    # to disabled, but let the caller override via chat_template_kwargs.
    forwarded.setdefault("chat_template_kwargs", {"enable_thinking": False})

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        # Merge MCP-provided tools with any tools the caller already supplied.
        try:
            mcp_tools = await _list_mcp_tools(client)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"MCP unavailable: {e}")
        caller_tools = list(body.get("tools") or [])
        seen = {t["function"]["name"] for t in caller_tools if t.get("type") == "function"}
        tools = caller_tools + [t for t in mcp_tools if t["function"]["name"] not in seen]

        for _ in range(MAX_TOOL_ITERATIONS):
            payload = {
                "model": UPSTREAM_MODEL,
                "messages": messages,
                **forwarded,
            }
            if UPSTREAM_MAX_TOKENS and "max_tokens" not in forwarded:
                payload["max_tokens"] = UPSTREAM_MAX_TOKENS
            if tools:
                payload["tools"] = tools
            resp = await _upstream_chat(client, payload)
            choice = resp["choices"][0]
            msg = choice["message"]
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                # Final answer — return upstream response, rewriting model id for the client.
                resp["model"] = client_model
                return JSONResponse(resp)

            # Record the assistant turn that requested tools, then dispatch each call.
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.get("content") or "",
                    "tool_calls": tool_calls,
                }
            )
            for call in tool_calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    args = {}
                try:
                    tool_result = await _call_mcp_tool(client, name, args)
                except Exception as e:  # noqa: BLE001
                    tool_result = f"[tool dispatch error] {e}"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                        "name": name,
                        "content": tool_result,
                    }
                )
            # Loop and let the model react to the tool outputs.

    raise HTTPException(
        status_code=502,
        detail=f"Exceeded MAX_TOOL_ITERATIONS={MAX_TOOL_ITERATIONS} without a final answer",
    )

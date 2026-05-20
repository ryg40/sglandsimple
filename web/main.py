"""Minimal web frontend for the sglandsimple stack.

Serves a single chat page and proxies two endpoints to the agent so the
browser never holds the upstream API key (even when it's `dummy`, this
is the prod pattern):

- GET  /              → templates/index.html
- POST /api/chat      → forward JSON body to ${AGENT_URL}/v1/chat/completions
- POST /api/ask_data  → wrap the user's question as an ask_data tool prompt
                        and dispatch through the agent's tool loop

No build step. Markdown rendering happens in the browser via `marked` and
`highlight.js` from a CDN.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

AGENT_URL = os.environ.get("AGENT_URL", "http://agent:8000").rstrip("/")
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "300"))

app = FastAPI(title="sglandsimple web")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


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

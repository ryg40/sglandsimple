# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Two-service docker-compose stack that fronts an existing OpenAI-compatible LLM server (SGLang/vLLM) with:

- `agent/` — FastAPI service exposing `/v1/chat/completions` (OpenAI-compatible). On every request it pulls the current tool list from the MCP server, merges it into the upstream call, and runs a tool-dispatch loop: when the upstream returns `tool_calls`, the agent invokes each one against MCP and feeds results back as `role: "tool"` messages until the model produces a final answer (capped by `MAX_TOOL_ITERATIONS`).
- `mcp/` — FastAPI MCP server speaking JSON-RPC 2.0 over HTTP POST at `/mcp` (plus a keepalive SSE stream on GET). Implements `initialize`, `tools/list`, `tools/call`. Tools: `summarize_text`/`chat` delegate to the upstream LLM; `echo` is a wiring diagnostic; `web_research` is an SGLang workflow (see below).
- `mcp/web_research.py` — SGLang frontend program. Search SearXNG → `sgl.fork` per result for parallel relevance notes → final constrained-JSON generation via `response_format` (json_schema, strict). Returns markdown + JSON.

Both services point at the *same* upstream (`UPSTREAM_BASE_URL`) — there is no local model runtime in this repo.

## Commands

```bash
cp .env.example .env
docker compose up --build -d
docker compose logs -f agent mcp
docker compose down
```

Smoke tests:

```bash
# MCP
curl -s localhost:8080/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Agent (OpenAI-compatible)
curl -s localhost:8000/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.6-27b","messages":[{"role":"user","content":"summarize: ..."}]}'
```

## Key design choices

- **Streaming is deliberately not implemented** in the agent — callers must send `stream: false`. Adding SSE would require restructuring the tool loop.
- **Tool loop runs server-side**, transparent to OpenAI clients. The model id the client sent is echoed back in the response even though the upstream model id (`UPSTREAM_MODEL`) is what's actually used.
- **MCP transport is bare JSON-RPC over HTTP**, not the full Streamable HTTP spec. Sufficient for `tools/list` + `tools/call`; the `GET /mcp` SSE endpoint exists only as a keepalive for clients that probe for one.
- Tool calls in MCP that hit the LLM (`summarize_text`, `chat`, `web_research`) go to the upstream directly — they do **not** loop back through the agent, which would risk recursion.
- **SGLang against a remote endpoint**: the `sgl.OpenAI(model)` backend is configured at import time using `OPENAI_BASE_URL` / `OPENAI_API_KEY` env vars (set from `UPSTREAM_*`). `sgl.function` programs run synchronously, so the MCP tool wraps them with `asyncio.to_thread`. Constrained JSON is done via the OpenAI client's `response_format=json_schema` rather than the DSL because that's the path SGLang/vLLM actually enforces on the server side.
- **Compose networks**: both services join the external `proxy` bridge network alongside the per-stack default network. This is how they reach `UPSTREAM_BASE_URL` and `SEARXNG_URL` which live on the LAN. Create it once with `docker network create proxy` if missing.

## Configuration

All via env vars (see `.env.example`): `UPSTREAM_BASE_URL`, `UPSTREAM_API_KEY`, `UPSTREAM_MODEL`, `AGENT_PORT`, `MCP_PORT`. Inside the compose network the agent reaches MCP via `MCP_URL=http://mcp:8080/mcp`.

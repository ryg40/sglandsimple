# MCP in this stack

This repo uses MCP as the **server-side tool bus** between the web/API surfaces and the workflow code in `mcp/`.

## What is actually running

- `agent/` exposes an OpenAI-compatible `/v1/chat/completions` API.
- `mcp/` exposes JSON-RPC 2.0 over HTTP at `POST /mcp` plus an SSE stream at `GET /mcp`.
- `web/` talks to FastAPI proxy routes such as `/api/docs/*`; those proxies then call MCP tools.

So the browser usually does **not** talk to MCP directly, but IDE clients can.

## The core MCP handshake

1. `initialize`
   - Response header: `Mcp-Session-Id`
2. `tools/list`
   - Discover the current tool catalog
3. `tools/call`
   - Invoke one tool with JSON arguments
4. Optional `GET /mcp`
   - Receive `ready`, `ping`, and mirrored `message` events for the same session

Exact transport join key: every request after `initialize` must reuse the same **`Mcp-Session-Id`** header.

See `docs/clients.md` for paste-ready client configs.

## Why MCP matters here

MCP keeps the workflow boundary stable:

- the web UI can call `docs_sync`, `docs_agent_run`, `ask_data`, `sheet_get`, `overview_summary`, etc.
- the agent service can expose those same capabilities through OpenAI tool calls
- an external MCP client can inspect or call the same tools without importing app code

## Worked example: Confluence live-enable path

Stage 23's Confluence work is a good example because it touches transport, workflow gating, and persistence.

### Current flow

1. A caller invokes the docs sync path (`docs_sync` via web proxy or direct MCP).
2. `mcp/docs_sync.py` walks wiki docs from the `docs` collection.
3. Each doc may already carry `docs.confluence_page_id`.
4. Sync actions are logged to `doc_sync_log`.

Exact persistence joins:

- `doc_revisions.doc_id -> docs._id`
- `doc_sync_log.doc_id -> docs._id`
- `docs.confluence_page_id -> Confluence page id`

### Stage 23 target live flow

When the live Confluence connector work lands, the call chain should be:

`tools/call(name="docs_sync") -> mcp/docs_sync.py -> ConfluenceConnector -> Atlassian MCP -> Confluence page`

The worked example keys are:

- `docs.path` maps the wiki tree to Confluence page hierarchy
- `docs.confluence_page_id` keeps updates idempotent
- `matched_on.ticket_refs[]` on Confluence sample pages lines up with `epics.jira_key` or `work_items.jira_key`

### Expected gates

The intended Stage 23 live gates are:

- `CONN_CONFLUENCE_ENABLED`
- `WORKFLOW_WRITES_ENABLED`
- `CONFLUENCE_WRITES_ENABLED`

Credential surface to teach:

- `CONFLUENCE_MCP_URL`
- `CONFLUENCE_TOKEN` as the Stage 23 primary credential
- `CONFLUENCE_MCP_TOKEN` as fallback/legacy alias

When those gates are off, the sync path should stay dry-run and still produce a useful plan.

### Hub status behavior

The `/hub` Confluence card uses `connector_health` for live Atlassian MCP status and `connector_summary` for seeded proof data. If `CONN_CONFLUENCE_ENABLED`, `CONFLUENCE_MCP_URL`, or a Confluence token are missing, health is `disabled`/`degraded`, but the Confluence connector can still publish canonical dry-run pages for the overlap-chain demo. The hub should therefore label those as dry-run pages, not as a total lack of Confluence evidence.

## How to explain MCP to a teammate

Use this short version:

- **OpenAI clients** talk to `agent/`.
- **Direct tool clients** talk to `mcp/`.
- **Both end up at the same MCP tools and LangGraph workflows.**

That is the architectural reason the repo can support a web app, Ask Data, Docs Wiki, and external IDE agents without duplicating workflow logic.

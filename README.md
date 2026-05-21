# sglandsimple

A small docker-compose stack that puts an OpenAI-compatible **agent endpoint** in front of an existing SGLang/vLLM server, and exposes the same tools over an **MCP server**.

```
client ──► agent (/v1/chat/completions)  ──►  upstream LLM (your SGLang/vLLM)
                │
                └──► mcp (tools/list, tools/call)
                          ├── summarize_text
                          ├── chat
                          ├── echo
                          └── web_research  ──► SearXNG  +  SGLang workflow
```

The agent fetches tools from the MCP server, advertises them on every chat completion, and auto-executes any tool calls the model emits against MCP — so a plain OpenAI client gets tool use "for free."

## Quick start

```bash
cp .env.example .env.local  # then edit UPSTREAM_BASE_URL / UPSTREAM_MODEL / SEARXNG_URL
docker compose up --build -d
```

`.env.local` is gitignored. The required vars (`UPSTREAM_BASE_URL`, `UPSTREAM_MODEL`, `SEARXNG_URL`) have no defaults — compose will refuse to start if they're unset.

Services:

- **Agent (OpenAI-compatible)** — public via Caddy at `https://${PUBLIC_HOSTNAME}/v1`, internal host bind on `:${AGENT_PORT}` (default `5450`).
- **MCP server (JSON-RPC over HTTP)** — LAN-only on `:${MCP_PORT}` (default `5451`). Not exposed publicly until Stage 3 hardening.

### Putting Caddy in front

Two ways, pick whichever your Caddy uses:

1. **caddy-docker-proxy**: the `agent` service already carries `caddy` labels that publish `${PUBLIC_HOSTNAME}` → `agent:8000`. No further action.
2. **Static Caddyfile**: copy `caddy/Caddyfile.snippet.example` to `caddy/Caddyfile.snippet.local`, replace the placeholder hostname, then paste/`import` it into your Caddyfile. The `.local` copy is gitignored. Your Caddy container must be on the external `proxy` network so it can resolve `sglandsimple-agent` by name.

## Using the agent

```bash
curl https://${PUBLIC_HOSTNAME}/v1/chat/completions \
  -H "Authorization: Bearer dummy" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "your-model-id",
    "messages": [
      {"role": "user", "content": "Please summarize: the quick brown fox jumps over the lazy dog, repeatedly, for many years."}
    ]
  }'
```

Or against the host directly (bypassing Caddy): `http://<host>:${AGENT_PORT}/v1/...`.

The model will see `summarize_text`, `chat`, and `echo` as available tools and call them as appropriate; the agent dispatches each call to the MCP server and feeds results back until the model returns a final answer.

Drop-in client config:

```json
{
  "baseUrl": "https://<your PUBLIC_HOSTNAME>/v1",
  "api": "openai-completions",
  "apiKey": "dummy",
  "models": [{ "id": "<your UPSTREAM_MODEL>", "name": "<your UPSTREAM_MODEL>" }]
}
```

> Streaming (`stream: true`) is intentionally not implemented — keep it simple. Send `stream: false`.

## web_research workflow (SGLang)

`mcp/web_research.py` is a deliberately small SGLang program meant as a learning artifact:

1. **Search** — `searxng_search` hits the existing SearXNG instance at `SEARXNG_URL` and collects ≥5 deduplicated results (title, url, snippet).
2. **Annotate (parallel fork)** — an `@sgl.function` opens N child states with `s.fork(len(hits))` and runs a one-sentence relevance prompt per result concurrently. Against SGLang's native runtime this leverages shared-prefix RadixAttention; against a remote OpenAI endpoint it degrades to N concurrent HTTP calls — same DSL, different speedup.
3. **Synthesize (constrained JSON)** — a final call uses `response_format={"type": "json_schema", "json_schema": {...}}` to force the model to emit an object with `topic`, `summary` (with `[n]`-style citation markers), `best_result` (index, url, **verbatim quote**, why), and `citations[]`. This is the real win you get from SGLang/vLLM whether or not you use the Python DSL.
4. **Render** — the MCP tool returns two content blocks: a Markdown rendering and the raw JSON.

Call it:

```bash
curl -s localhost:8080/mcp \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0","id":9,"method":"tools/call",
    "params":{"name":"web_research","arguments":{"topic":"recent advances in RadixAttention","k":6}}
  }' | jq -r '.result.content[0].text'   # markdown
```

Switch `.content[0]` to `.content[1]` for the JSON payload. The tool is also auto-exposed through the agent, so an OpenAI client can simply ask the model to "research X" and the agent will dispatch it.

## Using the MCP server directly

List tools:

```bash
curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq
```

Call a tool:

```bash
curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0","id":2,"method":"tools/call",
    "params":{"name":"summarize_text","arguments":{"text":"long input here..."}}
  }' | jq
```

## Configuration

All knobs are env vars (see `.env.example`); set them in `.env.local`:

| Var | Required? | Purpose |
| --- | --- | --- |
| `UPSTREAM_BASE_URL` | yes | OpenAI-compatible upstream |
| `UPSTREAM_API_KEY` | no (default `dummy`) | Bearer token for upstream |
| `UPSTREAM_MODEL` | yes | Model id to send upstream |
| `SEARXNG_URL` | yes | SearXNG used by `web_research` |
| `AGENT_PORT` | no (default `8000`) | Host port for agent |
| `MCP_PORT` | no (default `8080`) | Host port for MCP server |

Both services attach to the external Docker network `proxy` so they can reach the upstream LLM and SearXNG hosts on the LAN; create it once with `docker network create proxy` if it doesn't already exist.

## Layout

```
agent/   FastAPI service — /v1/chat/completions, MCP-aware tool loop
mcp/     FastAPI MCP server — JSON-RPC at /mcp, tools backed by the upstream LLM
web/     React + shadcn/ui SPA (admin dashboard) served by FastAPI
```

## Compliance workflow hub (Stage 9)

The dashboard's purpose is to let a person open one screen and **relate every
piece of a database-audit-logging compliance workflow** — the originating audit
finding, the Jira epic/stories, the coding work and PR, the Confluence docs, and
the real DB audit logs that prove the control — across many connected systems,
and export it all as a layman-friendly PDF/PPT artifact.

> Full spec, data model, and task breakdown live in `IMPLEMENT.md` (Stage 9).
> The diagrams below are the target design.

### Dashboard mockup

Top row is a grid of **connection "bubbles"** (one per integrated system, each
showing health + a summary metric). Below it, a **workflow lane** walks a
selected audit finding through every step, and a **"relate everything"** panel
pulls all associated records together.

```
┌──────────────┬───────────────────────────────────────────────────────────────────────┐
│  sglandsimple│  Overview · Compliance Workflow Hub                 [⌘K search]  [◐ theme]│
│              ├───────────────────────────────────────────────────────────────────────┤
│ ▸ Overview   │  CONNECTIONS                                                            │
│              │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐                        │
│ TOOLS        │  │● Jira   │ │● Conflu.│ │● GitHub │ │● AWS    │   ● healthy            │
│ ▸ Chat       │  │ 4 epics │ │ 12 pages│ │ 3 PRs   │ │ RDS x18 │   ◍ degraded          │
│ ▸ Sheet      │  │ 2m ago  │ │ 5m ago  │ │ 1m ago  │ │ 9m ago  │   ○ not connected     │
│ ▸ Wrangler   │  └─────────┘ └─────────┘ └─────────┘ └─────────┘   ◌ placeholder        │
│ ▸ Workflow   │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐                        │
│              │  │○ Service│ │● Snowfl.│ │● MongoDB│ │◌ Archer │                        │
│              │  │  Now    │ │ logs:9M │ │ system  │ │ (RIMS)  │                        │
│ ┌──────────┐ │  │  CR/CHG │ │ 3s ago  │ │ of rec. │ │ mock    │                        │
│ │● Connected│ │  └─────────┘ └─────────┘ └─────────┘ └─────────┘                        │
│ │ 87 records│ ├───────────────────────────────────────────────────────────────────────┤
│ └──────────┘ │  WORKFLOW · finding F-2041 "RDS audit logging"   epic RDS-LOG  [PDF][PPT]│
│              │  ①Finding→②Epic→③Jira ticket→④Branch/Agent→⑤PR+CI→⑥Confluence→⑦Logs    │
│              │  ●──────────●──────────●──────────●──────────◍──────────○──────────○     │
│              │  ┌─ relate everything ────────────────────────────────────────────────┐ │
│              │  │ finding F-2041  ·  epic RDS-LOG  ·  story RDS-LOG-7  ·  PR #128 ◍CI │ │
│              │  │ reviewers: copilot + 2  ·  Confluence: Epic Log §RDS  ·  12 log     │ │
│              │  │ samples (login / sql_error / sql_query) from the Mongo warehouse    │ │
│              │  └────────────────────────────────────────────────────────────────────┘ │
└──────────────┴───────────────────────────────────────────────────────────────────────┘
```

### Data flow — apps · MCPs · agents

How the pieces interconnect. Everything external is reached **server-side** from
the MCP layer (as an MCP client, a REST adapter, or SQL `tool_calls`); the
browser only talks to the web service, and the agent drives the same tools.

```mermaid
flowchart LR
  user([User / browser])
  subgraph edge[Edge]
    caddy[Caddy reverse proxy]
  end
  user --> caddy

  subgraph stack[sglandsimple stack]
    web[web SPA + FastAPI proxy]
    agent[agent · /v1/chat/completions · tool loop]
    mcp[mcp · JSON-RPC tools + connector registry]
    mongo[(MongoDB · system of record + log warehouse)]
    orch[workflow orchestrator · LangGraph + approvals]
  end

  caddy --> web
  caddy --> agent
  web -->|/api proxy| agent
  web -->|/api proxy| mcp
  agent -->|tools/list · tools/call| mcp
  agent --> llm[(Upstream LLM · SGLang/vLLM)]
  mcp --> llm
  mcp <--> mongo
  mcp --> orch
  orch <--> mongo

  subgraph conns[Connectors  · enabled per-flag, mock-first]
    jira[[Atlassian Jira · MCP]]
    conf[[Confluence · MCP]]
    gh[[GitHub · MCP]]
    aws[[AWS · MCP]]
    snow[[ServiceNow · REST]]
    sf[[Snowflake · SQL tool_calls]]
    archer[[Archer RIMS · placeholder]]
  end

  mcp <--> jira
  mcp <--> conf
  mcp <--> gh
  mcp <--> aws
  mcp <--> snow
  mcp <--> sf
  mcp <--> archer

  subgraph report[Reporting]
    pdf[report_pdf / report_ppt]
  end
  orch --> pdf
  mcp --> pdf
  pdf --> user

  coding[Coding agent] -->|branch + PR for Jira key| gh
  orch -->|create ticket| jira
  orch -->|epic log| conf
  archer -.->|audit findings| orch
  snow -.->|findings / change records| orch
  sf -.->|cloud DB audit logs| mongo
```


# IMPLEMENT.md — sglandsimple enterprise rollout (LangGraph edition)

This document is the implementation plan for evolving the current stack into an enterprise-shaped pattern: **server-side LangGraph agent workflows over a NoSQL store, fronted by both a web UI and direct MCP access from IDE/agent clients (opencode, VS Code Chat, PiAgent).**

> The repo name `sglandsimple` predates the framework choice. Despite the name, **this plan uses LangGraph**, not SGLang. The earlier `web_research.py` (built with the SGLang DSL) has been rewritten as a LangGraph graph.

## How to use this document

The narrative sections describe the *shape* of each stage. The **Task checklist** at the bottom is the executable plan: granular, dependency-ordered units of work, each one small enough to pick up cold and finish without re-reading the entire doc.

Convention:

- Tasks are `S<stage>.<group>.<n>`. Example: `S1.db.3 — Write validate_spec`.
- Check a task off (`[x]`) when **all** of its "Done when" bullets are satisfied. A task that is partially done stays `[ ]`.
- A task lists explicit **Files**, **Done when**, and **Depends on** so it can run in isolation. If a task has no `Depends on`, it can start immediately.
- When a task creates new env vars, ports, or compose services, update the **Env surface** table in the same change.

## Ground rules

- **Model runtime: external, fixed.** Every LLM call goes to an upstream OpenAI-compatible endpoint. The endpoint URL, API key, and model id all live in `.env.local` (gitignored) and are injected via `${UPSTREAM_*:?required}` references in `compose.yaml`. No values are hardcoded in committed files.
- **All graph code is server-side.** It lives in the MCP service container. Clients (web UI, OpenAI-API consumers, MCP clients) never import LangGraph; they call MCP tools or `/v1/chat/completions` and get final results.
- **Each stage lands as a usable system.** Don't move to stage N+1 until stage N is verified end-to-end.
- **External Docker network `proxy`** is used so the stack's containers can be reached by an existing Caddy reverse proxy and so they can reach LAN services (upstream LLM, SearXNG).
- **Public surface = agent only.** `PUBLIC_HOSTNAME` (set in `.env.local`) is fronted by Caddy and points at the agent's OpenAI-compatible endpoint. MCP stays LAN-only until stage 3 hardens its transport and auth.
- **Host port block: 5450, 5451, 5452, 5453, ...** — contiguous starting at 5450, one per service in stage order (agent → mcp → web → future). Stored as `AGENT_PORT`/`MCP_PORT`/`WEB_PORT` in `.env.local`.
- **Compose file name is `compose.yaml`** (one of compose's canonical names) so Dockge auto-discovers the stack.

## Why LangGraph here

For a stack whose LLM runtime is a remote OpenAI-compatible endpoint, LangGraph buys things that matter for enterprise patterns:

- **Explicit graph of nodes + edges**, including conditional routing — auditable workflow shape.
- **`StateGraph` typed state** (`TypedDict`/Pydantic) — every node is a pure function `state -> state_update`.
- **Native parallel fan-out** via `Send(...)` — one node produces N work items, each runs concurrently, results reduce back into shared state.
- **Checkpointing** to durable storage (Mongo) — every step persisted, runs resumable, observable, and replayable.
- **Human-in-the-loop interrupts** (`interrupt()`) — drop a graph into pending state, surface the question, resume later. The frontend and MCP-resumability stages get this for free.
- **Tool nodes / ToolNode** that integrate with the upstream model's tool-calling — same OpenAI-tools shape we already use in `agent/main.py`.

## Current state (baseline)

```
agent/                       FastAPI, /v1/chat/completions, server-side tool loop calling MCP
mcp/                         FastAPI, JSON-RPC at /mcp, tools: summarize_text, chat, echo, web_research
                             (web_research rewritten as LangGraph — SGLang dependency removed)
caddy/Caddyfile.snippet.example   static-Caddyfile template (the .local copy is gitignored)
compose.yaml                 Dockge-discoverable; services: mongo, mcp, agent, web; all on `proxy` network
.env.local                   gitignored runtime values (UPSTREAM_*, SEARXNG_URL, PUBLIC_HOSTNAME, ports)
.env.example                 sanitized template
```

Caddy fronts `${PUBLIC_HOSTNAME} → agent:8000`. Two ways wired:

1. **caddy-docker-proxy**: the `agent` service in `compose.yaml` carries `caddy` and `caddy.reverse_proxy` labels referencing `${PUBLIC_HOSTNAME}`.
2. **Static Caddyfile**: copy `caddy/Caddyfile.snippet.example` → `caddy/Caddyfile.snippet.local`, replace the placeholder hostname, then `import` into your real Caddyfile.

What we keep from baseline:

- `agent/main.py`'s OpenAI-compatible front door and MCP tool dispatch loop. Unchanged.
- `mcp/server.py`'s JSON-RPC transport, `tools/list`/`tools/call` handling, healthcheck. Extended with session/auth in stage 3.
- The pattern of returning two MCP content blocks per workflow: a Markdown rendering + the raw JSON.

What changed from baseline:

- The SGLang dependency and `mcp/web_research.py`'s `@sgl.function` + `sgl.fork` code → LangGraph `StateGraph` (stage 1, done).
- All workflow code is now LangGraph (`ask_data.py`, `web_research.py`).

## Stage 1 — MongoDB + LangGraph `ask_data` workflow

**Goal:** A server-side LangGraph workflow that turns a natural-language question into a constrained-JSON Mongo query, executes it, and returns a cited answer in both markdown and JSON.

### 1a. Dependencies

`mcp/requirements.txt` pins LangGraph + related packages. `sglang[openai]` removed.

### 1b. Compose changes

`mongo` service added (Mongo 7, persistent volume, healthcheck). `mcp` depends on `mongo` and receives `MONGO_URL`/`MONGO_DB`.

### 1c. Seed data

`mongo-seed/` contains:
- `00-users.js` — creates `app` user with `readWrite` on `enterprise` (readWrite so the LangGraph checkpointer can persist; application-level read-only enforcement lives in `db.py`).
- `01-employees.js` — ~30 employee docs.
- `02-tickets.js` — ~40 ticket docs.
- `03-documents.js` — ~20 document docs.

### 1d. `mcp/db.py`

Wraps `motor`:
- Singleton client, lazy on first call.
- `list_collections()`, `describe_collection()` with 60s TTL cache.
- `find()`, `aggregate()` — always call `validate_spec()` first, stringify ObjectIds for JSON safety.
- `validate_spec()` — allowlist collections, forbid `$where`/`$function`/`$accumulator`/`$out`/`$merge`, reject `{}` pipeline stages (must contain exactly one field per stage).

### 1e. `mcp/llm.py`

- `chat_model()` → configured `ChatOpenAI`.
- `structured(schema, system, user)` → constrained JSON via OpenAI `response_format={"type":"json_schema","strict":true}` with `json_object` fallback and best-effort fence extraction. Includes a 120s client timeout (`LLM_TIMEOUT` env).

### 1f. `mcp/checkpointer.py`

`asynccontextmanager` wrapping `AsyncMongoDBSaver`. Checkpoint collection name is `LANGGRAPH_CHECKPOINT_COLLECTION` (default `lg_checkpoints`).

### 1g. The `ask_data` graph (`mcp/ask_data.py`)

State (Pydantic): `AskDataState` with `question`, `catalog`, `spec`, `spec_error`, `retry_count`, `docs`, `per_doc_notes` (reduced via `operator.add`), `final`.

Nodes: `discover_schema` → `plan_query` → `execute_query` → conditional edge → (`plan_query` retry once, or `fan_out_notes` → parallel `interpret_doc` → `synthesize` → END, or fail closed).

Compiled with the Mongo checkpointer. Each invocation passes a fresh `thread_id = uuid4()`.

### 1h. New MCP tools

- `mongo_list_collections`
- `mongo_describe_collection`
- `mongo_query`
- `mongo_aggregate`
- `ask_data`

### 1i. `web_research` rewritten as LangGraph

`mcp/web_research.py` is a `StateGraph` with `search → fan_out_annotate → annotate_one (parallel via Send) → synthesize (structured) → END`. Same output schema (markdown + JSON). No `sglang` dependency.

### 1j. Safety rails

- Read-only enforced by `validate_spec` (no `$out`, `$merge`, `$set`, insert/delete).
- Hard `limit` ceiling at driver layer regardless of model output.
- One retry pass on validation/exec error; then fail closed (`isError=true`).
- LLM calls capped by `LLM_CONCURRENCY` semaphore (default 2) to avoid overrunning upstream `--max-num-seqs`.

### 1k. Verification (all done)

1. `docker compose up --build -d` starts all 4 services.
2. `tools/list` shows 9 tools (4 original + 5 new).
3. `mongo_describe_collection` returns sampled schema for `employees`.
4. `ask_data` passes three-shape smoke test: lookup, aggregation, tag search.
5. Agent endpoint dispatches model-emitted `ask_data` tool calls end-to-end.
6. `db.lg_checkpoints.estimatedDocumentCount()` > 0.

## Stage 2 — Web frontend

**Goal:** A minimal SPA-style page so non-IDE users can drive `ask_data` without curl.

### Compose changes

Added `web` service (FastAPI, Jinja + vanilla JS, no build step). Exposes `${WEB_PORT:-5452}:3000`.

### Implementation

- `GET /` → `templates/index.html`
- `POST /api/chat` → proxies to `agent:8000/v1/chat/completions`
- `POST /api/ask_data` → chat completion with `tool_choice=ask_data`, returns the agent's final assistant message
- Browser rendering via `marked` and `highlight.js` (CDN)

### Verification (done)

- `http://<host>:${WEB_PORT}` loads and renders chat UI with markdown + code highlighting.
- "Ask data" button explicitly triggers the tool path.

## Stage 3 — MCP server hardening for external clients

**Goal:** Make `mcp:8080/mcp` directly consumable by opencode, VS Code Chat, PiAgent, etc.

### Transport

- `POST /mcp` for client→server messages (done).
- Session via `Mcp-Session-Id` returned on `initialize`, required on subsequent POSTs (done).
- `GET /mcp` returns SSE keepalive stream with proper `event:`/`data:`/`id:` framing (done). **Full server-push routing of POST responses through SSE is deferred** (not needed for current clients; the synchronous POST response works fine).

### Auth

- `MCP_AUTH_TOKEN` — if set, requires `Authorization: Bearer <token>`. If unset, logs a startup warning (done).
- Per-session token-bucket rate limiting (`MCP_RATE_PER_MIN`, default 60) — done.

### Capability advertisement

- `initialize` returns correct `protocolVersion`, `serverInfo`, `capabilities.tools.listChanged=false` (done).
- `tools/list` already correct.

### Client config snippets

`docs/clients.md` has paste-ready blocks for opencode, VS Code Chat, PiAgent, and a curl quick-test. Notes that the `GET /mcp` SSE currently emits only keepalives.

### MCP public surface

**Decision:** Keep MCP LAN-only (option c) for now. Rationale: the agent's OpenAI-compatible endpoint at `${PUBLIC_HOSTNAME}` already exposes the MCP tool suite to external clients. IDE clients (opencode, VS Code Chat) can reach `mcp:8080/mcp` directly via host port `${MCP_PORT}` (or VPN tunnel). Public Caddy routing for MCP is deferred until an external client needs it and SSE server-push transport (S3.transport.2) is fully implemented.

### Verification

- Session ID handshake works (initialize → list tools with session header).
- Invalid/expired session returns 400.
- Rate limit kicks in after sustained burst.
- opencode/VS Code Chat config blocks from `docs/clients.md` succeed when pointed at `http://<host>:${MCP_PORT}/mcp`.

## Out of scope (for now)

- Multi-tenant auth (per-user Mongo namespaces).
- Write operations against Mongo (`$set`, `insert`, `delete`).
- Streaming responses from the agent (`stream: true`). Still 400s.
- Observability (OTel, structured logs to a collector).
- Vector search / semantic retrieval.
- SSE server-push of POST responses (deferred in S3.transport.2).
- Public Caddy routing for MCP (deferred in S3.expose.2).

## Env surface after all stages

All values live in `.env.local` (gitignored). `compose.yaml` uses `${VAR:?required}` for the required ones.

| Var | Default | Required | Stage | Notes |
| --- | --- | --- | --- | --- |
| `UPSTREAM_BASE_URL` | — | yes | 0 | OpenAI-compatible LLM endpoint |
| `UPSTREAM_API_KEY` | `dummy` | no | 0 |  |
| `UPSTREAM_MODEL` | — | yes | 0 | model id sent upstream |
| `SEARXNG_URL` | — | yes | 0 | SearXNG used by `web_research` |
| `PUBLIC_HOSTNAME` | — | yes | 0 | hostname Caddy fronts |
| `AGENT_PORT` | `5450` | no | 0 | host bind for agent |
| `MCP_PORT` | `5451` | no | 0 | host bind for mcp (LAN-only) |
| `MONGO_URL` | `mongodb://app:app@mongo:27017` | no | 1 | connection string |
| `MONGO_DB` | `enterprise` | no | 1 |  |
| `ASK_DATA_MAX_DOCS` | `10` | no | 1 | cap on per-doc fan-out |
| `ASK_DATA_LIMIT_CEILING` | `50` | no | 1 | hard limit on query results |
| `LANGGRAPH_CHECKPOINT_COLLECTION` | `lg_checkpoints` | no | 1 |  |
| `LLM_TIMEOUT` | `120` | no | 1 | per-LLM-call timeout in seconds |
| `LLM_CONCURRENCY` | `2` | no | 1 | semaphore cap for parallel LLM calls |
| `WEB_PORT` | `5452` | no | 2 | host bind for web frontend |
| `MCP_AUTH_TOKEN` | (unset → open) | no | 3 | bearer token for MCP |
| `MCP_RATE_PER_MIN` | `60` | no | 3 | per-session rate limit |
| `PLANNER_BASE_URL` | `${UPSTREAM_BASE_URL}` | no | 4 | planner LLM endpoint |
| `PLANNER_MODEL` | `${UPSTREAM_MODEL}` | no | 4 | planner model id |
| `PLANNER_API_KEY` | `${UPSTREAM_API_KEY}` | no | 4 |  |
| `BUILDER_BASE_URL` | — | yes (stage 4) | 4 | builder/executor LLM endpoint (e.g. `http://192.168.29.129:9292/v1`) |
| `BUILDER_MODEL` | — | yes (stage 4) | 4 | builder model id (e.g. `Qwen3.6-35B-Apex-Bal`) |
| `BUILDER_API_KEY` | `dummy` | no | 4 |  |
| `DEEP_AGENT_BUDGET_PER_CALL` | `70000` | no | 4 | token ceiling per LLM call |
| `DEEP_AGENT_MAX_STEPS` | `25` | no | 4 | hard cap on plan steps |
| `DEEP_AGENT_MAX_SECONDS` | `600` | no | 4 | hard cap on total run time |

---

# Task checklist

## Stage 0 — Baseline (already done)

- [x] **S0.1 — Agent + MCP scaffold**
- [x] **S0.2 — Compose stack**
- [x] **S0.3 — Env hygiene**
- [x] **S0.4 — Caddy wiring**
- [x] **S0.5 — Port block**
- [x] **S0.6 — Repo published**

## Stage 1 — Mongo + LangGraph

### S1.deps — Dependencies and base wiring

- [x] **S1.deps.1 — Pin LangGraph dependencies, drop SGLang**
  - Done when: `docker compose build mcp` succeeds; `grep -i sglang mcp/*.py` returns nothing.
- [x] **S1.deps.2 — Add `mongo` service to docker-compose**
  - Done when: `docker compose up -d mongo` reaches `healthy` within 30s.
- [x] **S1.deps.3 — Wire `mcp` to depend on `mongo`**
  - Done when: `docker compose up -d` starts mongo → mcp → agent in order.

### S1.seed — Mongo seed data

- [x] **S1.seed.1 — Create read-only app user**
  - Note: `app` user has `readWrite` so the LangGraph checkpointer can write; read-only is enforced by `db.py`.
- [x] **S1.seed.2 — Seed `employees` collection**
- [x] **S1.seed.3 — Seed `tickets` collection**
- [x] **S1.seed.4 — Seed `documents` collection**

### S1.db — Read-only Mongo access layer

- [x] **S1.db.1 — Singleton Motor client**
- [x] **S1.db.2 — `list_collections` and `describe_collection`**
- [x] **S1.db.3 — `validate_spec` allowlist**
  - Note: `additionalProperties: false` in JSON schema would break `pipeline` objects, so `_model_schema` only enforces it on schemas that define `properties` (not bare `{"type":"object"}`).
- [x] **S1.db.4 — `find` and `aggregate` executors**
  - Note: Pipeline stages with `len(stage) != 1` are rejected (prevents `[{}]`).

### S1.llm — LLM seam

- [x] **S1.llm.1 — `chat_model()` factory**
- [x] **S1.llm.2 — `structured(schema, system, user)` helper**
  - Note: Uses raw OpenAI `response_format` + thin fallback loop (not `ChatOpenAI.with_structured_output`), for better compatibility with vLLM/Qwen3.

### S1.ckpt — Checkpointer

- [x] **S1.ckpt.1 — Mongo-backed checkpointer factory**
  - Note: Implemented as `asynccontextmanager checkpointer_context()` returning `AsyncMongoDBSaver`, not a sync `get_checkpointer()`.

### S1.ag — `ask_data` graph

- [x] **S1.ag.1 — Pydantic state and IO models**
- [x] **S1.ag.2 — `discover_schema` node**
- [x] **S1.ag.3 — `plan_query` node**
- [x] **S1.ag.4 — `execute_query` node**
- [x] **S1.ag.5 — Conditional retry edge**
  - Note: Up to 1 retry on `spec_error`; second failure ends the graph with `final=None`.
- [x] **S1.ag.6 — Parallel `interpret_doc` fan-out**
- [x] **S1.ag.7 — `synthesize` node**
- [x] **S1.ag.8 — Compile the graph with checkpointer**
- [x] **S1.ag.9 — Markdown renderer**

### S1.mcp — MCP tool surface

- [x] **S1.mcp.1 — Register `mongo_list_collections`**
- [x] **S1.mcp.2 — Register `mongo_describe_collection`**
- [x] **S1.mcp.3 — Register `mongo_query` and `mongo_aggregate`**
- [x] **S1.mcp.4 — Register `ask_data`**

### S1.web_research — LangGraph rewrite of web_research

- [x] **S1.web_research.1 — Rewrite `web_research` as a `StateGraph`**

### S1.verify — End-to-end verification

- [x] **S1.verify.1 — Three-shape `ask_data` smoke test script**
- [x] **S1.verify.2 — Agent-path verification**
- [x] **S1.verify.3 — Checkpoints persisted**

## Stage 2 — Web frontend

### S2.scaffold — Scaffold web service

- [x] **S2.scaffold.1 — `web/` FastAPI service skeleton**
- [x] **S2.scaffold.2 — Add `web` service to compose**

### S2.ui — Front-end UI

- [x] **S2.ui.1 — Chat page (`templates/index.html` + `static/app.js`)**
- [x] **S2.ui.2 — "Ask data" shortcut**

### S2.verify

- [x] **S2.verify.1 — Manual UX walkthrough**

## Stage 3 — MCP hardening

### S3.transport — Streamable HTTP

- [x] **S3.transport.1 — Session IDs on `initialize`**
- [ ] **S3.transport.2 — SSE event framing on `GET /mcp`**
  - **Deferred.** Current `GET /mcp` emits keepalive pings with correct `event:`/`data:`/`id:` lines, but server-push routing of POST responses through SSE is not implemented. Synchronous POST response works for all current clients (in-stack agent, opencode, VS Code Chat, PiAgent).

### S3.auth — Bearer auth

- [x] **S3.auth.1 — `MCP_AUTH_TOKEN` enforcement**
- [x] **S3.auth.2 — Per-session token-bucket rate limit**

### S3.expose — Publish MCP via Caddy

- [x] **S3.expose.1 — Decide MCP public surface**
  - **Decision: LAN-only for now.** Rationale: the agent already exposes MCP tools via `/v1/chat/completions` at `${PUBLIC_HOSTNAME}`. IDE clients can reach `mcp:8080/mcp` via host port or VPN. Public Caddy routing deferred until an external client needs it and SSE server-push is implemented.
- [ ] **S3.expose.2 — Caddy labels / static snippet for MCP**
  - Deferred until external exposure is needed.

### S3.clients — Client recipes

- [x] **S3.clients.1 — `docs/clients.md` with paste-ready configs**

### S3.verify

- [ ] **S3.verify.1 — External-client smoke**
  - Depends on manually testing opencode or VS Code Chat against `http://<host>:${MCP_PORT}/mcp` from a remote machine.

## Stage 4 — Deep-Agents-style planner/builder subagents

**Goal:** A planner/builder subagent pair, dispatched as MCP tools, that splits work across two LLMs to keep any single conversation context under ~80k tokens.

- **Planner** (`UPSTREAM_BASE_URL` / `UPSTREAM_MODEL` — current Qwen) decomposes a user goal into a typed plan: ordered, independently-executable steps with declared inputs/outputs and a chosen tool per step. The planner never executes; it only emits structured plans.
- **Builder/executor** (separate endpoint: `http://192.168.29.129:9292/v1` serving `Qwen3.6-35B-Apex-Bal`) executes one step at a time with a focused toolbelt (filesystem in a sandbox, shell in a sandbox, `web_research`, `ask_data`/`mongo_query`). Each step runs in a fresh thread so per-step context stays small.
- **Parallelism** comes from LangGraph `Send(...)` fan-out when the planner marks steps as `parallel: true`. The supervisor reduces step results back into shared state and may re-plan once if a step fails.

Each subagent role gets its own env-var prefix (`PLANNER_*`, `BUILDER_*`) so a third role can be added later without touching existing ones. The two roles call the same `mcp/llm.py` factory with a `role` argument.

### 4a. Dispatch surface (enterprise pattern)

Exposed as **MCP tools**, not a new endpoint. Rationale: the Stage 3 auth/rate-limit/session-id shim already covers `mcp:8080/mcp`; reusing it means deep-agent calls inherit bearer auth and per-session limits with no new surface area. IDE clients (opencode, VS Code Chat, PiAgent) get the feature for free, and the agent's `/v1/chat/completions` continues to be the single public surface — internal dispatch is below it.

Two MCP tools, both implemented as LangGraph graphs:

- **`plan_task`** — input `{goal: str, context?: str}` → output `{plan_id, steps: [{id, tool, args, parallel, depends_on}], rationale}`. Calls the planner LLM once with a tight system prompt + the current MCP tool catalog. Persists the plan to Mongo (`deep_agent_plans`) and returns it.
- **`run_plan`** — input `{plan_id}` or `{plan: <inline plan>}` → output `{plan_id, results: [{step_id, status, output, error?}], summary}`. Executes steps in dependency order, fans parallel siblings out via `Send(...)`, and writes a per-step checkpoint so a failed run can resume.

A convenience tool **`deep_agent`** wraps both (`plan → run → summarize`) for one-shot callers. Steps within `run_plan` route to the existing MCP tools (`mongo_query`, `ask_data`, `web_research`, plus the new sandbox tools below) so the planner is bounded by the same allowlist enforced everywhere else.

### 4b. Executor toolbelt

The builder calls the existing MCP tools plus four new sandboxed tools. The sandbox is a dedicated bind-mounted directory (`./sandbox/` on the host → `/sandbox` inside the `mcp` container, mode `0777`); all file/shell tools resolve paths inside `/sandbox` and reject `..` traversal.

New MCP tools:

- `fs_read(path)` — read a UTF-8 file under `/sandbox`.
- `fs_write(path, content)` — write/replace a UTF-8 file under `/sandbox`.
- `fs_edit(path, old_string, new_string)` — exact-string replace (one match required), mirroring the Edit semantics the planner already knows.
- `shell_exec(cmd, timeout_sec=30)` — run `bash -lc <cmd>` inside `/sandbox` as a non-root user. No host mounts beyond `/sandbox`; egress allowed (so `pip`, `curl` work); CPU/mem caps via compose `deploy.resources`.

Existing tools the builder is permitted to invoke: `web_research`, `ask_data`, `mongo_query`, `mongo_aggregate`, `mongo_describe_collection`, `summarize_text`, `chat`. The planner sees the full allowlist; the builder is given only the subset relevant to the current step.

### 4c. Second LLM endpoint (per-role env vars)

Per-role override env vars. `mcp/llm.py` gains:

```python
def llm_client(role: str = "default") -> AsyncOpenAI: ...
def llm_model(role: str = "default") -> str: ...
```

Resolution order for `<ROLE>` ∈ `{PLANNER, BUILDER}`:

1. `<ROLE>_BASE_URL` / `<ROLE>_MODEL` / `<ROLE>_API_KEY` if set.
2. Fall back to `UPSTREAM_BASE_URL` / `UPSTREAM_MODEL` / `UPSTREAM_API_KEY`.

`.env.local` for this stage:

```
PLANNER_BASE_URL=${UPSTREAM_BASE_URL}     # explicit, even though it falls back
PLANNER_MODEL=${UPSTREAM_MODEL}
BUILDER_BASE_URL=http://192.168.29.129:9292/v1
BUILDER_MODEL=Qwen3.6-35B-Apex-Bal
BUILDER_API_KEY=dummy
```

Existing `chat_model()` / `structured()` accept a `role=` kwarg (default `"default"` keeps current behaviour). Tools that don't take a role keep working unchanged.

### 4d. Context budget enforcement

Per-session budget target: **80k tokens**. Mechanism:

- Each subagent invocation runs in its own LangGraph thread (`thread_id = uuid4()`), so state never bleeds across steps.
- Step inputs are a slice (`goal`, `step.args`, just-the-needed prior outputs declared in `depends_on`) — not the full plan or transcript.
- Builder system prompts and tool descriptions are de-duplicated against the planner's; the builder gets only the tools the current step uses.
- A `token_count_estimate` helper (tiktoken with the `cl100k_base` fallback) gates each LLM call; if the prompt would exceed `DEEP_AGENT_BUDGET_PER_CALL` (default 70k, leaving ~10k headroom for the response) the step is split or summarized first.

### 4e. Safety rails

- Sandbox path resolution uses `Path("/sandbox").resolve()` and rejects anything whose `resolve()` is not under it.
- `shell_exec` runs as uid 1000, no `--privileged`, no host network, dropped `CAP_*` except `CAP_NET_BIND_SERVICE` (so dev servers can still bind).
- `run_plan` caps total steps at `DEEP_AGENT_MAX_STEPS` (default 25) and total runtime at `DEEP_AGENT_MAX_SECONDS` (default 600).
- Plans are validated (Pydantic) before execution; unknown tool names fail closed.
- Single re-plan on failure (planner sees the failed step + error and emits a patched plan); a second failure ends the run with `isError=true`.

### 4f. Verification (intent)

1. `plan_task("Find the top 5 employees by ticket volume and draft an email to each")` returns a 4-step plan: `ask_data` → `fs_write` (draft) → `web_research` (greeting locales, parallel per locale) → `fs_edit`.
2. `run_plan` on the above completes end-to-end; `./sandbox/` contains the drafts; `db.deep_agent_plans` shows the persisted plan + run.
3. Forcing a failing step (e.g., bad Mongo predicate) triggers exactly one re-plan, then resolves.
4. Per-call token estimate logged on every LLM call and never exceeds `DEEP_AGENT_BUDGET_PER_CALL`.
5. Builder calls hit `192.168.29.129:9292` (`docker compose logs mcp` shows the request URL); planner calls hit `UPSTREAM_BASE_URL`.

---

# Task checklist — Stage 4

### S4.deps — Dependencies and env surface

- [x] **S4.deps.1 — Add `tiktoken` to `mcp/requirements.txt`**
  - Files: `mcp/requirements.txt`.
  - Done when: `docker compose build mcp` succeeds and `python -c "import tiktoken"` runs inside the container.
  - Depends on: —

- [x] **S4.deps.2 — Add Stage-4 env vars to `.env.example`**
  - Files: `.env.example`.
  - Done when: `PLANNER_BASE_URL`, `PLANNER_MODEL`, `PLANNER_API_KEY`, `BUILDER_BASE_URL`, `BUILDER_MODEL`, `BUILDER_API_KEY`, `DEEP_AGENT_BUDGET_PER_CALL`, `DEEP_AGENT_MAX_STEPS`, `DEEP_AGENT_MAX_SECONDS` all present with sensible defaults/comments. Add the entries to the Env surface table.
  - Depends on: —

- [x] **S4.deps.3 — Sandbox bind mount in `compose.yaml`**
  - Files: `compose.yaml`, `.gitignore`.
  - Done when: `./sandbox/` mounts to `/sandbox` in the `mcp` service, owned by uid 1000, gitignored. `mcp` runs with a non-root user for the sandbox tools (verify with `docker compose exec mcp id`).
  - Depends on: —

### S4.llm — Multi-role LLM seam

- [x] **S4.llm.1 — Add `role`-aware factory to `mcp/llm.py`**
  - Files: `mcp/llm.py`.
  - Done when: `llm_client(role="planner")` and `llm_client(role="builder")` return distinct `AsyncOpenAI` instances backed by `PLANNER_*` / `BUILDER_*` env vars, falling back to `UPSTREAM_*`. `llm_model(role)` returns the resolved model id. Existing zero-arg callers keep working.
  - Depends on: S4.deps.2

- [x] **S4.llm.2 — Plumb `role=` into `chat_model()` and `structured()`**
  - Files: `mcp/llm.py`.
  - Done when: both helpers accept `role: str = "default"` and route to the right client/model. Existing call sites unchanged. Add a unit-ish smoke (or one-line `python -c`) hitting both roles.
  - Depends on: S4.llm.1

### S4.sandbox — Sandbox tools (MCP)

- [x] **S4.sandbox.1 — `mcp/sandbox.py` with path-resolution guard**
  - Files: `mcp/sandbox.py`.
  - Done when: `safe_path(rel)` resolves under `/sandbox` and raises `ValueError` on traversal/`/abs` paths. Unit-ish smoke covers `..`, symlinks, and absolute paths.
  - Depends on: S4.deps.3

- [x] **S4.sandbox.2 — `fs_read` / `fs_write` / `fs_edit` MCP tools**
  - Files: `mcp/sandbox.py`, `mcp/server.py`.
  - Done when: three tools registered in `tools/list`; round-trip create→read→edit verified via `scripts/smoke_sandbox.sh`.
  - Depends on: S4.sandbox.1

- [x] **S4.sandbox.3 — `shell_exec` MCP tool**
  - Files: `mcp/sandbox.py`, `mcp/server.py`.
  - Done when: `shell_exec("ls -la")` returns the sandbox listing; `shell_exec("cd / && ls")` cannot escape (CWD stays in /sandbox or fails closed); timeout enforced; non-root uid verified inside container.
  - Depends on: S4.sandbox.1, S4.deps.3

### S4.planner — Planner subagent

- [x] **S4.planner.1 — Pydantic plan schema**
  - Files: `mcp/deep_agent/models.py` (new package).
  - Done when: `Plan`, `Step`, `StepResult` types defined; `Step.tool` must be in the current MCP tool allowlist (validated on `model_validate`).
  - Depends on: —

- [x] **S4.planner.2 — `plan_task` graph (single-node, structured-output)**
  - Files: `mcp/deep_agent/planner.py`.
  - Done when: takes `{goal, context?}`, calls the planner LLM with the live tool catalog from `mcp/server.py`, returns a validated `Plan`. Plan persisted to `db.deep_agent_plans` with a fresh `plan_id`. Checkpointed.
  - Depends on: S4.planner.1, S4.llm.2

- [x] **S4.planner.3 — Register `plan_task` MCP tool**
  - Files: `mcp/server.py`.
  - Done when: `tools/list` shows `plan_task`; `tools/call` returns the `Plan` JSON.
  - Depends on: S4.planner.2

### S4.builder — Builder/executor subagent

- [x] **S4.builder.1 — `run_plan` LangGraph with parallel fan-out**
  - Files: `mcp/deep_agent/builder.py`.
  - Done when: graph reads a `Plan`, executes steps in dependency order, fans `parallel:true` siblings via `Send(...)`, calls the builder LLM (per-step focused toolbelt = only the tools the step needs), collects `StepResult`s, returns a summary. Checkpointed under `plan_id`.
  - Depends on: S4.planner.1, S4.llm.2, S4.sandbox.2, S4.sandbox.3

- [x] **S4.builder.2 — Re-plan on first failure**
  - Files: `mcp/deep_agent/builder.py`.
  - Done when: when a step returns `status="error"`, builder calls planner with `{original_plan, failed_step, error}` once; the patched plan replaces remaining steps. Second failure ends the run with `isError=true`.
  - Depends on: S4.builder.1, S4.planner.2

- [x] **S4.builder.3 — Register `run_plan` MCP tool**
  - Files: `mcp/server.py`.
  - Done when: accepts either `{plan_id}` (load from Mongo) or `{plan}` (inline); returns `{plan_id, results, summary}`.
  - Depends on: S4.builder.1

- [x] **S4.builder.4 — Register `deep_agent` convenience tool**
  - Files: `mcp/server.py`.
  - Done when: one call runs `plan_task` → `run_plan` → returns combined result with the plan and per-step outputs. Useful for the agent endpoint to dispatch from a single user turn.
  - Depends on: S4.planner.3, S4.builder.3

### S4.budget — Context budget enforcement

- [x] **S4.budget.1 — `token_count_estimate` helper**
  - Files: `mcp/deep_agent/budget.py`.
  - Done when: returns an int estimate (tiktoken `cl100k_base`); falls back to len/4 if tiktoken can't load the encoding.
  - Depends on: S4.deps.1

- [x] **S4.budget.2 — Pre-flight budget check on every LLM call**
  - Files: `mcp/deep_agent/planner.py`, `mcp/deep_agent/builder.py`.
  - Done when: every prompt is measured against `DEEP_AGENT_BUDGET_PER_CALL`; over-budget prompts trigger a summarization pass (planner role) before the real call. Logged as `deep_agent.budget` events.
  - Depends on: S4.budget.1

### S4.safety — Limits and validation

- [x] **S4.safety.1 — Step-count and runtime caps in `run_plan`**
  - Files: `mcp/deep_agent/builder.py`.
  - Done when: exceeding `DEEP_AGENT_MAX_STEPS` or `DEEP_AGENT_MAX_SECONDS` ends the run with `isError=true` and a clear `error.code`.
  - Depends on: S4.builder.1

- [x] **S4.safety.2 — Tool allowlist enforcement at plan-validation time**
  - Files: `mcp/deep_agent/models.py`.
  - Done when: `Plan.model_validate` rejects unknown `tool` names against the live MCP catalog. Covered by a unit-ish smoke.
  - Depends on: S4.planner.1

### S4.verify — End-to-end

- [x] **S4.verify.1 — `scripts/smoke_deep_agent.sh`**
  - Files: `scripts/smoke_deep_agent.sh`.
  - Done when: invokes `deep_agent` via MCP with the goal from §4f.1; asserts `db.deep_agent_plans` row created, `./sandbox/` populated, exit 0.
  - Depends on: S4.builder.4

- [x] **S4.verify.2 — Two-endpoint traffic check**
  - Done when: `docker compose logs mcp | grep -E "(192.168.29.129|UPSTREAM_BASE_URL host)"` shows requests to both endpoints during a `deep_agent` run.
  - Depends on: S4.verify.1

- [x] **S4.verify.3 — Context budget never exceeded**
  - Done when: a stress goal (e.g. "summarize each of 50 web pages") completes without any single LLM call exceeding `DEEP_AGENT_BUDGET_PER_CALL`. Verified from the `deep_agent.budget` log lines.
  - Depends on: S4.verify.1

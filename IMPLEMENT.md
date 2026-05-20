# IMPLEMENT.md — sglandsimple enterprise rollout (LangGraph edition)

This document is the implementation plan for evolving the current stack into an enterprise-shaped pattern: **server-side LangGraph agent workflows over a NoSQL store, fronted by both a web UI and direct MCP access from IDE/agent clients (opencode, VS Code Chat, PiAgent).**

> The repo name `sglandsimple` predates the framework choice. Despite the name, **this plan uses LangGraph**, not SGLang. The earlier `web_research.py` (built with the SGLang DSL) will be rewritten as a LangGraph graph as part of stage 1 so the codebase is single-paradigm.

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
                             (web_research is currently SGLang — to be rewritten as LangGraph in stage 1)
caddy/Caddyfile.snippet.example   static-Caddyfile template (the .local copy is gitignored)
compose.yaml                 Dockge-discoverable; both services join the external `proxy` network
.env.local                   gitignored runtime values (UPSTREAM_*, SEARXNG_URL, PUBLIC_HOSTNAME, ports)
.env.example                 sanitized template
```

Caddy fronts `${PUBLIC_HOSTNAME} → agent:8000`. Two ways wired:

1. **caddy-docker-proxy**: the `agent` service in `compose.yaml` carries `caddy` and `caddy.reverse_proxy` labels referencing `${PUBLIC_HOSTNAME}`.
2. **Static Caddyfile**: copy `caddy/Caddyfile.snippet.example` → `caddy/Caddyfile.snippet.local`, replace the placeholder hostname, then `import` into your real Caddyfile.

What we keep from baseline:

- `agent/main.py`'s OpenAI-compatible front door and MCP tool dispatch loop. Unchanged.
- `mcp/server.py`'s JSON-RPC transport, `tools/list`/`tools/call` handling, healthcheck. Unchanged.
- The pattern of returning two MCP content blocks per workflow: a Markdown rendering + the raw JSON.

What we replace:

- The SGLang dependency and `mcp/web_research.py`'s `@sgl.function` + `sgl.fork` code → LangGraph `StateGraph`.
- All future workflow code is LangGraph.

## Stage 1 — MongoDB + LangGraph `ask_data` workflow

**Goal:** A server-side LangGraph workflow that turns a natural-language question into a constrained-JSON Mongo query, executes it, and returns a cited answer in both markdown and JSON. Existing `web_research` is rewritten in the same idiom so the codebase has one paradigm.

### 1a. Dependencies

`mcp/requirements.txt`:

```
fastapi==0.115.6
uvicorn[standard]==0.32.1
httpx==0.28.1
openai==1.59.7
langgraph==0.2.62
langgraph-checkpoint-mongodb==0.1.0
langchain-openai==0.2.14
langchain-core==0.3.28
motor==3.6.0
pydantic==2.10.4
```

Drop `sglang[openai]`. (Exact versions pinned at implementation time.)

### 1b. Compose changes

Add one service:

```yaml
mongo:
  image: mongo:7
  container_name: sglandsimple-mongo
  restart: unless-stopped
  volumes:
    - mongo-data:/data/db
    - ./mongo-seed:/docker-entrypoint-initdb.d:ro
  environment:
    MONGO_INITDB_DATABASE: enterprise
  networks: [default]
  healthcheck:
    test: ["CMD", "mongosh", "--quiet", "--eval", "db.runCommand({ ping: 1 }).ok"]
    interval: 10s
    timeout: 3s
    retries: 5

volumes:
  mongo-data:
```

No host port — accessed only by `mcp` on the compose network. `mcp` gains `MONGO_URL` and `MONGO_DB` env, and a `depends_on: { mongo: { condition: service_healthy } }`.

### 1c. Seed data

`mongo-seed/01-init.js` populates a small enterprise-ish dataset (≤50 docs per collection so the LLM can see the shape in prompts and tests run fast):

- `employees` — `_id`, `name`, `dept`, `role`, `hire_date`, `manager_id`, `salary_band`, `skills[]`
- `tickets` — `_id`, `title`, `body`, `status`, `priority`, `assignee_id`, `created_at`, `tags[]`
- `documents` — `_id`, `title`, `body`, `owner_id`, `updated_at`, `tags[]`

`mongo-seed/00-users.js` creates a read-only app user on the `enterprise` DB; `MONGO_URL` uses that user.

### 1d. New module: `mcp/db.py`

Wraps `motor`. Responsibilities:

- Singleton client from `MONGO_URL`, db from `MONGO_DB` (default `enterprise`).
- `list_collections()` → names + counts.
- `describe_collection(name, sample=5)` → inferred schema `{field: {types:[...], example:...}}` from a small `aggregate([{$sample:{size:N}}])`. Cached in-process with 60s TTL.
- `find(name, filter, projection, sort, limit, skip)` — read-only, hard `limit` ceiling (default 50).
- `aggregate(name, pipeline, limit)` — read-only.
- `validate_spec(spec)` — explicit allowlist:
  - `collection` ∈ known collections
  - rejects `$where`, `$function`, `$accumulator`, `$out`, `$merge`, and `$expr` containing JS
  - rejects pipelines mutating data (`$out`, `$merge`, `$collStats` writes)
  - clamps `limit` to ceiling
  - rejects unknown top-level keys in the spec

### 1e. New module: `mcp/llm.py`

Thin wrappers around the upstream:

- `chat_model()` — returns a `langchain_openai.ChatOpenAI` bound to `UPSTREAM_BASE_URL` / `UPSTREAM_API_KEY` / `UPSTREAM_MODEL`. Used by LangGraph nodes that don't need structured output.
- `structured(schema, system, user)` — wraps `ChatOpenAI.with_structured_output(schema, method="json_schema", strict=True)` for the constrained-JSON nodes. Schema = Pydantic model.

This is the single seam where we hit the upstream. Easy to swap later.

### 1f. New module: `mcp/checkpointer.py`

```python
from langgraph.checkpoint.mongodb import MongoDBSaver

def get_checkpointer():
    return MongoDBSaver.from_conn_string(MONGO_URL, db_name=MONGO_DB, collection_name="lg_checkpoints")
```

Stage 1 uses checkpoints purely for observability/debugging — clients don't pass `thread_id`s. Each MCP call gets a fresh random thread; runs are persisted so we can inspect them in Mongo.

### 1g. The `ask_data` graph (`mcp/ask_data.py`)

State (Pydantic):

```python
class AskDataState(BaseModel):
    question: str
    catalog: str | None = None              # rendered schema brief, set by node 1
    spec: QuerySpec | None = None           # planner output, set by node 2
    spec_error: str | None = None           # validation/exec error, fed back to node 2 once
    retry_count: int = 0
    docs: list[dict] = []                   # query results
    per_doc_notes: Annotated[list[DocNote], operator.add] = []  # fan-in reducer
    final: FinalAnswer | None = None        # synthesized answer (constrained JSON)
```

Pydantic models for the structured-output nodes:

```python
class QuerySpec(BaseModel):
    collection: str
    kind: Literal["find", "aggregate"]
    filter: dict | None = None
    projection: dict | None = None
    sort: dict | None = None
    limit: int = Field(default=20, ge=1, le=50)
    pipeline: list[dict] | None = None
    rationale: str

class DocNote(BaseModel):
    doc_id: str
    note: str

class Evidence(BaseModel):
    index: int
    doc_id: str
    collection: str
    quote: str
    why: str

class FinalAnswer(BaseModel):
    answer: str            # contains [n] markers
    evidence: list[Evidence]
    query_used: QuerySpec
```

Nodes:

| Node | Function | Output written to state |
| --- | --- | --- |
| `discover_schema` | Build catalog from `db.list_collections` + `describe_collection`. Cached. | `catalog` |
| `plan_query` | `structured(QuerySpec, ...)` against the upstream with `catalog`, `question`, and (on retry) `spec_error`. | `spec` |
| `execute_query` | `validate_spec(spec)` then `db.find` / `db.aggregate`. On error, sets `spec_error` and increments `retry_count`. | `docs` or `spec_error` |
| `fan_out_notes` | Returns a list of `Send("interpret_doc", {"doc": d, "question": q})` for the first `ASK_DATA_MAX_DOCS` docs. | (routes) |
| `interpret_doc` | One LLM call → `DocNote`. Reduced via `operator.add` into `per_doc_notes`. | appends to `per_doc_notes` |
| `synthesize` | `structured(FinalAnswer, ...)` with docs + notes; enforces citations. | `final` |
| `render` | Pure function: build markdown from `final`. (Renders happen outside the graph in `server.py`; this node is optional and may be omitted.) | — |

Edges:

```
START -> discover_schema -> plan_query -> execute_query
execute_query --(spec_error and retry_count < 1)--> plan_query
execute_query --(docs)--> fan_out_notes -> interpret_doc (parallel) -> synthesize -> END
execute_query --(spec_error and retry_count >= 1)--> END   # fail with diagnostic
```

Compiled with the Mongo checkpointer. Each invocation passes a fresh `thread_id = uuid4()`.

### 1h. New MCP tools (registered in `mcp/server.py`)

| Tool | Purpose |
| --- | --- |
| `mongo_list_collections` | Lists known collections + brief description. Backed by `db.list_collections`. |
| `mongo_describe_collection` | Returns sampled schema for one collection. |
| `mongo_query` | Direct `find` with structured args (validated, read-only). |
| `mongo_aggregate` | Direct aggregation (validated, read-only). |
| `ask_data` | Runs the LangGraph `ask_data` graph. Returns markdown + JSON. |

`mongo_query`/`mongo_aggregate` exist so an external MCP client (e.g. opencode) can drive Mongo through the model's own tool calls if it prefers, and so `ask_data` and the direct tools share the same execution+validation layer.

### 1i. Rewrite `web_research` as LangGraph

`mcp/web_research.py` becomes a `StateGraph` with the same flow:

```
START -> search (SearXNG) -> fan_out_annotate -> annotate_one (parallel via Send) -> synthesize (structured) -> END
```

Schema for `synthesize` is the existing one (`topic`, `summary` with `[n]` citations, `best_result` with verbatim quote, `citations[]`). Same MCP output (markdown + JSON). Removing the SGLang dependency entirely.

### 1j. Safety rails

- Read-only Mongo user. No write tools.
- All specs pass `validate_spec` before execution.
- Hard `limit` ceiling at the driver layer regardless of model output.
- One retry pass on validation/exec error; then fail closed.
- Tool call results sent back through MCP carry an `isError: true` flag on failure, never silent success.

### 1k. Verification

1. `docker compose up --build -d`.
2. `tools/list` shows the five new tools alongside the existing ones.
3. `mongo_describe_collection` returns sampled schema for `employees`.
4. `ask_data` answers three shapes correctly with schema-valid JSON:
   - direct lookup (`"who manages alice?"`)
   - aggregation (`"open tickets per priority"`)
   - tag-ish search (`"documents tagged onboarding"`)
5. Agent endpoint at `:8000/v1/chat/completions` answers the same question via tool calls dispatched to MCP.
6. `db.lg_checkpoints.find().limit(3)` in mongosh shows persisted checkpoint records.

**Done when**: all three question shapes work end-to-end, evidence references real `_id`s, and a checkpoint is persisted per run.

## Stage 2 — Web frontend

**Goal:** A minimal SPA-style page so non-IDE users can drive `ask_data` (and chat in general) without curl.

### Compose changes

Add one service:

```yaml
web:
  build: ./web
  container_name: sglandsimple-web
  restart: unless-stopped
  environment:
    AGENT_URL: http://agent:8000
  ports: ["${WEB_PORT:-3000}:3000"]
  depends_on: { agent: { condition: service_healthy } }
  networks: [default, proxy]
```

### Implementation

`web/` is a single-page app served by FastAPI (Jinja or plain HTML + JS — no build step):

- `/` — chat UI. Textarea + history. Posts to `/api/chat` on the same origin.
- `/api/chat` — server-side proxy to `agent:8000/v1/chat/completions` so the browser never holds the upstream API key (even if it's `dummy`, this is the prod pattern).
- `/api/ask_data` — convenience that calls the MCP `ask_data` tool *through* the agent (so the tool loop is consistent); renders the returned markdown block.
- Rendered with `marked` (CDN) for markdown, `highlight.js` for code/JSON fences.

Deliberately no React/Vite — the point is the access pattern, not frontend tooling. Replaceable later.

### Verification

- Open `http://localhost:3000`, ask `"open tickets per priority"`, see the markdown answer with citations.
- Tool-call path: ask a chatty question, watch the agent dispatch to MCP, get a final answer with no exposed tool plumbing.

**Done when**: a non-technical user can ask data questions through the browser and see cited answers.

## Stage 3 — MCP server hardening for external clients

**Goal:** Make `mcp:8080/mcp` directly consumable by opencode, VS Code Chat, PiAgent, etc., not just by our in-stack agent.

### Transport

Current MCP server is JSON-RPC over plain HTTP POST. External clients expect **Streamable HTTP** per the MCP spec:

- `POST /mcp` for client→server messages (already implemented).
- `GET /mcp` returns an SSE stream on which the server may push messages, and which the client uses to receive responses to its POSTed requests. Currently we only keepalive — we need correct event framing (`event:` lines, `id:` for resumability) and to route server-side responses through it for clients that opted into SSE.
- Session via `Mcp-Session-Id` response header on `initialize`, required on subsequent requests.

### Auth

- `MCP_AUTH_TOKEN` env. If set, all `/mcp` requests must carry `Authorization: Bearer <token>`. If unset, open (current behavior) — log a startup warning.
- Per-session rate limiting (token bucket, in-memory) keyed by session id.

### Capability advertisement

- Correct `initialize` response: `protocolVersion`, `serverInfo`, `capabilities.tools.listChanged = false`, `capabilities.logging = {}` if we add logging notifications.
- `tools/list` already correct.

### Optional: expose graph resumability

Stage 1 hides `thread_id`. Stage 3 can optionally expose an `ask_data_async` tool variant that:

- Accepts an optional `thread_id`.
- Returns immediately after `interrupt()` for clarification questions.
- A companion `resume` tool feeds human input back into the same thread.

Useful for "the model needs a clarifying question before running the query" flows. Defer unless a real client needs it.

### Client config snippets

Add `docs/clients.md` with paste-ready blocks for:

- opencode (`mcpServers` JSON with URL + bearer token)
- VS Code Chat (`mcp.servers` settings.json entry)
- PiAgent (config shape TBD)

### Verification

- `npx @modelcontextprotocol/inspector` connects, lists tools, calls `ask_data`, sees streamed responses.
- An opencode config snippet works against `http://<host>:8080/mcp` from a remote machine.
- With `MCP_AUTH_TOKEN` set, unauthenticated requests return 401.

**Done when**: at least one external MCP client (opencode or VS Code chat) drives `ask_data` end-to-end.

## Out of scope (for now)

- Multi-tenant auth (per-user Mongo namespaces).
- Write operations against Mongo (`$set`, `insert`, `delete`).
- Streaming responses from the agent (`stream: true`). Still 400s in stage 1.
- Observability (OTel, structured logs to a collector). Add when the first stage 3 client is live.
- Vector search / semantic retrieval. The current workflow plans queries against structured fields; embedding-based retrieval can be added as a node later.

## Env surface after all stages

All values live in `.env.local` (gitignored). `compose.yaml` uses `${VAR:?required}` for the required ones — compose refuses to start if they're unset.

| Var | Default | Required | Stage | Notes |
| --- | --- | --- | --- | --- |
| `UPSTREAM_BASE_URL` | — | yes | 0 | OpenAI-compatible LLM endpoint |
| `UPSTREAM_API_KEY` | `dummy` | no | 0 |  |
| `UPSTREAM_MODEL` | — | yes | 0 | model id sent upstream |
| `SEARXNG_URL` | — | yes | 0 | SearXNG used by `web_research` |
| `PUBLIC_HOSTNAME` | — | yes | 0 | hostname Caddy fronts (label-mode); ignored by static Caddyfile setups |
| `AGENT_PORT` | `5450` | no | 0 | host bind for agent (`5450:8000`) |
| `MCP_PORT` | `5451` | no | 0 | host bind for mcp (`5451:8080`) — LAN-only |
| `MONGO_URL` | — | yes (stage 1) | 1 | `mongodb://app:<pwd>@mongo:27017` |
| `MONGO_DB` | `enterprise` | no | 1 |  |
| `ASK_DATA_MAX_DOCS` | `10` | no | 1 |  |
| `ASK_DATA_LIMIT_CEILING` | `50` | no | 1 |  |
| `LANGGRAPH_CHECKPOINT_COLLECTION` | `lg_checkpoints` | no | 1 |  |
| `WEB_PORT` | `5452` | no | 2 | host bind for web frontend |
| `MCP_AUTH_TOKEN` | (unset → open) | no | 3 | when set, requires `Authorization: Bearer …` on `/mcp` |
| `MCP_RATE_PER_MIN` | `60` | no | 3 | per-session rate limit |

---

# Task checklist

Each task is self-contained. To work one: read its **Files**, **Goal**, and **Done when**, then implement. Check the box when all "Done when" bullets pass. Use `grep -n "^- \[ \]" IMPLEMENT.md | head` to find the next open task.

## Stage 0 — Baseline (already done)

- [x] **S0.1 — Agent + MCP scaffold** — FastAPI agent at `/v1/chat/completions` with server-side MCP tool loop; FastAPI MCP server at `/mcp` with `summarize_text`, `chat`, `echo`, `web_research` (SGLang DSL — to be rewritten in S1.web_research.1).
- [x] **S0.2 — Compose stack** — `compose.yaml` (renamed from `docker-compose.yml` for Dockge discovery), both services on external `proxy` network, healthchecks.
- [x] **S0.3 — Env hygiene** — All hardcoded URLs replaced with `${VAR:?required}` references. `.env.local` (gitignored) holds runtime values; `.env.example` is the sanitized template. Required vars fail-fast at startup.
- [x] **S0.4 — Caddy wiring** — `agent` carries `caddy: ${PUBLIC_HOSTNAME}` + `caddy.reverse_proxy` labels for caddy-docker-proxy; `caddy/Caddyfile.snippet.example` template provided for static-Caddyfile setups (`.local` copy gitignored).
- [x] **S0.5 — Port block** — Host bindings moved to contiguous 5450 (agent), 5451 (mcp). 5452/5453 reserved for stage 2/3 services.
- [x] **S0.6 — Repo published** — Private GitHub repo created via `gh`; no secrets, PII, or private network identifiers in committed files.

## Stage 1 — Mongo + LangGraph

### S1.deps — Dependencies and base wiring

- [ ] **S1.deps.1 — Pin LangGraph dependencies, drop SGLang**
  - Files: `mcp/requirements.txt`
  - Goal: Replace the SGLang stack with LangGraph + LangChain OpenAI + Motor + Pydantic.
  - Specifics:
    - Remove: `sglang[openai]`
    - Add (use these exact lines; bump only if a real incompatibility appears at build time):
      ```
      langgraph==0.2.62
      langgraph-checkpoint-mongodb==0.1.0
      langchain-openai==0.2.14
      langchain-core==0.3.28
      motor==3.6.0
      pydantic==2.10.4
      ```
    - Keep: `fastapi`, `uvicorn[standard]`, `httpx`, `openai`.
  - Done when:
    - `pip install -r mcp/requirements.txt` succeeds inside a clean `python:3.12-slim`.
    - `docker compose build mcp` succeeds.
    - `grep -i sglang mcp/requirements.txt mcp/*.py` returns nothing.
  - Depends on: —

- [ ] **S1.deps.2 — Add `mongo` service to docker-compose**
  - Files: `compose.yaml`, `.env.example`
  - Goal: Stand up a single-node Mongo on the compose default network, persistent volume, healthcheck.
  - Specifics:
    - Image `mongo:7`, container name `sglandsimple-mongo`, no host port.
    - Volumes: named `mongo-data:/data/db`, bind `./mongo-seed:/docker-entrypoint-initdb.d:ro`.
    - Env: `MONGO_INITDB_DATABASE=enterprise`.
    - Healthcheck: `mongosh --quiet --eval "db.runCommand({ping:1}).ok"`.
    - Top-level `volumes: { mongo-data: {} }`.
    - Add `MONGO_URL=mongodb://app:app@mongo:27017` and `MONGO_DB=enterprise` to `.env.example`.
  - Done when:
    - `docker compose config --quiet` exits 0.
    - `docker compose up -d mongo` reaches `healthy` within 30s.
    - `docker compose exec mongo mongosh --quiet --eval 'db.runCommand({ping:1}).ok'` prints `1`.
  - Depends on: —

- [ ] **S1.deps.3 — Wire `mcp` to depend on `mongo`**
  - Files: `compose.yaml`
  - Goal: `mcp` only starts after Mongo is healthy and has `MONGO_URL`/`MONGO_DB` in env.
  - Specifics:
    - Add `depends_on: { mongo: { condition: service_healthy } }` to `mcp`.
    - Add `MONGO_URL` and `MONGO_DB` env passthroughs with the same `${...:-default}` style as the other vars.
  - Done when:
    - `docker compose up -d` starts mongo, then mcp, then agent without errors.
    - `docker compose exec mcp printenv MONGO_URL` prints the expected value.
  - Depends on: S1.deps.2

### S1.seed — Mongo seed data

- [ ] **S1.seed.1 — Create read-only app user**
  - Files: `mongo-seed/00-users.js`
  - Goal: An `app` user with `read` on `enterprise`, used by the MCP service. Runs once on first container start.
  - Specifics:
    - Switch to `admin`, `db.createUser({user:'app', pwd:'app', roles:[{role:'read', db:'enterprise'}]})`.
    - Wrap in `try/catch` so re-runs don't fail (Mongo init scripts run only on empty data dir, but keep it idempotent).
  - Done when:
    - On a fresh `mongo-data` volume, `docker compose exec mongo mongosh -u app -p app --authenticationDatabase admin enterprise --eval 'db.runCommand({ping:1}).ok'` prints `1`.
    - Writes from that user fail (`db.test.insertOne({})` → "not authorized").
  - Depends on: S1.deps.2

- [ ] **S1.seed.2 — Seed `employees` collection**
  - Files: `mongo-seed/01-employees.js`
  - Goal: ~30 employee docs with realistic, queryable shape.
  - Specifics:
    - Fields: `_id` (string), `name`, `dept` ∈ {Engineering, Sales, Support, HR, Finance}, `role`, `hire_date` (ISODate), `manager_id` (string or null), `salary_band` ∈ {IC1..IC6, M1..M3}, `skills` (string[]).
    - Include at least one chain of length 3 (IC → manager → director).
    - Use deterministic `_id`s like `emp-001`.
  - Done when:
    - `db.employees.countDocuments({})` ≥ 25.
    - `db.employees.findOne({dept:'Engineering'})` returns a doc with all fields present.
  - Depends on: S1.deps.2

- [ ] **S1.seed.3 — Seed `tickets` collection**
  - Files: `mongo-seed/02-tickets.js`
  - Goal: ~40 ticket docs spanning statuses and priorities for aggregation tests.
  - Specifics:
    - Fields: `_id`, `title`, `body`, `status` ∈ {open, in_progress, resolved, closed}, `priority` ∈ {p0, p1, p2, p3}, `assignee_id` (matches an `employees._id`), `created_at`, `tags` (string[]).
    - Distribute statuses+priorities so aggregations return varied rows.
  - Done when:
    - `db.tickets.aggregate([{$group:{_id:'$priority', n:{$sum:1}}}])` returns ≥ 3 rows.
    - Every `assignee_id` resolves to an existing employee.
  - Depends on: S1.seed.2

- [ ] **S1.seed.4 — Seed `documents` collection**
  - Files: `mongo-seed/03-documents.js`
  - Goal: ~20 documents with tags so text-ish queries work.
  - Specifics:
    - Fields: `_id`, `title`, `body` (1-2 paragraphs of plausible content), `owner_id`, `updated_at`, `tags` (string[]).
    - Include the tag `onboarding` on at least 3 docs, `runbook` on at least 2.
  - Done when:
    - `db.documents.countDocuments({tags:'onboarding'})` ≥ 3.
    - At least one doc body contains the literal word "policy" (for quote-extraction tests).
  - Depends on: S1.seed.2

### S1.db — Read-only Mongo access layer

- [ ] **S1.db.1 — Singleton Motor client**
  - Files: `mcp/db.py`
  - Goal: One reusable `AsyncIOMotorClient` keyed on `MONGO_URL`, db on `MONGO_DB`.
  - Specifics:
    - Module-level `_client = None`; `def get_db()` returns `_client[MONGO_DB]`, constructing on first call.
    - No connection on import — lazy.
  - Done when:
    - `python -c "import asyncio; from mcp.db import get_db; print(asyncio.run(get_db().command('ping')))"` from inside the mcp container prints `{'ok': 1.0}`.
  - Depends on: S1.deps.3, S1.seed.1

- [ ] **S1.db.2 — `list_collections` and `describe_collection`**
  - Files: `mcp/db.py`
  - Goal: Schema discovery the planner node can prompt with.
  - Specifics:
    - `async def list_collections() -> list[dict]`: `[{name, count}]` for the three seeded collections.
    - `async def describe_collection(name, sample=5) -> dict`: returns `{field: {types:[...], example}}` from `aggregate([{$sample:{size:N}}])`.
    - In-process TTL cache (60s) keyed by `name`.
  - Done when:
    - `await list_collections()` returns 3 entries with non-zero counts.
    - `await describe_collection('tickets')` returns a dict containing keys `status`, `priority`, `assignee_id`.
  - Depends on: S1.db.1, S1.seed.4

- [ ] **S1.db.3 — `validate_spec` allowlist**
  - Files: `mcp/db.py`
  - Goal: One function that accepts a planner-emitted spec and either returns a normalized spec or raises `SpecError`.
  - Specifics:
    - Validate `collection ∈ {employees, tickets, documents}`.
    - Validate `kind ∈ {find, aggregate}`.
    - For `find`: only `filter`, `projection`, `sort`, `limit`, `skip` allowed. Clamp `limit` to `ASK_DATA_LIMIT_CEILING` (default 50).
    - For `aggregate`: scan every stage; reject if any stage key is `$out`, `$merge`, `$function`, `$accumulator`. Reject any value containing `$where` recursively. Reject `$expr` containing `$function`.
    - Recursive walker that flags any forbidden operator at any depth.
    - Raise `SpecError(reason, path)` with a JSON-pointer-ish path.
  - Done when:
    - Unit-style assertions: `validate_spec({collection:'tickets', kind:'find', filter:{$where:'1'}})` raises.
    - `validate_spec({collection:'tickets', kind:'find', limit:9999})` returns spec with `limit == 50`.
    - Valid `aggregate` with `$group` + `$match` passes through unchanged.
  - Depends on: S1.db.1

- [ ] **S1.db.4 — `find` and `aggregate` executors**
  - Files: `mcp/db.py`
  - Goal: Thin async wrappers that always call `validate_spec` first and stringify `_id` for JSON-safety.
  - Specifics:
    - `async def find(spec) -> list[dict]`.
    - `async def aggregate(spec) -> list[dict]`.
    - Post-process: convert any `ObjectId` to `str` recursively before return.
    - Surface driver errors as `ExecError`.
  - Done when:
    - `await find({collection:'employees', kind:'find', filter:{dept:'Engineering'}, limit:5})` returns ≤5 dicts with stringified `_id`.
    - `await aggregate({collection:'tickets', kind:'aggregate', pipeline:[{$group:{_id:'$priority', n:{$sum:1}}}]})` returns the per-priority counts.
  - Depends on: S1.db.3

### S1.llm — LLM seam

- [ ] **S1.llm.1 — `chat_model()` factory**
  - Files: `mcp/llm.py`
  - Goal: Single function returning a configured `ChatOpenAI` pointed at the upstream.
  - Specifics:
    - Reads `UPSTREAM_BASE_URL`, `UPSTREAM_API_KEY`, `UPSTREAM_MODEL`.
    - Returns `ChatOpenAI(base_url=..., api_key=..., model=..., temperature=0.2)`.
    - No module-level instance; construct on call so tests can monkeypatch env.
  - Done when:
    - `chat_model().invoke("ping").content` returns a non-empty string inside the mcp container.
  - Depends on: S1.deps.1

- [ ] **S1.llm.2 — `structured(schema, system, user)` helper**
  - Files: `mcp/llm.py`
  - Goal: One-call constrained-JSON wrapper.
  - Specifics:
    - Signature: `async def structured(schema: type[BaseModel], system: str, user: str) -> BaseModel`.
    - Uses `chat_model().with_structured_output(schema, method='json_schema', strict=True)` and `ainvoke([SystemMessage(system), HumanMessage(user)])`.
    - Returns a typed Pydantic instance, not a dict.
  - Done when:
    - With a trivial schema `class Foo(BaseModel): name: str; n: int`, `await structured(Foo, 'reply concisely', 'name=alice n=3')` returns `Foo(name='alice', n=3)` (or close — the point is it parses to the schema).
  - Depends on: S1.llm.1

### S1.ckpt — Checkpointer

- [ ] **S1.ckpt.1 — Mongo-backed checkpointer factory**
  - Files: `mcp/checkpointer.py`
  - Goal: `get_checkpointer()` returns a `MongoDBSaver` writing to `enterprise.lg_checkpoints`.
  - Specifics:
    - Uses `MONGO_URL`, `MONGO_DB`, env-overridable collection name (`LANGGRAPH_CHECKPOINT_COLLECTION`, default `lg_checkpoints`).
    - Constructed via `MongoDBSaver.from_conn_string(...)`.
  - Done when:
    - Importing `get_checkpointer` and instantiating does not error.
    - After running any graph once (S1.ag.4), `db.lg_checkpoints.estimatedDocumentCount()` > 0.
  - Depends on: S1.deps.3

### S1.ag — `ask_data` graph

- [ ] **S1.ag.1 — Pydantic state and IO models**
  - Files: `mcp/ask_data_models.py`
  - Goal: All typed state and IO shapes in one file so nodes can import without cycles.
  - Specifics:
    - `QuerySpec`, `DocNote`, `Evidence`, `FinalAnswer` per the narrative section.
    - `AskDataState(BaseModel)` with `per_doc_notes: Annotated[list[DocNote], operator.add]` (use `langgraph.graph.add_messages`-style annotation for list reducers).
  - Done when:
    - `from mcp.ask_data_models import *` imports cleanly.
    - `QuerySpec.model_validate({collection:'tickets', kind:'find', rationale:'x'})` succeeds.
  - Depends on: S1.deps.1

- [ ] **S1.ag.2 — `discover_schema` node**
  - Files: `mcp/ask_data.py`
  - Goal: Build a compact catalog string from `list_collections` + `describe_collection`.
  - Specifics:
    - Async node `discover_schema(state) -> {"catalog": str}`.
    - Format: per-collection block with field name, types list, one example value, truncated to ≤200 chars per field.
    - Cache the rendered catalog at module level with a 60s TTL.
  - Done when:
    - Calling the node returns a string mentioning all three collections and at least `status`, `priority`, `dept`.
  - Depends on: S1.db.2

- [ ] **S1.ag.3 — `plan_query` node**
  - Files: `mcp/ask_data.py`
  - Goal: `structured(QuerySpec, ...)` call producing a validated spec, with one retry on failure.
  - Specifics:
    - System prompt explains the available collections (from `state.catalog`), forbids write operators, mandates `rationale`.
    - If `state.spec_error` is set, prompt includes it and asks for a corrected spec.
    - Returns `{spec: QuerySpec, spec_error: None}` (clears the error so the next execute pass is clean).
  - Done when:
    - On `question='open tickets per priority'`, returns a spec with `collection='tickets'` and `kind='aggregate'`.
    - On retry path (inject a `spec_error`), returns a different spec.
  - Depends on: S1.llm.2, S1.ag.1, S1.ag.2

- [ ] **S1.ag.4 — `execute_query` node**
  - Files: `mcp/ask_data.py`
  - Goal: Validate + run the spec; populate `docs` or set `spec_error`.
  - Specifics:
    - `validate_spec(state.spec)` then `db.find` or `db.aggregate`.
    - On `SpecError`/`ExecError`: set `spec_error=str(e)`, increment `retry_count`.
    - On success: set `docs=results`, leave `spec_error=None`.
  - Done when:
    - With a valid spec, populates `docs` with ≥1 result.
    - With an invalid spec, `spec_error` is populated and `docs == []`.
  - Depends on: S1.db.4, S1.ag.3

- [ ] **S1.ag.5 — Conditional retry edge**
  - Files: `mcp/ask_data.py`
  - Goal: After `execute_query`, route back to `plan_query` if `spec_error and retry_count < 1`, otherwise forward.
  - Specifics:
    - `def route_after_exec(state) -> str`: returns `'plan_query'`, `'fan_out_notes'`, or `'__end__'` (for terminal failure).
    - Wire with `graph.add_conditional_edges('execute_query', route_after_exec, {...})`.
  - Done when:
    - First-failure run loops back to `plan_query` exactly once.
    - Second failure ends the graph with `final=None` and the error preserved in state.
  - Depends on: S1.ag.4

- [ ] **S1.ag.6 — Parallel `interpret_doc` fan-out**
  - Files: `mcp/ask_data.py`
  - Goal: Per-document one-line relevance note, in parallel via `Send`.
  - Specifics:
    - `fan_out_notes(state)` returns `[Send('interpret_doc', {doc, question}) for doc in state.docs[:ASK_DATA_MAX_DOCS]]`.
    - `interpret_doc({doc, question}) -> {per_doc_notes: [DocNote(doc_id, note)]}` — single LLM call per doc.
    - `per_doc_notes` is reduced via `operator.add` (set up in S1.ag.1).
  - Done when:
    - With 6 docs and `ASK_DATA_MAX_DOCS=4`, `per_doc_notes` ends with exactly 4 entries.
    - Notes are non-empty and ≤30 words each.
  - Depends on: S1.ag.4, S1.llm.1

- [ ] **S1.ag.7 — `synthesize` node**
  - Files: `mcp/ask_data.py`
  - Goal: `structured(FinalAnswer, ...)` producing the cited answer.
  - Specifics:
    - Prompt enforces `[n]` citation markers, verbatim quotes from fields present in `docs`, and that every `evidence.doc_id` appears in `docs`.
    - Returns `{final: FinalAnswer}`.
  - Done when:
    - On the "open tickets per priority" question, `final.answer` contains at least one `[1]`-style marker.
    - `final.evidence[*].doc_id` ⊆ `[d['_id'] for d in docs]`.
  - Depends on: S1.ag.6

- [ ] **S1.ag.8 — Compile the graph with checkpointer**
  - Files: `mcp/ask_data.py`
  - Goal: A module-level `GRAPH = build_graph()` callable that streams to completion.
  - Specifics:
    - `StateGraph(AskDataState)` with nodes from S1.ag.2–7.
    - Edges: `START → discover_schema → plan_query → execute_query`; conditional from `execute_query`; `fan_out_notes → interpret_doc → synthesize → END`.
    - `graph.compile(checkpointer=get_checkpointer())`.
    - Public `async def run_ask_data(question: str) -> AskDataState`: invokes with fresh `thread_id=uuid4()`.
  - Done when:
    - `await run_ask_data('open tickets per priority')` returns a state where `final is not None`.
    - `db.lg_checkpoints.find({thread_id: <that uuid>}).count()` > 0.
  - Depends on: S1.ckpt.1, S1.ag.5, S1.ag.7

- [ ] **S1.ag.9 — Markdown renderer**
  - Files: `mcp/ask_data.py`
  - Goal: `render_markdown(final: FinalAnswer) -> str` for the MCP markdown block.
  - Specifics:
    - Sections: `# Answer`, `## Evidence` (bulleted with `[n] (collection/doc_id)` then a `>` quote and the `why`), `## Query used` (fenced JSON of `query_used`).
  - Done when:
    - Output contains the answer text, every `[n]` referenced in `answer` appears as an Evidence bullet, and the fenced block parses as JSON.
  - Depends on: S1.ag.7

### S1.mcp — MCP tool surface

- [ ] **S1.mcp.1 — Register `mongo_list_collections`**
  - Files: `mcp/server.py`
  - Goal: Read-only listing tool.
  - Specifics:
    - Tool entry in `TOOLS` with no args.
    - Dispatch: returns `db.list_collections()` rendered as a small markdown table + JSON.
  - Done when:
    - `tools/call` with `name=mongo_list_collections` returns `isError:false` and the three collection names.
  - Depends on: S1.db.2

- [ ] **S1.mcp.2 — Register `mongo_describe_collection`**
  - Files: `mcp/server.py`
  - Goal: Sampled-schema tool, one arg `name`.
  - Specifics:
    - Schema validates `name` ∈ collections list (driver layer rejects unknown).
    - Returns rendered schema + raw JSON.
  - Done when:
    - `tools/call` with `name='employees'` returns the same shape as `db.describe_collection('employees')`.
  - Depends on: S1.db.2

- [ ] **S1.mcp.3 — Register `mongo_query` and `mongo_aggregate`**
  - Files: `mcp/server.py`
  - Goal: Direct query/aggregate tools that exercise the same `validate_spec` + executor path as the graph.
  - Specifics:
    - `mongo_query` args: `collection`, `filter`, `projection?`, `sort?`, `limit?`, `skip?`.
    - `mongo_aggregate` args: `collection`, `pipeline`, `limit?`.
    - Both return `{rows: [...]}` JSON plus a markdown table preview (first 10 rows).
    - On `SpecError`/`ExecError`, return `isError:true` with the message.
  - Done when:
    - Valid `mongo_query` on `employees` returns rows with stringified `_id`.
    - `$where` injection returns `isError:true`.
  - Depends on: S1.db.4

- [ ] **S1.mcp.4 — Register `ask_data`**
  - Files: `mcp/server.py`
  - Goal: One arg `question`. Runs the graph, returns markdown + JSON.
  - Specifics:
    - `_tool_ask_data(args)` calls `run_ask_data`, then `render_markdown(final)` and `final.model_dump()`.
    - On terminal failure (`final is None`), `isError:true` with `spec_error` text.
  - Done when:
    - `tools/call` with `question='open tickets per priority'` returns two text blocks (markdown then JSON), `isError:false`.
    - The agent endpoint (`agent/main.py`) successfully dispatches a model-emitted `ask_data` tool call without changes to its code.
  - Depends on: S1.ag.8, S1.ag.9

### S1.web_research — LangGraph rewrite of web_research

- [ ] **S1.web_research.1 — Rewrite `web_research` as a `StateGraph`**
  - Files: `mcp/web_research.py`
  - Goal: Same external behavior; SGLang removed.
  - Specifics:
    - State: `topic`, `hits`, `notes` (list reducer), `final`.
    - Nodes: `search` (SearXNG) → `fan_out_annotate` (Send per hit) → `annotate_one` → `synthesize` (structured, same schema as today) → END.
    - Reuse `mcp/llm.py` and the existing markdown renderer.
    - Drop all `import sglang` lines and the `set_default_backend` call.
  - Done when:
    - `tools/call name=web_research` returns the same markdown + JSON shape it does today.
    - `grep -i sgl mcp/` returns no hits.
  - Depends on: S1.llm.2

### S1.verify — End-to-end verification

- [ ] **S1.verify.1 — Three-shape `ask_data` smoke test script**
  - Files: `scripts/smoke_ask_data.sh`
  - Goal: A repeatable script that hits MCP with three canonical questions and asserts schema-valid output.
  - Specifics:
    - For each of: `"who manages alice?"`, `"open tickets per priority"`, `"documents tagged onboarding"` — POST `tools/call` and pipe the second content block through `jq -e` checking required keys (`answer`, `evidence`, `query_used`).
    - Exit 0 only if all three pass.
  - Done when:
    - `bash scripts/smoke_ask_data.sh` exits 0 against the running stack.
  - Depends on: S1.mcp.4

- [ ] **S1.verify.2 — Agent-path verification**
  - Files: `scripts/smoke_agent.sh`
  - Goal: Confirm the OpenAI-compatible agent dispatches to `ask_data` end-to-end.
  - Specifics:
    - POST to `:8000/v1/chat/completions` with a user message that should trigger `ask_data`.
    - Assert the final assistant message references at least one `_id` from Mongo.
  - Done when:
    - `bash scripts/smoke_agent.sh` exits 0.
  - Depends on: S1.mcp.4

- [ ] **S1.verify.3 — Checkpoints persisted**
  - Files: (no code) — manual check or assertion in smoke script
  - Goal: Confirm the Mongo checkpointer is wired correctly.
  - Done when:
    - After running S1.verify.1, `docker compose exec mongo mongosh enterprise --eval 'db.lg_checkpoints.estimatedDocumentCount()'` prints a number > 0.
  - Depends on: S1.verify.1

## Stage 2 — Web frontend

### S2.scaffold — Scaffold web service

- [ ] **S2.scaffold.1 — `web/` FastAPI service skeleton**
  - Files: `web/main.py`, `web/Dockerfile`, `web/requirements.txt`
  - Goal: Minimal FastAPI app that serves an HTML page and proxies two endpoints to the agent.
  - Specifics:
    - `GET /` → renders `templates/index.html` (Jinja).
    - `POST /api/chat` → proxies the JSON body to `${AGENT_URL}/v1/chat/completions`, returns upstream JSON.
    - `POST /api/ask_data` → constructs a chat-completions call that nudges the model to call `ask_data`, returns the upstream JSON.
    - `requirements.txt`: `fastapi`, `uvicorn[standard]`, `httpx`, `jinja2`.
  - Done when:
    - `docker compose up -d web` exposes `:${WEB_PORT}` (default `5452`); `curl localhost:5452/` returns HTML.
    - `POST /api/chat` with `{messages:[{role:'user', content:'hi'}]}` returns a 200 with a non-empty assistant message.
  - Depends on: S1.mcp.4

- [ ] **S2.scaffold.2 — Add `web` service to compose**
  - Files: `compose.yaml`, `.env.example`, `.env.local`
  - Goal: New service builds from `./web`, attaches to `default` and `proxy`, depends on agent.
  - Specifics:
    - `WEB_PORT` already declared in `.env.example` (default 5452) and `.env.local`.
    - Healthcheck identical pattern to the others.
    - **Do not** add Caddy labels — stage 2 web stays behind the same `PUBLIC_HOSTNAME` as the agent only if you decide to in a follow-up; default is host-port-only access.
  - Done when:
    - `docker compose config --quiet` exits 0.
    - `docker compose up -d` brings `web` to healthy.
  - Depends on: S2.scaffold.1

### S2.ui — Front-end UI

- [ ] **S2.ui.1 — Chat page (`templates/index.html` + `static/app.js`)**
  - Files: `web/templates/index.html`, `web/static/app.js`, `web/static/styles.css`
  - Goal: Single-pane chat UI; renders markdown.
  - Specifics:
    - Textarea + send button + scrolling history.
    - JS posts conversation to `/api/chat`; on response, appends assistant message rendered through `marked` (CDN).
    - JSON code fences highlighted via `highlight.js` (CDN).
  - Done when:
    - From the browser at `http://<host>:${WEB_PORT}`, sending "open tickets per priority" returns an answer containing `[n]` markers and a fenced JSON block, rendered.
  - Depends on: S2.scaffold.2

- [ ] **S2.ui.2 — "Ask data" shortcut**
  - Files: `web/templates/index.html`, `web/static/app.js`
  - Goal: A second button labeled "Ask data" that calls `/api/ask_data` and renders the markdown body of the returned MCP markdown block.
  - Done when:
    - Clicking "Ask data" with a question runs the tool path explicitly and displays the same markdown the MCP tool produced.
  - Depends on: S2.ui.1

### S2.verify

- [ ] **S2.verify.1 — Manual UX walkthrough**
  - Files: — (no code)
  - Goal: Confirm a non-technical user can use it.
  - Done when:
    - Loading `http://<host>:${WEB_PORT}`, typing a question, and seeing a cited markdown answer requires no terminal interaction.
  - Depends on: S2.ui.2

## Stage 3 — MCP hardening

### S3.transport — Streamable HTTP

- [ ] **S3.transport.1 — Session IDs on `initialize`**
  - Files: `mcp/server.py`
  - Goal: Return a `Mcp-Session-Id` header on `initialize`; require it on subsequent POSTs.
  - Specifics:
    - In-memory `dict[session_id, SessionState]`. Sessions expire after 30 min idle.
    - Missing header on non-initialize methods → 400 with JSON-RPC error.
  - Done when:
    - `initialize` response includes a fresh UUID header.
    - A second `tools/list` without the header is rejected; with the header, accepted.
  - Depends on: —

- [ ] **S3.transport.2 — SSE event framing on `GET /mcp`**
  - Files: `mcp/server.py`
  - Goal: Replace keepalive-only stream with proper SSE: `event:`, `data:`, monotonically increasing `id:`.
  - Specifics:
    - Per-session asyncio.Queue. POST handlers can enqueue responses for SSE delivery; default behavior (current synchronous JSON response) preserved for clients that don't open SSE.
    - On `Last-Event-Id` header, replay queued events from that point (resumability).
  - Done when:
    - `npx @modelcontextprotocol/inspector` connects via Streamable HTTP and lists tools.
    - A request issued over POST and listened-for over SSE is received once on the SSE stream.
  - Depends on: S3.transport.1

### S3.auth — Bearer auth

- [ ] **S3.auth.1 — `MCP_AUTH_TOKEN` enforcement**
  - Files: `mcp/server.py`, `.env.example`
  - Goal: If `MCP_AUTH_TOKEN` is set, require `Authorization: Bearer <token>` on `/mcp` (both GET and POST).
  - Specifics:
    - Unset → permissive, log a startup warning ("MCP_AUTH_TOKEN not set; /mcp is open").
    - Mismatch → 401.
  - Done when:
    - Setting the env and restarting causes unauth requests to 401; matching token passes.
  - Depends on: —

- [ ] **S3.auth.2 — Per-session token-bucket rate limit**
  - Files: `mcp/server.py`
  - Goal: Default 60 req/min per session; configurable via `MCP_RATE_PER_MIN`.
  - Done when:
    - Sustained burst >60/min from one session sees 429s; a second session is unaffected.
  - Depends on: S3.transport.1

### S3.expose — Publish MCP via Caddy

- [ ] **S3.expose.1 — Decide MCP public surface**
  - Files: `IMPLEMENT.md` (this section)
  - Goal: Choose between (a) `${PUBLIC_HOSTNAME}/mcp` path-routed to mcp:8080, (b) a second hostname (`mcp.<...>`) pointed at mcp:8080, or (c) keep LAN-only and let external clients tunnel.
  - Done when:
    - Decision recorded here with one sentence of rationale.
  - Depends on: S3.auth.1

- [ ] **S3.expose.2 — Caddy labels / static snippet for MCP**
  - Files: `compose.yaml`, `caddy/Caddyfile.snippet.example`
  - Goal: Implement the decision from S3.expose.1.
  - Specifics:
    - If path-routed: add `caddy.handle_path: "/mcp/*"` + matching reverse_proxy on the existing `agent`/`mcp` labels, *or* a `handle /mcp*` block in the Caddyfile snippet pointing at `sglandsimple-mcp:8080`.
    - If a second hostname: add `caddy: ${MCP_PUBLIC_HOSTNAME}` + `caddy.reverse_proxy: "{{upstreams 8080}}"` to the `mcp` service and add `MCP_PUBLIC_HOSTNAME` to `.env.local` + `.env.example`.
    - Update env-surface table.
  - Done when:
    - From a remote machine, `curl https://<chosen URL>/mcp -X POST ...` with the bearer token reaches the MCP server and `tools/list` succeeds.
  - Depends on: S3.expose.1, S3.transport.2, S3.auth.1

### S3.clients — Client recipes

- [ ] **S3.clients.1 — `docs/clients.md` with paste-ready configs**
  - Files: `docs/clients.md`
  - Goal: One copy-paste block per supported client (opencode, VS Code Chat, PiAgent).
  - Specifics:
    - URL form, bearer token placement, transport (`http`/streamable).
    - Note the required `MCP_AUTH_TOKEN` env to set on this server side.
  - Done when:
    - At least one external client (opencode or VS Code Chat) can drive `ask_data` end-to-end against the local stack using only the doc.
  - Depends on: S3.transport.2, S3.auth.1

### S3.verify

- [ ] **S3.verify.1 — External-client smoke**
  - Files: — (manual)
  - Done when:
    - opencode (or VS Code Chat) lists tools and successfully calls `ask_data` from a separate machine using the doc-provided config.
  - Depends on: S3.clients.1


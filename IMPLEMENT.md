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
- ~~Write operations against Mongo (`$set`, `insert`, `delete`)~~ — landed in Stage 6 via a narrow audited write-layer (`mcp/db.py::insert_one|update_one|delete_one`). Free-form multi-doc updates remain out of scope.
- Streaming responses from the agent (`stream: true`). Still 400s.
- Observability (OTel, structured logs to a collector).
- Vector search / semantic retrieval.
- SSE server-push of POST responses (deferred in S3.transport.2).
- Public Caddy routing for MCP (deferred in S3.expose.2).

## Stage 6 — Spreadsheet UI + natural-language data editing

**Goal:** A spreadsheet-style front end over the Mongo collections — **Airtable / NocoDB-shaped UX** (left rail of "tables" = collections, dense grid with sticky headers, inline cell edit, per-cell save state, paging) — so a user can manipulate rows directly **and** drive the same edits via plain-English commands ("change Alice's dept to Platform", "raise the salary band for everyone in Support hired before 2020 to IC4"). Reuses the existing agent → MCP tool-loop plumbing; adds a small write-layer with hard safety rails.

> This stage extends Stage 1 (read-only `ask_data`) into controlled writes. The existing read paths and validation continue to apply; the new write path is its own validated, audited surface — not a relaxation of `validate_spec`.

### 6a. Why this is one stage, not two

The natural-language path and the manual grid path share the *same* server-side write surface (`sheet_*` MCP tools). The NL path is just a planner that emits a sequence of those tool calls. Building both at once keeps the audit-log + safety story consistent, and means the grid UI can dogfood every edit the NL path could possibly emit.

### 6b. Surface

Three layers, top → bottom:

1. **Web `/sheet` page** (Stage-2 web service, new template + JS). Collection tabs, paginated grid, click-to-edit cells, add-row / delete-row buttons, an NL command bar across the top, and a toast feed.
2. **Web service routes** (`web/main.py`) that proxy the grid CRUD **and** the NL command directly to MCP via a session-aware JSON-RPC client (the web service holds the MCP session id + optional bearer). Going direct keeps the NL path one round-trip and avoids dragging the agent's tool-loop into a single-purpose write call; the agent path is still available for callers that want it.
3. **MCP tools** (in `mcp/server.py`): `sheet_get_rows`, `sheet_update_cell`, `sheet_insert_row`, `sheet_delete_row`, `sheet_apply_nl`. The first four are thin wrappers over a new write-layer in `mcp/db.py`. `sheet_apply_nl` is a LangGraph workflow (`mcp/sheet_apply.py`) that turns NL into a plan of those same calls.

### 6c. Write-layer in `mcp/db.py`

New, separate from `validate_spec()` so the read-only invariant is untouched. Adds:

- `validate_write_spec(spec)` — allowlists exactly four ops: `insertOne`, `updateOne` (by `_id` only), `deleteOne` (by `_id` only), `replaceOne` (by `_id` only). Rejects update operators outside a small allowlist (`$set`, `$unset`, `$inc`, `$push`, `$pull`, `$addToSet`). Rejects bulk ops, pipelines, multi-document updates.
- `insert_one(collection, doc)`, `update_one(collection, _id, update)`, `delete_one(collection, _id)` — each writes a *before* snapshot, performs the op, writes an *after* snapshot, and appends a row to `audit_log`.
- `audit_log` collection rows: `{action, collection, doc_id, before, after, ts, source}` where `source ∈ {"sheet_cell", "sheet_insert", "sheet_delete", "sheet_apply_nl", "mcp_direct"}`. The audited row's `_id` is stored under `doc_id`; the audit doc itself gets a Mongo-auto `_id`, so multiple edits to the same row don't collide on the audit collection's primary key.
- A `SHEET_WRITES_ENABLED` env gate; when false, every write helper raises `SpecError("writes disabled")` before touching Mongo.
- `get_rows(collection, skip, limit, sort?)` — paginated read used by the spreadsheet grid; returns `{collection, skip, limit, total, rows}`.

Read-only allowlist of collections (`KNOWN_COLLECTIONS`) unchanged; writes target the same three (`employees`, `tickets`, `documents`).

### 6d. NL-edit workflow (`mcp/sheet_apply.py`)

A small async coroutine (no LangGraph `StateGraph` was needed here — the flow is linear and short enough that the graph overhead doesn't pay off; if a re-plan loop is added later, promote this to a `StateGraph`):

1. **discover_schema** — reuses `ask_data._build_catalog()` so the planner sees the same cached schema as the read-side workflow.
2. **plan_ops** — single `structured()` call on the **planner** role. Output schema: `EditPlan = {ops: [SetCell | InsertRow | DeleteRow], match?: MatchFilter, rationale}`. `MatchFilter = {filter, set_for_matches: {field: value}}` is the planner's escape hatch for predicate edits ("everyone in Support hired before 2020").
3. **expand_matches** — if `match` is present, run a read-only `dbmod.find()` with the filter, then expand into per-row `SetCell` ops applying `set_for_matches`.
4. **apply_ops** — iterate ops sequentially through `dbmod.insert_one`/`update_one`/`delete_one` with `source="sheet_apply_nl"`. Each op is its own try/except; failures are recorded into `failed` but don't abort the run.
5. **return** — `SheetApplyResult{collection, instruction, rationale, applied, failed, summary, error?}`, rendered as markdown + JSON in the MCP `content[]` envelope.

Pydantic note: `SetCell.id`, `DeleteRow.id`, `AppliedOp.id`, `FailedOp.id` use `Field(alias="_id")` with `populate_by_name=True` because Pydantic v2 reserves underscore-prefixed attribute names. The server dumps the result with `by_alias=True` so JSON consumers see `_id` as expected.

Caps:

- `SHEET_APPLY_MAX_OPS` (default 50) — refuses to plan/expand more ops than this, including `match` expansion.
- The write-layer per-op limits still apply (one `_id` per op).

### 6e. Spreadsheet front end (`web/`)

Plain Jinja + vanilla JS, no build step (mirrors `index.html`/`app.js`). **Look-and-feel target: Airtable / NocoDB** — left rail of "tables" (Mongo collections), a top toolbar over each table, a dense grid below, inline cell edit with type-aware inputs, and per-cell save state. Keep it CSS-only (no framework) but copy the visual cues: white background, sticky column headers, hairline 1 px borders, a thin "saving…" indicator on the edited cell, row hover state, and a row "+" affordance at the bottom.

- `templates/sheet.html` — fixed left rail listing collections (with their row counts); main pane has a toolbar (collection name, row count, NL command bar, "Add row" button, paging) and the grid; toast region top-right; link back to `/`.
- `static/sheet.js` — fetches rows via `/api/sheet/rows`, renders an HTML `<table>` with sticky `<thead>`. Each editable `<td>` becomes an inline input on click (text / number / date detected from the sampled schema). Blur or Enter commits via `POST /api/sheet/cell`; Escape cancels. The cell shows three states: idle, saving (spinner), saved (brief green flash) / error (red flash + toast). Add-row inserts a blank doc with a generated `_id` (visible in the grid immediately, then committed). Delete-row prompts for confirmation. NL bar posts to `/api/sheet/nl`, streams a "thinking…" toast, then reloads the current page.
- `static/sheet.css` — Airtable-ish: sticky header row, sticky `_id` column, alternating rows, edit-state highlight, error toast, left rail with active-table highlight. Style budget < 300 LoC.

### 6f. Web routes (`web/main.py`)

| Method | Path | Forwards to |
| --- | --- | --- |
| GET | `/sheet` | renders `templates/sheet.html` |
| GET | `/api/sheet/collections` | MCP `mongo_list_collections` |
| GET | `/api/sheet/rows?collection=&skip=&limit=` | MCP `sheet_get_rows` |
| POST | `/api/sheet/cell` | MCP `sheet_update_cell` |
| POST | `/api/sheet/row` | MCP `sheet_insert_row` |
| DELETE | `/api/sheet/row?collection=&_id=` | MCP `sheet_delete_row` |
| POST | `/api/sheet/nl` | MCP `sheet_apply_nl` (direct JSON-RPC; the web service holds the session id + optional `MCP_AUTH_TOKEN`) |

### 6g. Safety rails

- Read-only path **and** write path live in `mcp/db.py`; the read-only `validate_spec` does not change shape. `validate_write_spec` is strictly additive.
- Writes always go through the write-layer (no caller may invoke `motor` `update_one()` directly).
- Every write produces an `audit_log` row, including planner-driven NL writes. The `source` field distinguishes them.
- `SHEET_WRITES_ENABLED=false` (default in `.env.example` → set to `true` in `.env.local` only when desired) disables the write surface and makes the NL planner refuse with an explicit "writes disabled" error.
- The NL planner emits no free-form Mongo updates — it can only emit `SheetOp` variants that one-to-one map to the four allowlisted ops.
- Hard cap on ops per NL call (`SHEET_APPLY_MAX_OPS`, default 50) prevents a runaway bulk edit.

### 6h. Env surface (additions)

| Var | Default | Required | Stage | Notes |
| --- | --- | --- | --- | --- |
| `SHEET_WRITES_ENABLED` | `true` | no | 6 | When `false`, all write helpers fail closed |
| `SHEET_AUDIT_COLLECTION` | `audit_log` | no | 6 | Collection name for the write audit log |
| `SHEET_APPLY_MAX_OPS` | `50` | no | 6 | Hard cap on ops per `sheet_apply_nl` run |

### 6i. Verification (intent)

1. `docker compose up --build -d` brings up mongo + mcp + agent + web; healthchecks green.
2. `GET /sheet` renders the grid for `employees`; clicking a cell, editing it, and tabbing away persists the change (visible in Mongo and in `audit_log`).
3. Add row + delete row round-trip works with confirmation.
4. NL bar: "change Bob Carter's dept to Platform" produces exactly one `audit_log` entry with `before.dept="Engineering"` / `after.dept="Platform"`.
5. NL bar: "set salary_band to IC4 for every Support engineer hired before 2020" expands to N ops, all logged, with `source="sheet_apply_nl"`.
6. With `SHEET_WRITES_ENABLED=false`, every write attempt (grid or NL) returns a clear "writes disabled" error and `audit_log` does not grow.
7. `scripts/smoke_sheet.sh` passes.

---

# Task checklist — Stage 6

### S6.env — Env surface

- [x] **S6.env.1 — Add Stage-6 env vars and update the Env surface table**
  - Files: `.env.example`, IMPLEMENT.md (Env surface table).
  - Done when: `SHEET_WRITES_ENABLED`, `SHEET_AUDIT_COLLECTION`, `SHEET_APPLY_MAX_OPS` present with sensible defaults; both files in sync.

### S6.db — Mongo write layer

- [x] **S6.db.1 — Write-layer in `mcp/db.py` with audit log**
  - Files: `mcp/db.py`.
  - Note: also added `get_rows()` for paginated grid reads. Audit row uses `doc_id` (not `_id`) to avoid collisions on repeat edits to the same row.

### S6.mcp — MCP write tools

- [x] **S6.mcp.1 — Register `sheet_get_rows`, `sheet_update_cell`, `sheet_insert_row`, `sheet_delete_row`**
  - Files: `mcp/server.py`.
  - Note: `tools/list` returns 21 tools; the four `sheet_*` CRUD tools are wired through `multi_content_tools` for uniform error handling.

- [x] **S6.mcp.2 — `sheet_apply_nl` workflow + MCP registration**
  - Files: `mcp/sheet_apply.py` (new), `mcp/server.py`.
  - Note: implemented as a small async coroutine rather than a LangGraph `StateGraph` (linear flow; promote later if a re-plan loop is added). Planner emits `EditPlan{ops, match?, rationale}`; `match.set_for_matches` is expanded server-side into per-row `SetCell` ops, capped by `SHEET_APPLY_MAX_OPS`.

### S6.web — Web service

- [x] **S6.web.1 — Web routes for the sheet surface**
  - Files: `web/main.py`, `compose.yaml`.
  - Note: all routes proxy MCP **directly** (the web service runs its own session-aware JSON-RPC client with `MCP_AUTH_TOKEN` support), including `POST /api/sheet/nl`. The agent path is no longer in the loop for sheet ops. `compose.yaml` was updated to pass `MCP_URL` and `MCP_AUTH_TOKEN` into the web container.

- [x] **S6.web.2 — Spreadsheet UI (`sheet.html`, `sheet.js`, `sheet.css`)**
  - Files: `web/templates/sheet.html`, `web/static/sheet.js`, `web/static/sheet.css`.
  - Note: Airtable/NocoDB look — left rail of tables with badge counts, sticky `<thead>`, sticky `_id` column, hairline borders, per-cell saving/saved/errored state, paging, NL command bar, toast feed.

- [x] **S6.web.3 — Cross-link sheet from chat UI**
  - Files: `web/templates/index.html`, `web/templates/sheet.html`.
  - Note: `/` header has "Open Sheet →"; `/sheet` rail has "← Chat".

### S6.verify — End-to-end

- [x] **S6.verify.1 — `scripts/smoke_sheet.sh`**
  - Files: `scripts/smoke_sheet.sh`.
  - Note: passes against the running stack. Asserts `audit_log` grew by ≥4 rows (insert + cell update + NL update + delete) and also pings `/api/sheet/collections` on the web service for parity.

- [x] **S6.verify.2 — Rebuild + manual UX walkthrough**
  - Note: stack rebuilt (`docker compose build mcp web && docker compose up -d`), all four services healthy, `/sheet` renders, NL bar applied a probe edit and `audit_log` recorded it with `source="sheet_apply_nl"`.

### S6.followups — Known nits (not blockers)

- [ ] **S6.followups.1 — `total` row count drifts after writes**
  - Files: `mcp/db.py::get_rows`.
  - Symptom: the grid header showed `27 rows` immediately after inserting a probe into a 28-row collection because `get_rows()` uses `estimated_document_count()` for `total`.
  - Fix: switch to `count_documents({})` when `skip + limit > total` (or always, accepting the small cost on these tiny collections). One-shottable.

- [ ] **S6.followups.2 — Reactivity after NL edits**
  - Files: `web/static/sheet.js`.
  - Symptom: after an NL edit, the grid reload picks up changes but the column set is derived from rows on the page — newly-`$set` fields not in the current page won't show up until the user navigates to a page that has them.
  - Fix: when the NL response includes a list of `applied`, union those `field`s into `state.columns` before rerendering.

- [ ] **S6.followups.3 — Cell type inference for booleans / arrays**
  - Files: `web/static/sheet.js::inferInputType` + `editCell`.
  - Current behaviour: arrays/objects open as a `<textarea>` of JSON; everything else opens as a single-line text/number input. Booleans become strings on edit.
  - Fix: detect `typeof value === "boolean"` and render a checkbox; for arrays of strings (e.g. `skills`), render a tag editor. Not load-bearing for Stage 7.

---

## Stage 7 — Reactive aggregation builder (Data-Wrangler-shaped)

> **Status: complete.** All `S7.*` tasks done and verified (`scripts/smoke_wrangler.sh` green; `/wrangler` live). The only remaining planned work is Stage 5 (GitHub Copilot as upstream, still TBD) and the Stage-6 follow-up nits (`S6.followups.*`).

**Goal:** A reactive UI on top of Mongo `aggregate()` that feels like **Data Wrangler** — each pipeline stage can be **run on its own**, with the prior stage's output shown as the input preview to the next. The user picks fields, comparators, and values from menus, optionally typed natural-language inputs, and quickly iterates to a useful report. An "agent suggestions" button asks the planner for 2–3 useful seed pipelines (different `$group`/`$project` shapes) to kickstart exploration.

> Read-only by design. Reuses Stage-1's `validate_spec`/`aggregate` plumbing. No new write surface.

### 7a. UX shape

The page is a left rail of "recent collections" (reusing the Stage-6 rail) and a right pane structured as:

1. **Sample header** — a thin band that says e.g. "Sampled 50 most recent `tickets` (by `updated_at desc`)" with a refresh button. On first load and on collection change, the page does a light `find()` against the chosen collection ordered by the best available recency field (`updated_at` / `ts` / `created_at` / `hire_date` / `_id` as fallback) capped at `WRANGLER_SAMPLE_LIMIT` (default 50).
2. **Important fields strip** — a horizontal scroll of "field chips" derived from the sample: each chip shows field name + type + a tiny histogram/cardinality hint. Click a chip to filter; option-click to project; right-click for "group by". This is the Data-Wrangler "tap a column → get suggestions" affordance.
3. **Pipeline column** — a vertical list of stages. Each stage card has:
   - a header (stage type icon, e.g. ⮕ `$match`, Σ `$group`, ⛚ `$project`, ↧ `$sort`, ⊓ `$limit`),
   - a small inline editor (key-value chips for filters; pickers for group keys + accumulators; toggle list for project),
   - **Run-up-to-here** button, which executes the pipeline `[stage_0, …, stage_i]` and shows the output preview *as the input* of the next card,
   - a "remove" / "duplicate" / "drag-handle" affordance.
4. **Preview pane** — below each run stage, a small grid view (sticky header, 25 rows max) showing the materialized rows. The card immediately below uses *that* preview as its "incoming" data label.
5. **Footer toolbar** — "Run all", "Save pipeline" (writes to `db.wrangler_pipelines`), "Load…", "Ask agent for 3 starter queries" button. The page can also export the final pipeline as a copy-paste `mongo_aggregate` MCP call.

The visual cues to copy from Data Wrangler:
- Stage cards stack vertically with a "what's currently selected" summary on the closed card and a full editor on the open card.
- Every stage shows a row-count delta (`50 → 12 rows`) on its header.
- Hovering a row in the preview highlights the same row in the prior-stage preview (best-effort by `_id` join).

### 7b. Stages the builder supports (v1)

A bounded grammar, mapped one-to-one onto Mongo stages and onto `validate_spec`'s existing allowlist (no new validation surface):

| Stage card | Mongo stage | UI |
| --- | --- | --- |
| Filter | `$match` | per-field row of `{field, op, value}`; `op ∈ {=, !=, contains, regex, in, exists, between, >, >=, <, <=}` |
| Group | `$group` | multi-select group keys + accumulator rows `{field, fn}`, `fn ∈ {count, sum, avg, min, max, addToSet, first, last}` |
| Project | `$project` | toggleable include/exclude + computed-field rows (`{$expr}` is supported, no `$function`) |
| Sort | `$sort` | per-field row `{field, dir}` |
| Limit | `$limit` | integer, clamped to `ASK_DATA_LIMIT_CEILING` |
| Lookup | `$lookup` | (deferred to v2 — needs cross-collection allowlist work) |

Computed-field expressions and `$expr` filters go through the existing `_walk_forbidden` scan so `$where`/`$function`/`$accumulator` cannot leak in.

### 7c. Per-stage execution (the Data-Wrangler bit)

Each "Run-up-to-here" call sends the **prefix** of the pipeline to a new MCP tool `wrangler_run_prefix(collection, pipeline, upto)`:

- Builds `pipeline[:upto+1]`.
- Appends `{"$limit": WRANGLER_PREVIEW_LIMIT}` (default 25) if no `$limit` is already at that point.
- Goes through `dbmod.aggregate()`, hitting the same `validate_spec()` everything else does.
- Returns `{stage_index, input_count, output_count, rows}` so the UI can show the row-count delta.

This means **every stage is independently runnable**, instantly, before adding the next — exactly the Wrangler experience.

### 7d. Saved pipelines

`db.wrangler_pipelines` collection:

```
{_id, name, collection, stages: [...], created_by, created_at, updated_at, tags?}
```

Two MCP tools:

- `wrangler_save_pipeline(name, collection, stages, _id?)` — upsert.
- `wrangler_list_pipelines(collection?)` — for the "Load…" menu.

These do not go through the Stage-6 write surface (different collection, different shape, no row-level audit needed). They DO get a single per-write `audit_log` entry tagged `source="wrangler_save"` for parity.

### 7e. Agent-suggested pipelines

A button "Ask agent for 3 starter queries" hits a new MCP tool:

- `wrangler_suggest(collection, sample_summary)` — planner LLM call. System prompt: "given this collection schema and a small sample, propose 2-3 *useful, different-shaped* aggregation pipelines: prefer one count-by-group, one trend-over-time, one rank/top-N. Each must be valid against `validate_spec`."
- Returns structured `{pipelines: [{name, rationale, stages: [...]}]}` — the UI offers each as a one-click "load into the builder".

The planner is bounded to emit only the stage grammar from 7b. Schema is validated server-side by Pydantic + `validate_spec` before being returned.

### 7f. Reactivity

- The sample query auto-refreshes when the collection changes (and when the user clicks the sample-header refresh button).
- Each stage card has a "live re-run on edit" toggle (default on). When on, edits to a stage are debounced (300ms) and the up-to-here preview re-runs.
- The page never holds open WebSockets — every call is a regular HTTP POST. Reactivity is client-side debounce + small payloads (25-row previews keep round-trips snappy).

### 7g. Safety rails

- All execution goes through `dbmod.aggregate()` and `validate_spec()`. The new builder cannot bypass them.
- Stage cap: `WRANGLER_MAX_STAGES` (default 12) — refuses larger pipelines.
- Preview cap: `WRANGLER_PREVIEW_LIMIT` (default 25). Final "Run all" honors `ASK_DATA_LIMIT_CEILING` (50).
- Suggested pipelines from the agent are validated server-side; an invalid suggestion is silently dropped from the response.

### 7h. Env surface (additions)

| Var | Default | Required | Stage | Notes |
| --- | --- | --- | --- | --- |
| `WRANGLER_SAMPLE_LIMIT` | `50` | no | 7 | Rows pulled for the initial sample |
| `WRANGLER_PREVIEW_LIMIT` | `25` | no | 7 | Rows returned by per-stage `wrangler_run_prefix` |
| `WRANGLER_MAX_STAGES` | `12` | no | 7 | Hard cap on stages per pipeline |

### 7i. Verification (intent)

1. `/wrangler` loads with the `tickets` sample populated and field chips visible.
2. Click `status` chip → filter card appears with `op==`, value picker. Selecting `open` and Run-up-to-here shows the filtered preview with `50 → N` delta.
3. Add `$group { _id: "$priority", count: {$sum:1} }` → preview shows grouped counts; row hover highlights the corresponding `priority` rows in the prior preview.
4. Add `$sort {count:-1}` then `$limit 5` → preview shows top-5 priorities.
5. "Save pipeline" persists to `db.wrangler_pipelines`; "Load…" rehydrates it on a new page load.
6. "Ask agent for 3 starter queries" returns 2-3 valid pipelines; one-click load drops them into the builder; each Runs successfully.
7. A pipeline of 13 stages is refused with a clear error referencing `WRANGLER_MAX_STAGES`.

---

# Task checklist — Stage 7

### S7.env — Env surface

- [x] **S7.env.1 — Add Stage-7 env vars**
  - Files: `.env.example`, IMPLEMENT.md (Env surface table).

### S7.db — Sampling helpers

- [x] **S7.db.1 — `sample_recent(collection, limit, sort_by?)` in `mcp/db.py`**
  - Files: `mcp/db.py`.
  - Note: returns `{collection, rows, sort_field, sort_dir}`. Probes one doc and picks the first present field from `["updated_at","ts","created_at","hire_date","_id"]`; honors `LIMIT_CEILING`.

### S7.mcp — Aggregation-builder MCP tools

- [x] **S7.mcp.1 — `wrangler_sample` tool**
  - Files: `mcp/server.py`, `mcp/wrangler.py`.
  - Note: `field_summary` entries are `{field, types, cardinality, coverage, examples}` (added `coverage` = fraction of sampled docs with the field).

- [x] **S7.mcp.2 — `wrangler_run_prefix` tool**
  - Files: `mcp/server.py`, `mcp/wrangler.py`.
  - Note: returns `{collection, stage_index, input_count, output_count, rows}`. `input_count` is the capped output count of `pipeline[:upto]`, so the header delta is apples-to-apples. Honors `WRANGLER_MAX_STAGES`; all execution goes through `db.aggregate()`/`validate_spec()`.

- [x] **S7.mcp.3 — `wrangler_save_pipeline` / `wrangler_list_pipelines` tools**
  - Files: `mcp/server.py`, `mcp/wrangler.py`.
  - Note: upsert by `_id` (auto `wp-<hex>` if absent) into `db.wrangler_pipelines`; each save writes one `audit_log` row tagged `source="wrangler_save"`.

- [x] **S7.mcp.4 — `wrangler_suggest` tool**
  - Files: `mcp/wrangler_suggest.py`, `mcp/server.py`.
  - Note: single `structured()` call on the **planner** role using the field summary. Each suggested pipeline is round-tripped through `validate_spec()`; invalid ones are dropped and reported under `dropped`. Implemented as a plain coroutine (no LangGraph node needed for a single call).

### S7.web — Reactive builder UI

- [x] **S7.web.1 — `/wrangler` page scaffold**
  - Files: `web/main.py`, `web/templates/wrangler.html`, `web/static/wrangler.css`.
  - Note: web routes proxy MCP directly (reusing the Stage-6 session-aware JSON-RPC client): `/api/wrangler/{sample,run,save,pipelines,suggest}`.

- [x] **S7.web.2 — Field chips + stage cards**
  - Files: `web/static/wrangler.js`, `web/static/wrangler.css`.
  - Note: chips show field + type + cardinality; click=filter, alt-click=project, right-click=group-by. Add-stage row also offers Filter/Group/Project/Sort/Limit explicitly. Each card has inline editors, Run-up-to-here, duplicate (⧉), and remove.

- [x] **S7.web.3 — Per-stage preview + row-count deltas**
  - Files: `web/static/wrangler.js`.
  - Note: 25-row mini-grid per card; header shows `input → output rows`. Hover-linking highlights the same `_id` row in the previous stage's preview.

- [x] **S7.web.4 — Live re-run debounce toggle**
  - Files: `web/static/wrangler.js`.
  - Note: per-card `live` checkbox (default on); edits debounce 300ms and re-run that card and every card below it.

- [x] **S7.web.5 — Save / Load pipeline**
  - Files: `web/main.py`, `web/static/wrangler.js`.
  - Note: Save prompts for a name and posts compiled stages; Load opens a side panel listing pipelines for the active collection and rehydrates editable cards via a best-effort decompile (`hydrateFromStages`).

- [x] **S7.web.6 — "Ask agent for 3 starter queries"**
  - Files: `web/main.py`, `web/static/wrangler.js`.
  - Note: side panel shows each suggestion's name + rationale + raw stages + a "Load into builder" button that decompiles into editable cards and auto-runs.

### S7.verify — End-to-end

- [x] **S7.verify.1 — `scripts/smoke_wrangler.sh`**
  - Files: `scripts/smoke_wrangler.sh`.
  - Note: passes against the running stack. Runs the 4-stage tickets pipeline stage-by-stage (deltas `25→20→4→4`), round-trips save+list, and asserts `wrangler_suggest` returns ≥2 validated pipelines (got 3).

- [x] **S7.verify.2 — Build + UX verification**
  - Note: `docker compose build mcp web && docker compose up -d` green; `tools/list` shows the 5 `wrangler_*` tools; `/wrangler` renders; web proxy endpoints (`sample`/`run`/`suggest`) verified via curl — sample returns 8 ticket fields, `run upto=1` gives `20 → 4`, `suggest employees` returns 3 named pipelines (Headcount by Department, Role Distribution by Department, Top 5 Highest Salary Bands).

---

## Stage 5 — GitHub Copilot as an upstream provider (TBD)

**Goal:** Let the stack target a GitHub Copilot Pro/Business/Enterprise subscription as `UPSTREAM_*` so the same agent + MCP plumbing can run on Copilot-hosted models (Claude Sonnet, GPT-4.1, etc.), the way opencode / PiAgent do.

> Status: **TBD.** Not started. Open questions in 5e must be resolved before scheduling.

### 5a. Why this is non-trivial

Copilot is **not** a clean OpenAI base-URL + key. Three extra moving parts versus a vanilla provider:

1. **GitHub device-flow login** → a `ghu_…` GitHub OAuth token (per-user, long-lived).
2. **Token exchange** → `GET https://api.github.com/copilot_internal/v2/token` with `Authorization: token ghu_…` returns a short-lived HMAC bearer (~30 min TTL). Must be cached and refreshed on expiry/401.
3. **Editor-spoof headers** required on every chat request: `Copilot-Integration-Id`, `Editor-Version`, `Editor-Plugin-Version`, `User-Agent`. Drift in any of these can flip the account into a rejected state.

The chat endpoint itself is OpenAI-shaped (`POST https://api.githubcopilot.com/chat/completions`) for most models; Codex models use `/responses` and will be excluded from scope.

### 5b. Two implementation routes

Pick one in S5.decide.1.

**Route A — Sidecar proxy (low effort).** Run a community proxy (e.g. [`ericc-ch/copilot-api`](https://github.com/ericc-ch/copilot-api), last release 2025-10-05 — slow cadence but not archived) as a new compose service. It handles device flow, token cache, refresh, and header spoofing, and exposes a local `/v1/chat/completions`. The agent and MCP point at it via `UPSTREAM_BASE_URL=http://copilot-api:4141/v1`. Nothing in our Python changes.

- Pros: ~30 min to wire; zero changes to `agent/` or `mcp/`.
- Cons: third-party dependency on a project with slow updates; breakage when GitHub rotates headers; tool-call support varies by model.

**Route B — Native client in this repo (more work).** Add a Copilot auth module to `mcp/` and inject editor headers into the existing `httpx.AsyncClient` calls. ~150 LoC across:
- `mcp/copilot_auth.py` — device-flow init, `ghu_` storage (host-mounted file), bearer cache with TTL + refresh.
- `mcp/llm.py` — when `UPSTREAM_PROVIDER=copilot`, wrap `AsyncOpenAI` to attach Copilot headers and call the auth module for the bearer.
- `agent/main.py` — same wrapping for the direct upstream call.

- Pros: no extra container; we own the breakage surface.
- Cons: we own the breakage surface; device-flow UX in a headless container needs care (one-time `docker compose exec mcp python -m mcp.copilot_auth login`).

### 5c. Constraints we already know will bite

- **Against Copilot's ToS.** Non-editor use is not sanctioned; accounts have been rate-limited or banned for heavy abuse patterns. Our `web_research` fan-out and the Stage-4 builder loop are exactly the kind of bursty parallel traffic that draws attention. Mitigation in S5.safety.
- **Rate limits are tighter** than the current self-hosted SGLang/vLLM endpoint. The `LLM_CONCURRENCY=2` / `ASK_DATA_MAX_DOCS=4` tuning from Stage 1 will need to drop further (likely 1 concurrent + smaller fan-out).
- **No grammar-enforced constrained JSON.** Copilot does not expose vLLM's `response_format=json_schema` strict grammar. `mcp/llm.py::structured()` will need a fallback path: prompt-only JSON + Pydantic validate + bounded retry. The existing fallback in `structured()` already covers this, but it must become the *primary* path for Copilot.
- **Tool-calling varies by model.** GPT-4.1 / Claude Sonnet through Copilot generally honor OpenAI `tools`; Codex models do not. Restrict the configured `UPSTREAM_MODEL` to a known-good tool-calling model.
- **Two-endpoint Stage-4 split assumes both endpoints obey the same OpenAI shape.** Copilot can be the `PLANNER_*` endpoint only if S5.builder.1 below confirms tool-call behavior under fan-out; otherwise keep `BUILDER_*` on the self-hosted box.

### 5d. Env surface (proposed)

| Var | Default | Required | Notes |
| --- | --- | --- | --- |
| `UPSTREAM_PROVIDER` | `openai` | no | When set to `copilot`, enables Copilot auth/headers path (Route B) or simply selects the sidecar service (Route A). |
| `COPILOT_TOKEN_FILE` | `/data/copilot/ghu_token` | no | Host-mounted file holding the `ghu_…` token from device flow. |
| `COPILOT_BEARER_TTL` | `1500` | no | Seconds to cache the exchanged bearer before forced refresh (Copilot returns ~30 min; refresh slightly early). |
| `COPILOT_EDITOR_VERSION` | `vscode/1.104.1` | no | Editor-spoof header; bump when GitHub starts rejecting. |
| `COPILOT_PLUGIN_VERSION` | `copilot-chat/0.26.7` | no | Editor-plugin-version header. |
| `COPILOT_INTEGRATION_ID` | `vscode-chat` | no | Integration-id header. |

### 5e. Open questions (resolve before scheduling)

1. **Route A or B?** Decide based on tolerance for an extra container vs. owning ~150 LoC of auth code.
2. **Which Copilot model id?** Confirm tool-calling works under our agent loop with the chosen model before committing. Candidates: `claude-sonnet-4.5`, `gpt-4.1`. Codex variants out.
3. **Where does device-flow login happen?** Headless container UX needs a clear `make copilot-login` (or equivalent) target. Where does `ghu_…` live on disk — host bind-mount or Docker secret?
4. **Does Stage-4 split survive Copilot rate limits?** If not, either keep `BUILDER_*` on the self-hosted endpoint (Copilot for planner only) or postpone Stage 4 + Copilot combination.
5. **Constrained-JSON fallback acceptable?** Verify `ask_data` and `web_research` still return parseable JSON via the no-schema-enforcement path with one retry, on the chosen model.

### 5f. Verification (intent)

1. With `UPSTREAM_PROVIDER=copilot`, `curl -s ${PUBLIC_HOSTNAME}/v1/chat/completions … "model":"<copilot-model>"` returns a completion.
2. Agent tool loop dispatches an `ask_data` tool call end-to-end via Copilot and returns a cited answer.
3. Bearer refresh: kill the cached bearer (or wait past TTL), next call succeeds with a fresh exchange.
4. `LLM_CONCURRENCY=1` + reduced `ASK_DATA_MAX_DOCS` produces no Copilot 429s across the three smoke tests.
5. Route choice documented in `docs/clients.md` (Copilot as upstream — not as a client).

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
| `SHEET_WRITES_ENABLED` | `true` | no | 6 | When `false`, all sheet write helpers fail closed |
| `SHEET_AUDIT_COLLECTION` | `audit_log` | no | 6 | Audit-log collection for sheet writes |
| `SHEET_APPLY_MAX_OPS` | `50` | no | 6 | Hard cap on ops per `sheet_apply_nl` run |
| `WRANGLER_SAMPLE_LIMIT` | `50` | no | 7 | Rows pulled for the initial sample |
| `WRANGLER_PREVIEW_LIMIT` | `25` | no | 7 | Rows returned by per-stage `wrangler_run_prefix` |
| `WRANGLER_MAX_STAGES` | `12` | no | 7 | Hard cap on stages per pipeline |

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

## Stage 5 — GitHub Copilot as upstream (TBD)

> All tasks below are **TBD**. Resolve the §5e open questions and pick a route (S5.decide.1) before any other task is started.

### S5.decide — Route selection

- [ ] **S5.decide.1 — Pick Route A (sidecar) vs Route B (native client)**
  - Files: this doc (record the decision in §5b).
  - Done when: decision recorded with rationale; downstream tasks pruned to match the chosen route.
  - Depends on: §5e Q1.

- [ ] **S5.decide.2 — Pick the Copilot model id**
  - Done when: a Copilot model is chosen, manually verified to honor OpenAI `tools` against the agent's tool loop, and recorded in `.env.example` as a comment.
  - Depends on: §5e Q2.

### S5.deps — Dependencies and env surface

- [ ] **S5.deps.1 — Add Stage-5 env vars to `.env.example`**
  - Files: `.env.example`, Env surface table.
  - Done when: `UPSTREAM_PROVIDER`, `COPILOT_TOKEN_FILE`, `COPILOT_BEARER_TTL`, `COPILOT_EDITOR_VERSION`, `COPILOT_PLUGIN_VERSION`, `COPILOT_INTEGRATION_ID` all present with defaults from §5d.
  - Depends on: —

- [ ] **S5.deps.2 — Host-mounted token directory**
  - Files: `compose.yaml`, `.gitignore`.
  - Done when: `./copilot/` bind-mounts to `/data/copilot` in whichever service owns the token (sidecar for Route A, `mcp` + `agent` for Route B), uid 1000, gitignored.
  - Depends on: S5.decide.1.

### S5.proxy — Route A only (sidecar)

- [ ] **S5.proxy.1 — Add `copilot-api` service to `compose.yaml`**
  - Files: `compose.yaml`.
  - Done when: service starts, joins the `proxy` network, exposes `4141` to the in-stack network only, healthcheck green.
  - Depends on: S5.decide.1 (chose A), S5.deps.2.

- [ ] **S5.proxy.2 — One-shot device-flow login**
  - Files: `scripts/copilot_login.sh` (new).
  - Done when: script runs the sidecar's login flow against `github.com/login/device`, persists `ghu_…` under `./copilot/`, and a follow-up `curl http://localhost:4141/v1/models` succeeds.
  - Depends on: S5.proxy.1.

- [ ] **S5.proxy.3 — Point upstream at the sidecar**
  - Files: `.env.local` (documented in `.env.example`).
  - Done when: `UPSTREAM_BASE_URL=http://copilot-api:4141/v1`, `UPSTREAM_MODEL=<chosen>`, `UPSTREAM_API_KEY=dummy`; `docker compose up -d` brings agent+mcp up against the sidecar.
  - Depends on: S5.proxy.2, S5.decide.2.

### S5.native — Route B only (in-repo client)

- [ ] **S5.native.1 — `mcp/copilot_auth.py` (device flow + bearer cache)**
  - Files: `mcp/copilot_auth.py`.
  - Done when: `python -m mcp.copilot_auth login` walks device flow and writes `ghu_…`; `get_bearer()` returns a cached short-lived token, refreshes on 401 or TTL expiry; thread-safe via `asyncio.Lock`.
  - Depends on: S5.decide.1 (chose B), S5.deps.1, S5.deps.2.

- [ ] **S5.native.2 — Copilot-aware client wrapper in `mcp/llm.py`**
  - Files: `mcp/llm.py`.
  - Done when: when `UPSTREAM_PROVIDER=copilot`, the `AsyncOpenAI` instance is built with a custom `httpx.AsyncClient` that injects the four editor headers and pulls the bearer from `copilot_auth.get_bearer()` per request. Existing non-Copilot path unchanged.
  - Depends on: S5.native.1.

- [ ] **S5.native.3 — Same wrapping in `agent/main.py`**
  - Files: `agent/main.py`.
  - Done when: agent's direct upstream call uses the same Copilot wrapper. Header set identical to `mcp/llm.py`.
  - Depends on: S5.native.2.

- [ ] **S5.native.4 — Document login UX**
  - Files: `docs/clients.md` (new "Copilot as upstream" section).
  - Done when: paste-ready `docker compose exec mcp python -m mcp.copilot_auth login` recipe, plus where `ghu_…` lands and how to revoke.
  - Depends on: S5.native.1.

### S5.json — Constrained-JSON fallback

- [ ] **S5.json.1 — Make prompt-only JSON the primary path when provider=copilot**
  - Files: `mcp/llm.py::structured`.
  - Done when: under Copilot, `structured()` skips `response_format=json_schema` (no grammar enforcement upstream), uses prompt-only JSON + Pydantic validate + 1 retry; logs which path was taken.
  - Depends on: S5.decide.1.

### S5.safety — Rate-limit and abuse-pattern mitigation

- [ ] **S5.safety.1 — Drop concurrency defaults under Copilot**
  - Files: `mcp/ask_data.py`, `.env.example` (documented).
  - Done when: when `UPSTREAM_PROVIDER=copilot`, default `LLM_CONCURRENCY=1` and `ASK_DATA_MAX_DOCS=2` unless explicitly overridden. Documented in §5c.
  - Depends on: S5.decide.1.

- [ ] **S5.safety.2 — Backoff on 429/403**
  - Files: `mcp/llm.py` (or the wrapper from S5.native.2 / S5.proxy.1 dependency).
  - Done when: on 429 or 403 from Copilot, exponential backoff with jitter, max 3 retries, then surface a clear error. No silent loops.
  - Depends on: S5.decide.1.

### S5.verify — End-to-end

- [ ] **S5.verify.1 — Direct curl against agent**
  - Done when: `curl ${PUBLIC_HOSTNAME}/v1/chat/completions` with the Copilot model returns a completion; logs show the Copilot endpoint was used.
  - Depends on: route-specific tasks above.

- [ ] **S5.verify.2 — `ask_data` end-to-end via Copilot**
  - Done when: the three-shape smoke from `scripts/smoke_ask_data.sh` passes against Copilot. Constrained-JSON fallback handles any schema misses.
  - Depends on: S5.verify.1, S5.json.1.

- [ ] **S5.verify.3 — Bearer refresh works**
  - Done when: with the cached bearer manually invalidated (or after TTL), the next call triggers a refresh and succeeds without restart.
  - Depends on: S5.verify.1.

- [ ] **S5.verify.4 — Sustained-burst rate-limit check**
  - Done when: running the Stage-1 smoke 10× back-to-back produces no Copilot 429s under the dropped concurrency defaults from S5.safety.1.
  - Depends on: S5.safety.1, S5.verify.2.

- [ ] **S5.verify.5 — Decide on Stage-4 + Copilot compatibility**
  - Done when: either `deep_agent` runs cleanly with planner on Copilot + builder on self-hosted (recorded in §4c env block), or the combo is marked out-of-scope and §5e Q4 is closed.
  - Depends on: S5.verify.4.

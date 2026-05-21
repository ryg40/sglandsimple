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

> **Status: complete.** All `S7.*` tasks done and verified (`scripts/smoke_wrangler.sh` green; `/wrangler` live). Next planned work is **Stage 8** (React + shadcn/ui admin-panel rewrite of the front end); after that, Stage 5 (GitHub Copilot as upstream, still TBD) and the Stage-6 follow-up nits (`S6.followups.*`).

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

## Stage 8 — React + shadcn/ui admin panel (visual overhaul)

> **Status: complete** (code + serving verified; in-browser visual/a11y walkthrough still open — see `S8.verify.2`). The React + shadcn/ui SPA replaced the Jinja/vanilla pages; one additive MCP tool (`audit_recent`) was needed for the Overview feed — otherwise the `/api/*` surface is preserved. Build: `docker compose build web` (multi-stage node→python), served by FastAPI on `${WEB_PORT}`.

**Goal:** Replace the no-build Jinja + vanilla-JS pages with a single **React + TypeScript + Vite + Tailwind v4 + shadcn/ui** SPA that presents Chat, Sheet, and Wrangler as panels of one cohesive, visually polished **admin dashboard**. Robustness is a first-class requirement: every data view has loading/empty/error states, every mutation is optimistic with rollback, the whole thing is keyboard- and screen-reader-navigable with a persisted light/dark theme, and all server payloads flow through a typed API client backed by TanStack Query.

### 8a. Decisions (locked)

- **Full React SPA rewrite** (not a CSS-only reskin, not a hybrid). `web/templates/*` and `web/static/*.{js,css}` are removed once parity is reached.
- **Build/serve topology: multi-stage Docker, FastAPI serves the SPA.** Stage 1 (`node:20`) runs `vite build` → `dist/`; stage 2 (`python:3.12-slim`) copies `dist/` + `main.py`. FastAPI mounts the built assets and serves `index.html` as the SPA fallback for any non-`/api` route. Still one `web` container, still `:3000`, no new compose service.
- **"Robust" scope (locked):** (1) loading/empty/error states + toasts + optimistic mutations with rollback; (2) a11y + light/dark theming with persisted preference; (3) a type-safe API layer (shared TS types + typed fetch client + TanStack Query). *Automated component tests / CI gates are out of scope for this stage* (can be a follow-up).
- **Visual reference:** the Dribbble "Fintech Admin Dashboard" shot ([CDN image](https://cdn.dribbble.com/userupload/46653846/file/0f601882bc358a009ee16725d325eb15.png)). Translate its language into our tokens — see 8c.

### 8b. Topology & layout

The SPA is one app shell with three routed panels, reachable from a persistent left sidebar (replacing the three separate pages):

```
AppShell
  ├─ Sidebar (collapsible)        grouped nav: Overview · Chat · Sheet · Wrangler;
  │                               theme toggle + a pinned status card at the bottom
  ├─ Topbar                       page title / breadcrumb, command search (⌘K),
  │                               connection/health pill, primary actions per route
  └─ <Outlet/>
       ├─ /            Overview    dashboard: stat cards (collection counts, recent
       │                           audit activity), a recent-transactions-style table
       │                           fed by audit_log, quick links into the three tools
       ├─ /chat        Chat        the existing agent chat (markdown + code), restyled
       ├─ /sheet       Sheet       the Stage-6 grid as a shadcn DataTable
       └─ /wrangler    Wrangler    the Stage-7 builder as shadcn Cards + DataTable previews
```

The **Overview** route is new — it's the "admin panel" landing surface the visual reference is built around. It reuses existing read endpoints (`/api/sheet/collections`, a new lightweight `/api/audit/recent` proxy — see 8g) and is the showcase for the fintech-dashboard styling.

### 8c. Design language (from the reference)

Translate the reference into shadcn/Tailwind tokens rather than hard-coded colors:

- **Theme:** light default with a real dark mode. Soft neutral canvas (`--background` ~ `oklch(0.985 0 0)`), white elevated cards (`--card`) with hairline borders (`--border`) and a very soft shadow. Generous radii (`--radius: 0.875rem`).
- **Sidebar:** grouped sections with small muted labels, icon + label rows, an active "pill" highlight, collapsible to icons-only. A pinned card at the bottom (status/health), mirroring the reference's promo card.
- **Topbar:** greeting/breadcrumb left, centered command search, pill-shaped **primary** (dark) action buttons right.
- **Cards:** big tabular-numeric figures with small muted captions; positive deltas green, negative red/orange; chips with soft tinted backgrounds for statuses (Completed/Pending/etc.).
- **Charts:** smooth area/line via `recharts` (shadcn's chart wrapper) — an Overview trend card and a Money-movement-style stacked bar.
- **Tables:** dense rows, avatar/logo cell, status chips, right-aligned monospaced amounts, hover row state. Use shadcn `DataTable` (TanStack Table).
- **Typography:** Inter (or system) with clear hierarchy; `font-variant-numeric: tabular-nums` on all figures.

### 8d. Stack & dependencies

- `vite`, `react`, `react-dom`, `typescript`, `@vitejs/plugin-react`.
- `tailwindcss@4` + `@tailwindcss/vite` (Tailwind v4, CSS-first config via `@theme`).
- `shadcn/ui` (Radix primitives + class-variance-authority + tailwind-merge + lucide-react icons). Components added on demand: `button`, `card`, `input`, `table`/data-table, `dialog`, `dropdown-menu`, `tabs`, `sonner` (toasts), `skeleton`, `badge`, `tooltip`, `command`, `switch`/`theme-toggle`, `chart`.
- `@tanstack/react-query` (server-state cache/retry/invalidation) + `@tanstack/react-table` (data grids).
- `react-router-dom` (routing), `recharts` (charts), `react-markdown` + `highlight.js`/`rehype-highlight` (chat rendering, replacing the CDN `marked`).

### 8e. Type-safe API layer

- `src/lib/types.ts` — TS interfaces for every payload the existing routes return: `Collection`, `SheetRowsResponse`, `CellUpdateResult`, `SheetApplyResult`, `WranglerSample`, `FieldSummary`, `RunPrefixResult`, `Pipeline`, `SuggestResult`, plus the chat completion shape.
- `src/lib/api.ts` — a thin typed `fetch` wrapper (`get<T>`, `post<T>`, `del<T>`) that throws a typed `ApiError` (status + parsed body) on non-2xx. No URL is hand-built in components.
- `src/lib/queries.ts` — TanStack Query hooks: `useCollections`, `useSheetRows`, `useUpdateCell` (optimistic), `useInsertRow`, `useDeleteRow`, `useApplyNl`, `useWranglerSample`, `useRunPrefix`, `useSavePipeline`, `usePipelines`, `useSuggest`, `useRecentAudit`. Mutations invalidate the right query keys; cell/insert/delete are optimistic with rollback on error.

### 8f. Robustness requirements (acceptance-bearing)

- **States:** every panel renders a `Skeleton` while loading, an empty-state component when there's no data, and an inline error card with a retry button on failure. A top-level React error boundary catches render crashes and shows a recoverable fallback.
- **Mutations:** cell edits, row insert/delete, and NL apply are optimistic; on error the cache rolls back and a destructive `sonner` toast explains why. Success shows a subtle confirmation.
- **A11y:** all interactive controls reachable by keyboard; visible focus rings; dialogs/menus use Radix (focus trap + escape). The Sheet grid supports arrow-key cell navigation and Enter-to-edit. Charts have text alternatives (a data summary). Run `axe` manually; no serious violations.
- **Theming:** a `ThemeProvider` toggles `.dark` on `<html>`, persists to `localStorage`, and defaults to `prefers-color-scheme`. Tokens defined once in `@theme`; no component hard-codes a hex.

### 8g. New back-end surface (minimal)

Only one additive read endpoint is needed; everything else reuses existing routes:

- `GET /api/audit/recent?limit=` → web proxies a new MCP read tool **`audit_recent`** (or, if we'd rather not add an MCP tool, a direct read via the existing `mongo_query` tool against `audit_log`). Returns the latest audit rows for the Overview "recent activity" table. *Decision recorded in S8.api.1.*

FastAPI changes: mount `dist/assets`, add a catch-all that returns `index.html` for non-`/api`, non-asset GETs (SPA fallback), keep all `/api/*` handlers byte-for-byte.

### 8h. Migration / parity

- Build the SPA alongside the old pages; cut over only when Chat + Sheet + Wrangler reach feature parity (every existing button/flow works).
- Delete `web/templates/` and `web/static/*.{js,css}` in the same commit that flips FastAPI to serve `dist/`.
- `.dockerignore` excludes `node_modules`; `web/dist/` is gitignored (built in CI/Docker, not committed).

### 8i. Env surface (additions)

| Var | Default | Required | Stage | Notes |
| --- | --- | --- | --- | --- |
| `WEB_BUILD_MODE` | `production` | no | 8 | `vite build` mode; `development` enables source maps |
| `AUDIT_RECENT_LIMIT` | `25` | no | 8 | Default rows for the Overview activity table |

(No new ports or services. `WEB_PORT` unchanged.)

### 8j. Verification (intent)

1. `docker compose build web` runs the Node build stage then the Python stage; `docker compose up -d` brings `web` up healthy on `${WEB_PORT}`.
2. `/` renders the Overview dashboard with stat cards, a trend chart, and a recent-activity table — visually consistent with the reference (light theme).
3. Theme toggle flips to dark, persists across reload, and respects `prefers-color-scheme` on first load.
4. `/sheet` reaches full Stage-6 parity (cell edit, add/delete row, NL bar) with optimistic updates + rollback verified by forcing a failing edit.
5. `/wrangler` reaches full Stage-7 parity (chips, per-stage run + deltas, save/load, suggest).
6. Loading skeletons, empty states, and error-with-retry are each observable (e.g. by stopping `mcp`).
7. Keyboard-only walkthrough of all three panels works; no serious `axe` violations.
8. `scripts/smoke_web_spa.sh` passes (built `index.html` served, hashed assets resolve, SPA fallback returns `index.html` for `/sheet`, `/api/*` still returns JSON).

---

# Task checklist — Stage 8

### S8.scaffold — Vite + React + Tailwind v4 + shadcn

- [x] **S8.scaffold.1 — Vite React+TS app under `web/`**
  - Files: `web/package.json`, `web/tsconfig*.json`, `web/vite.config.ts`, `web/index.html`, `web/src/main.tsx`, `web/.gitignore`.
  - Note: React 18 + Vite 6 + TS 5.7. `npm run build` (tsc -b + vite build) emits `web/dist/`. `@types/node` added for the vite config. Dev proxy sends `/api` → `:5452`.

- [x] **S8.scaffold.2 — Tailwind v4 + design tokens**
  - Files: `web/src/index.css`, `web/vite.config.ts`.
  - Note: Tailwind v4.3 via `@tailwindcss/vite`. Tokens in oklch (`@theme inline`), light + `.dark`, including sidebar + chart series. Class-based dark mode via `@custom-variant`.

- [x] **S8.scaffold.3 — shadcn/ui base components**
  - Files: `web/src/components/ui/*`, `web/src/lib/utils.ts`.
  - Note: components hand-written (MIT shadcn source) rather than via the CLI (no interactive init / `components.json`): button, card, input, badge, skeleton, dialog, dropdown-menu, tabs, tooltip, sonner. `cn()` in lib/utils.

### S8.api — Type-safe data layer

- [x] **S8.api.1 — `audit_recent` read**
  - Files: `mcp/db.py`, `mcp/server.py`, `web/main.py`, `compose.yaml`.
  - **Decision: dedicated MCP tool `audit_recent`** (not loosening `mongo_query`) — keeps `audit_log` out of the read allowlist. `db.audit_recent(limit)` sorts by `ts` desc; web `GET /api/audit/recent?limit=` proxies it and defaults to `AUDIT_RECENT_LIMIT`.

- [x] **S8.api.2 — Shared TS types**
  - Files: `web/src/lib/types.ts`. No `any` in the data layer.

- [x] **S8.api.3 — Typed fetch client + `ApiError`**
  - Files: `web/src/lib/api.ts`. `get/post/del<T>` + `qs()` helper; throws `ApiError{status, body}` with a best-effort message.

- [x] **S8.api.4 — TanStack Query hooks**
  - Files: `web/src/lib/queries.ts`, `web/src/main.tsx`.
  - Note: `useUpdateCell` and `useDeleteRow` are optimistic with rollback via `onMutate`/`onError`; all mutations invalidate sheet rows + collections + audit. `useRecentAudit` polls every 15s.

### S8.shell — App shell, routing, theming

- [x] **S8.shell.1 — Router + AppShell**
  - Files: `web/src/App.tsx`, `web/src/components/app-sidebar.tsx`, `web/src/components/topbar.tsx`.
  - Note: collapsible grouped sidebar (Workspace/Tools) with active pill + a pinned connection/total-records status card; topbar with title/subtitle + command-search affordance.

- [x] **S8.shell.2 — Theme provider + toggle (persisted)**
  - Files: `web/src/components/theme-provider.tsx`, `web/src/components/theme-toggle.tsx`.
  - Note: implemented via **`next-themes`** (class attribute, `storageKey="sgl-theme"`, `enableSystem`) rather than a hand-rolled provider — sonner reads the same provider.

- [x] **S8.shell.3 — Error boundary + global toaster**
  - Files: `web/src/components/error-boundary.tsx`, `web/src/components/ui/sonner.tsx` (mounted in `main.tsx`).

### S8.overview — Dashboard landing (the showcase)

- [x] **S8.overview.1 — Stat cards + trend chart**
  - Files: `web/src/routes/overview.tsx`, `web/src/components/stat-card.tsx`.
  - Note: per-collection stat cards + a "write events" card; recharts area chart of audit events/day; a collection-count bar list. Skeletons while loading.

- [x] **S8.overview.2 — Recent-activity table**
  - Files: `web/src/components/activity-table.tsx`.
  - Note: audit feed with action chips (insert=success, delete=destructive, update=warning), source, relative timestamps; loading/empty/error+retry states.

### S8.panels — Port the three tools

- [x] **S8.panels.1 — Chat panel**
  - Files: `web/src/routes/chat.tsx`, `web/src/components/markdown.tsx`.
  - Note: send + ask-data, `react-markdown` + `remark-gfm` + `rehype-highlight` (github theme), thinking indicator, error toasts.

- [x] **S8.panels.2 — Sheet panel**
  - Files: `web/src/routes/sheet.tsx`.
  - Note: built as an inline editable grid in the route (no separate `data-grid.tsx`). Collection tabs, click-to-edit cells (optimistic + rollback), add/delete row, paging, NL bar, sticky header + sticky `_id` column. Enter commits / Escape cancels.

- [x] **S8.panels.3 — Wrangler panel**
  - Files: `web/src/routes/wrangler.tsx`, `web/src/lib/pipeline.ts`.
  - Note: field chips (click/alt-click/right-click), stage cards (match/group/project/sort/limit) with per-stage Run-up-to-here + `input → output` delta + 25-row preview, per-card live-rerun (300ms debounce), save/load side panel, "Ask agent" suggestions side panel. compile/decompile logic in `lib/pipeline.ts`.

### S8.docker — Build & serve

- [x] **S8.docker.1 — Multi-stage Dockerfile + FastAPI SPA serving**
  - Files: `web/Dockerfile`, `web/main.py`, `web/.dockerignore`, `web/requirements.txt`, `compose.yaml`, `.env.example`.
  - Note: node:20 build stage → dist; python:3.12 stage serves it (`/assets` mount + `{full_path}` SPA fallback that 404s `api/*`). `WEB_BUILD_MODE` build-arg + `AUDIT_RECENT_LIMIT` env wired in compose. jinja2 dropped from requirements.

- [x] **S8.docker.2 — Remove legacy Jinja/vanilla pages**
  - Files: deleted `web/templates/`, `web/static/`; removed the three template routes from `main.py`.
  - Note: docstring updated to describe the SPA + API surface; build green; nothing references the removed files.

### S8.verify — End-to-end

- [x] **S8.verify.1 — `scripts/smoke_web_spa.sh`**
  - Files: `scripts/smoke_web_spa.sh`.
  - Note: PASS — index served, hashed asset 200s, `/sheet` falls back to index, `/api/sheet/collections` + `/api/audit/recent` return JSON, unknown `/api/*` 404s.

- [x] **S8.verify.2 — Build + verification**
  - Note: `docker compose build web mcp` (multi-stage) + `up -d` green; all 4 services healthy; `tools/list` shows 27 tools incl. `audit_recent`. Data paths for all three panels verified via curl through the new SPA proxy (collections, audit feed, wrangler sample + run `20 → 4`). **Not done headlessly:** the in-browser visual/keyboard/a11y/dark-mode-persistence walkthrough (§8j 2–7) needs a human at a browser — open `http://<host>:${WEB_PORT}/` to complete it.

---

## Stage 9 — Compliance workflow hub (integrations dashboard)

> **Pick-up point.** Stage 8 (the React/shadcn admin SPA) is the substrate this builds on. Stage 9 turns the Overview into a **workflow hub**: a grid of connection "bubbles" (one per external system) plus a guided, end-to-end **audit-finding → Jira → code → PR → docs → report** flow that stitches every system together. Start at `S9.model.1` and proceed in task order. This is a **large** stage — it is decomposed so each integration and each workflow step can land independently behind a feature flag.

**Goal:** A person opens the dashboard, clicks into a section, and immediately sees *all the related pieces of one standard compliance workflow* — the originating audit finding, the Jira epic/stories, the coding work and PR, the Confluence documentation, and the real database audit logs that prove the control — aggregated across many systems and exportable as a layman-friendly PDF/PPT artifact.

### 9a. The domain (why this exists)

The core subject is **database audit logging** — login events, SQL errors, and SQL queries — which a regulation-driven **audit finding** requires be generated and retained across **dozens of DB engine × platform combinations**, both on-prem and cloud. That work is sliced into Jira **epics**; **RDS logging is the current priority epic**. The dashboard exists to make the otherwise-scattered evidence of "we satisfied this control" legible in one place and produce an artifact non-technical stakeholders (managers, audit managers) can read.

The standard workflow the hub must represent and (progressively) drive:

1. **Identify the audit finding** — capture the originating finding, its regulatory requirements, and store it in an `audit_findings` collection.
2. **Relate work to the finding + active Jira epic** — link the finding to the epic that will carry the implementation/operational stories.
3. **Auto-generate the Jira ticket** from the epic's template (best-practice fields/values).
4. **Coding agent picks up the work** — implements the feature on a branch named for the Jira ticket.
5. **PR template + pipeline** — opens a PR that triggers the compliance GitHub Actions and requests review from Copilot + 2 team members.
6. **Post-approval** — Jira ticket updated; work documented in Confluence under that epic's **Epic Log**; every piece persisted to MongoDB collections for future pipelines + enrichment.
7. **Log warehouse** — real DB audit logs live in the MongoDB warehouse so example logs can be referenced.
8. **Aggregate** — the dashboard pulls findings, epics, tickets, PRs, docs, and real logs together so a user can produce an artifact showing real DB logs and all their associations.
9. **Report** — PDF/PPT skills aggregate the above and surface the most pertinent info for a layman/manager/audit-manager audience.

### 9b. Connections (the "bubbles")

Each external system is a **connection bubble** on the dashboard: a card showing health/auth status, a one-line summary metric, the last sync time, and a click-through into a detail panel. Connections are described by a common adapter contract so the UI treats them uniformly even though transports differ.

| Bubble | Transport | Primary use in the workflow | Status |
| --- | --- | --- | --- |
| **Atlassian Jira** | MCP | Epics, stories, ticket auto-generation (steps 2–3, 6) | new |
| **Atlassian Confluence** | MCP | Epic Log documentation (step 6) | new |
| **GitHub** | MCP | Branch/PR/Actions/reviews (steps 4–5) | new |
| **AWS** | MCP | RDS inventory + log config evidence (priority epic) | new |
| **ServiceNow** | REST API | Finding/CR intake + change records | new |
| **Snowflake** | `tool_calls` (SQL) | Query warehoused audit logs (cloud) | new |
| **MongoDB** | existing `mongo_*` tools | System of record + log warehouse (steps 1,6,7) | exists |
| **Archer (RIMS)** | placeholder | Risk/audit-finding source + enrichment | placeholder |

**Decisions to lock in `S9.connect.1`** (don't guess — these gate real credentials and external calls):
- Which Jira/Confluence/GitHub/AWS MCP servers (image + version + auth model) — these are external; the stack consumes them, it does not vendor them.
- ServiceNow + Snowflake: thin server-side adapters in `mcp/` (REST and SQL respectively) exposed as MCP tools, mirroring how `mongo_*`/`wrangler_*` are exposed — so the agent and the web proxy reach them the same way.
- Archer ships as a **placeholder adapter** (typed contract + mock data) until a real API is available; the UI bubble renders "not connected" gracefully.

### 9c. Architecture (server-side first)

Keep the established shape: **all integration logic is server-side** (in `mcp/`), the **web service only proxies**, and the **agent tool-loop** can drive the same tools. Add:

- `mcp/connectors/` — one module per system implementing a small `Connector` protocol: `health()`, `summary()`, and the system-specific read/write tools. MCP-backed systems (Jira/Confluence/GitHub/AWS) are reached by `mcp/` acting as an **MCP client** to those upstream MCP servers; ServiceNow/Snowflake are direct adapters; Archer is a mock.
- A **connection registry** so `tools/list` advertises each connector's tools and the dashboard can enumerate bubbles + health.
- New MongoDB collections as the system of record (see 9d). Writes go through an audited path like the Stage-6 write-layer (`source="workflow_*"`).
- A **workflow orchestrator** (LangGraph) that walks steps 1→6 with human-in-the-loop interrupts at the approval gates, persisting each artifact + its cross-links as it goes. Reuse the checkpointer.

> Secrets: every connector's credentials live in `.env.local` only, injected via `${...:?}` in compose. No tokens in committed files. Outbound calls to real systems are **gated behind per-connector enable flags** (default off) so the stage can land and be demoed with mocks before live wiring.

### 9d. Data model (MongoDB — system of record)

New collections, each cross-linked by id so the hub can "relate all the pieces":

- `audit_findings` — `{_id, source (archer|servicenow|manual), regulation, requirement, severity, status, epic_id?, created_at}`.
- `epics` — `{_id, jira_key, title, regulation_refs[], db_platform_combos[], priority, status}` (RDS epic seeded as priority).
- `work_items` — `{_id, finding_id, epic_id, jira_key, branch, pr_url, status}` (the story per finding).
- `pr_records` — `{_id, work_item_id, github_pr, checks[], reviewers[], state}`.
- `doc_records` — `{_id, epic_id, work_item_id, confluence_url, epic_log_section}`.
- `log_samples` — references into the existing log warehouse proving the control (login/sql-error/sql-query examples) `{_id, db_platform, kind, mongo_ref, finding_id}`.
- `workflow_runs` — orchestrator state per run, linking all of the above for one finding.

These join to the existing `audit_log` (write provenance) and the warehouse collections.

### 9e. Dashboard UX (the hub)

- **Connections grid** — the bubbles from 9b. Each: status dot (healthy/degraded/not-connected/placeholder), summary metric, last-sync, click → detail drawer with that system's recent items + its tools.
- **Workflow lane** — a horizontal stepper (steps 1→9) for a selected finding/epic; each step shows its artifact (finding card, epic, generated ticket, branch/PR with check status, Confluence link, log samples) and the cross-links. Clicking any node opens the underlying record.
- **"Relate everything" view** — pick a finding (or the RDS epic) and see a single panel with every associated piece pulled from the collections above + live system reads.
- **Report actions** — "Export PDF" / "Export PPT" buttons (9f) scoped to the current finding/epic.
- All views reuse Stage-8 robustness: loading/empty/error+retry, optimistic where it makes sense, a11y, theming. Connection detail reads are cached via TanStack Query with per-bubble refetch.

### 9f. Reporting (PDF / PPT)

A server-side report builder aggregates a finding/epic's full graph (finding → epic → tickets → PRs → docs → sample logs) and renders **audience-tuned** outputs:
- **PDF** — narrative compliance artifact (finding, requirement, evidence, real log excerpts, links).
- **PPT** — executive summary deck for layman/manager/audit-manager: status, coverage across DB×platform combos, what the logs prove, links out.
Exposed as MCP tools (`report_pdf`, `report_ppt`) so the agent can also generate them; the web offers download buttons. Use established PDF/PPTX skills/libraries (resolve exact libs in `S9.report.1`).

### 9g. Safety / rollout rails

- **Per-connector enable flags** (`CONN_<NAME>_ENABLED`, default `false`). Disabled → bubble shows "not connected", tools refuse with a clear message, no outbound calls.
- **Read-before-write**: live mutations (create Jira ticket, open PR, write Confluence) are behind an explicit `WORKFLOW_WRITES_ENABLED` flag *and* per-step human approval (orchestrator `interrupt()`); default off → the flow runs in **dry-run** producing the artifacts/links it *would* create.
- **Mocks first**: every connector ships a mock mode so the dashboard + workflow + reports are demoable end-to-end with zero live credentials. Live wiring is opt-in per connector.
- All workflow writes to Mongo are audited (`source="workflow_<step>"`), reusing the Stage-6 audit path.
- Archer stays a placeholder until its API is provisioned; nothing blocks on it.

### 9h. Env surface (additions — defaults keep everything off/mocked)

| Var | Default | Required | Stage | Notes |
| --- | --- | --- | --- | --- |
| `WORKFLOW_WRITES_ENABLED` | `false` | no | 9 | Master gate for live mutations across connectors |
| `CONN_JIRA_ENABLED` | `false` | no | 9 | Enable Jira MCP connector (else mock) |
| `JIRA_MCP_URL` | — | no | 9 | Upstream Jira MCP server URL |
| `JIRA_MCP_TOKEN` | — | no | 9 | Auth for Jira MCP |
| `CONN_CONFLUENCE_ENABLED` | `false` | no | 9 | Enable Confluence MCP connector |
| `CONFLUENCE_MCP_URL` | — | no | 9 | Upstream Confluence MCP server URL |
| `CONFLUENCE_MCP_TOKEN` | — | no | 9 |  |
| `CONN_GITHUB_ENABLED` | `false` | no | 9 | Enable GitHub MCP connector |
| `GITHUB_MCP_URL` | — | no | 9 | Upstream GitHub MCP server URL |
| `GITHUB_MCP_TOKEN` | — | no | 9 |  |
| `CONN_AWS_ENABLED` | `false` | no | 9 | Enable AWS MCP connector |
| `AWS_MCP_URL` | — | no | 9 | Upstream AWS MCP server URL |
| `CONN_SERVICENOW_ENABLED` | `false` | no | 9 | Enable ServiceNow REST adapter |
| `SERVICENOW_BASE_URL` | — | no | 9 | ServiceNow instance base URL |
| `SERVICENOW_TOKEN` | — | no | 9 | ServiceNow auth (token/basic) |
| `CONN_SNOWFLAKE_ENABLED` | `false` | no | 9 | Enable Snowflake SQL adapter |
| `SNOWFLAKE_ACCOUNT` | — | no | 9 | Snowflake account/locator |
| `SNOWFLAKE_USER` | — | no | 9 |  |
| `SNOWFLAKE_TOKEN` | — | no | 9 | Snowflake auth (PAT/keypair) |
| `CONN_ARCHER_ENABLED` | `false` | no | 9 | Placeholder; mock data when off |
| `REPORT_OUTPUT_DIR` | `/sandbox/reports` | no | 9 | Where generated PDF/PPT land |

### 9i. Verification (intent)

1. With all `CONN_*_ENABLED=false`, the dashboard renders **8 connection bubbles**; each shows a sensible mock/"not-connected" state with no outbound calls.
2. Seed a sample `audit_finding` (RDS logging) → it appears in the workflow lane linked to the seeded RDS epic.
3. Dry-run the workflow (writes disabled): steps 1→6 each produce an artifact + cross-links persisted to the new collections; the lane shows the would-create Jira ticket, branch name, PR template, and Confluence Epic-Log target.
4. "Relate everything" for the RDS epic shows finding + epic + work items + PR records + doc records + sample logs in one panel, each click-through opening the record.
5. Enabling one connector (e.g. Snowflake mock→live) flips its bubble to healthy and its detail drawer lists real recent items; disabling it fails its tools closed.
6. `report_pdf` and `report_ppt` produce files under `REPORT_OUTPUT_DIR` aggregating the finding's full graph; download buttons work from the UI.
7. Every Mongo write during the run has an `audit_log` row tagged `source="workflow_<step>"`.
8. `scripts/smoke_workflow.sh` passes (mock mode): seed finding → dry-run orchestrator → assert all collections populated + cross-linked → generate a report.

---

# Task checklist — Stage 9

> Granular and dependency-ordered. Connectors and workflow steps are independent enough to land one at a time behind their enable flags. Mock-first: nothing requires live credentials to be checked off.

### S9.model — Data model + decisions

- [x] **S9.model.1 — New MongoDB collections + seed**
  - Files: `mongo-seed/` (new seed for `epics` with the RDS priority epic + a sample `audit_findings` row), `mcp/db.py` (extend `KNOWN_COLLECTIONS`? — decide: workflow collections are **separate** from the read-only enterprise allowlist; add a dedicated workflow allowlist instead).
  - Done when: `audit_findings`, `epics`, `work_items`, `pr_records`, `doc_records`, `log_samples`, `workflow_runs` exist with seed data for the RDS epic + one finding.
  - Depends on: —

- [x] **S9.connect.1 — Lock connector decisions**
  - Files: this doc (record in §9b).
  - Done when: chosen MCP servers (image/version/auth) for Jira/Confluence/GitHub/AWS recorded; ServiceNow + Snowflake adapter approach confirmed; Archer placeholder contract defined.
  - Depends on: —

### S9.connect — Connector layer (server-side, mock-first)

- [x] **S9.connect.2 — `Connector` protocol + registry**
  - Files: `mcp/connectors/__init__.py`, `mcp/connectors/base.py`, `mcp/server.py` (registry → `tools/list`).
  - Done when: a common `health()/summary()/tools` contract exists; a registry enumerates connectors with enable flags; `audit_recent`-style proxying works for connector tools.
  - Depends on: S9.connect.1

- [x] **S9.connect.3 — MongoDB connector (wrap existing)**
  - Files: `mcp/connectors/mongodb.py`.
  - Done when: existing `mongo_*` tools surface through the registry with health/summary; serves as the reference connector.
  - Depends on: S9.connect.2

- [x] **S9.connect.4 — MCP-client connectors: Jira, Confluence, GitHub, AWS**
  - Files: `mcp/connectors/{jira,confluence,github,aws}.py`.
  - Done when: each connects to its upstream MCP server when `CONN_*_ENABLED=true`, else returns mock `health()/summary()` + sample items; tools refuse cleanly when disabled.
  - Depends on: S9.connect.2

- [x] **S9.connect.5 — ServiceNow REST adapter**
  - Files: `mcp/connectors/servicenow.py`, `mcp/server.py`.
  - Done when: read tools (findings/CRs) over `SERVICENOW_BASE_URL`; mock mode when disabled.
  - Depends on: S9.connect.2

- [x] **S9.connect.6 — Snowflake SQL adapter (tool_calls)**
  - Files: `mcp/connectors/snowflake.py`, `mcp/server.py`.
  - Done when: a read-only `snowflake_query` tool runs warehoused-log queries (validated/limited like `mongo_query`); mock rows when disabled.
  - Depends on: S9.connect.2

- [x] **S9.connect.7 — Archer placeholder connector**
  - Files: `mcp/connectors/archer.py`.
  - Done when: typed contract + mock findings; bubble renders "placeholder/not-connected"; no outbound calls.
  - Depends on: S9.connect.2

### S9.workflow — Orchestrator (steps 1→6, dry-run first)

- [x] **S9.workflow.1 — Workflow state model + collections wiring**
  - Files: `mcp/workflow/models.py`.
  - Done when: Pydantic models for the run + each artifact; cross-link ids resolved against the 9d collections.
  - Depends on: S9.model.1

- [x] **S9.workflow.2 — LangGraph orchestrator with approval interrupts**
  - Files: `mcp/workflow/graph.py`, checkpointer reuse.
  - Done when: steps 1→6 run in dry-run (writes gated by `WORKFLOW_WRITES_ENABLED` + per-step `interrupt()`); each step persists its artifact + cross-links; `workflow_runs` updated; audited (`source="workflow_<step>"`).
  - Depends on: S9.workflow.1, S9.connect.4

- [x] **S9.workflow.3 — Jira ticket generation from epic template**
  - Files: `mcp/workflow/jira_template.py`.
  - Done when: given a finding + epic, emits a best-practice ticket payload (dry-run returns it; live creates via the Jira connector when enabled).
  - Depends on: S9.workflow.2, S9.connect.4

- [x] **S9.workflow.4 — PR template + Actions/review wiring (dry-run)**
  - Files: `mcp/workflow/pr_template.py`.
  - Done when: produces the branch name (references Jira key), PR body template, required checks list, and reviewer set (Copilot + 2); live opens the PR via the GitHub connector when enabled.
  - Depends on: S9.workflow.2, S9.connect.4

- [x] **S9.workflow.5 — Confluence Epic-Log documentation (dry-run)**
  - Files: `mcp/workflow/epic_log.py`.
  - Done when: renders the Epic-Log section for the work item; live publishes via the Confluence connector when enabled; `doc_records` updated.
  - Depends on: S9.workflow.2, S9.connect.4

### S9.report — PDF / PPT artifacts

- [x] **S9.report.1 — Pick libraries + report data aggregator**
  - Files: `mcp/report/aggregate.py`, `mcp/requirements.txt`.
  - Done when: PDF + PPTX libs chosen/pinned; aggregator pulls a finding's full graph from the 9d collections + live reads into one report model.
  - Depends on: S9.workflow.2

- [x] **S9.report.2 — `report_pdf` + `report_ppt` MCP tools**
  - Files: `mcp/report/pdf.py`, `mcp/report/ppt.py`, `mcp/server.py`.
  - Done when: both tools write to `REPORT_OUTPUT_DIR`, audience-tuned (layman/manager/audit-manager); returned path is downloadable by the web.
  - Depends on: S9.report.1

### S9.web — Dashboard hub UI

- [x] **S9.web.1 — Connector proxy routes + types/hooks**
  - Files: `web/main.py` (`/api/connectors`, `/api/connectors/{name}`), `web/src/lib/{types,queries}.ts`.
  - Done when: the SPA can enumerate bubbles + health and read each connector's recent items via typed hooks.
  - Depends on: S9.connect.2

- [x] **S9.web.2 — Connections grid (bubbles)**
  - Files: `web/src/routes/overview.tsx` (or a new `hub.tsx`), `web/src/components/connection-bubble.tsx`.
  - Done when: 8 bubbles render with status dot/summary/last-sync; click opens a detail drawer; mock states render with no live calls.
  - Depends on: S9.web.1

- [x] **S9.web.3 — Workflow lane + "Relate everything" view**
  - Files: `web/src/routes/workflow.tsx`, components.
  - Done when: select a finding/epic → horizontal stepper (1→9) with each artifact + cross-links; a single relate-everything panel pulls all associated records; click-through opens records.
  - Depends on: S9.web.1, S9.workflow.2

- [x] **S9.web.4 — Report export buttons**
  - Files: `web/main.py` (download proxy), `web/src/routes/workflow.tsx`.
  - Done when: "Export PDF"/"Export PPT" scoped to the current finding/epic call the report tools and download the file.
  - Depends on: S9.report.2, S9.web.3

### S9.verify — End-to-end

- [x] **S9.verify.1 — `scripts/smoke_workflow.sh` (mock mode)**
  - Files: `scripts/smoke_workflow.sh`.
  - Done when: seeds a finding → dry-run orchestrator → asserts `audit_findings/epics/work_items/pr_records/doc_records/log_samples/workflow_runs` populated + cross-linked → generates a PDF; exit 0.
  - Depends on: S9.workflow.5, S9.report.2

- [x] **S9.verify.2 — Build + dashboard walkthrough**
  - Done when: §9i scenarios 1–8 reproducible (mock mode); one connector flipped live verified; recorded as a note here.
  - Depends on: S9.web.4, S9.verify.1

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
| `WEB_BUILD_MODE` | `production` | no | 8 | `vite build` mode; `development` enables source maps |
| `AUDIT_RECENT_LIMIT` | `25` | no | 8 | Default rows for the Overview activity table |
| `WORKFLOW_WRITES_ENABLED` | `false` | no | 9 | Master gate for live mutations across connectors |
| `CONN_JIRA_ENABLED` | `false` | no | 9 | Enable Jira MCP connector (else mock) |
| `JIRA_MCP_URL` | — | no | 9 | Upstream Jira MCP server URL |
| `JIRA_MCP_TOKEN` | — | no | 9 | Auth for Jira MCP |
| `CONN_CONFLUENCE_ENABLED` | `false` | no | 9 | Enable Confluence MCP connector |
| `CONFLUENCE_MCP_URL` | — | no | 9 | Upstream Confluence MCP server URL |
| `CONFLUENCE_MCP_TOKEN` | — | no | 9 |  |
| `CONN_GITHUB_ENABLED` | `false` | no | 9 | Enable GitHub MCP connector |
| `GITHUB_MCP_URL` | — | no | 9 | Upstream GitHub MCP server URL |
| `GITHUB_MCP_TOKEN` | — | no | 9 |  |
| `CONN_AWS_ENABLED` | `false` | no | 9 | Enable AWS MCP connector |
| `AWS_MCP_URL` | — | no | 9 | Upstream AWS MCP server URL |
| `CONN_SERVICENOW_ENABLED` | `false` | no | 9 | Enable ServiceNow REST adapter |
| `SERVICENOW_BASE_URL` | — | no | 9 | ServiceNow instance base URL |
| `SERVICENOW_TOKEN` | — | no | 9 | ServiceNow auth (token/basic) |
| `CONN_SNOWFLAKE_ENABLED` | `false` | no | 9 | Enable Snowflake SQL adapter |
| `SNOWFLAKE_ACCOUNT` | — | no | 9 | Snowflake account/locator |
| `SNOWFLAKE_USER` | — | no | 9 |  |
| `SNOWFLAKE_TOKEN` | — | no | 9 | Snowflake auth (PAT/keypair) |
| `CONN_ARCHER_ENABLED` | `false` | no | 9 | Placeholder; mock data when off |
| `REPORT_OUTPUT_DIR` | `/sandbox/reports` | no | 9 | Where generated PDF/PPT land |

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

## Stage 10 — Service-Specific Micro-Agents (Cognitive Scaling & Security Isolation)

**Goal:** Evolve the monolithic toolbelt design into specialized, single-responsibility leaf executors at the LangGraph node level (Node-Level Tool Scoping), minimizing token context usage, avoiding tool dilution, and enforcing the security principle of least privilege.

### 10a. Why this is necessary
- **Tool Dilution:** As Stage 9 adds multiple external systems (Jira, Confluence, GitHub, AWS, ServiceNow, Snowflake, Archer), making all tools available statically in `server.py`’s `TOOLS` array forces generalist agents to select from 30+ schemas. This degrades model accuracy.
- **Context Footprint:** Transmitting 30+ schemas on every LLM call scales input token usage exponentially across multi-turn workflows.
- **Least Privilege:** Restricting tool access in a node-level sandbox reduces security risks in case of model drift.

### 10b. The Implementation Pattern: Node-Level Tool Scoping
- At the LangGraph execution layer (`mcp/workflow/nodes.py`), each node is a pure function.
- Rather than a generalist prompt, each node limits tool access solely to the schemas relevant for that node's concrete task (e.g., the `generate_ticket` node only sees `jira_*` tools).
- High-level orchestration is kept in the high-level graphical state transition layer (the controller), while low-level actions are scoped specifically.

### 10c. Task Checklist

- [x] **S10.scope.1 — Restructure graph nodes tool scoping**
  - Files: `mcp/workflow/nodes.py`, `mcp/connectors/__init__.py`.
  - Done when: `get_connector(name).tools()` is utilized inside `nodes.py` to selectively fetch and inject *only* system-specific tools to the LLM during distinct node tasks, reducing prompt size by 80%+.
  - Depends on: S9.workflow.2

- [x] **S10.scope.2 — Least-privilege credentials isolation**
  - Files: `mcp/connectors/__init__.py`.
  - Done when: connectors verify and utilize scoped API keys, preventing global leakage if a single provider is degraded.
  - Depends on: S9.connect.2

---

## Stage 11 — Compliance command center (the main page as a live overview)

> **Pick-up point.** Stage 9 built the **Hub** (`/hub` → `web/src/routes/hub.tsx`) as the place to enumerate connection bubbles and drill into one workflow. Stage 11 promotes the **Overview** (`/` → `web/src/routes/overview.tsx`) from a generic stat-grid into the **compliance command center**: a single dynamic surface that pulls together every service and every collection the Hub touches, fronted by the numbers and tables a compliance lead checks first thing each morning. Start at `S11.api.1` and proceed in task order. This is **additive** — it reuses Stage-9 collections, the Stage-9 web proxy, and Stage-8 UI primitives; no new compose services.

**Goal:** A person lands on the dashboard and, without clicking, sees a live roll-up of the whole compliance estate — connector health, finding/epic/work-item/PR counts, and (most importantly) **what needs attention**: items that are currently prioritized or have an upcoming due date. Each number and table is a click-through into the Hub or the underlying record.

### 11a. What changes (Overview, today → target)

The current Overview (`overview.tsx`) shows raw Mongo collection counts (`employees`, `tickets`, `documents`) plus an audit-log write-trend. That made sense before Stage 9; it now under-uses the compliance data model. Stage 11 reframes the page around the Stage-9 collections (`audit_findings`, `epics`, `work_items`, `pr_records`, `doc_records`, `log_samples`, `workflow_runs`) and the connector registry, while keeping the existing audit-trend as a secondary panel.

**The page is composed of dynamic regions, each backed by a live query (TanStack Query, polled), each with loading/empty/error+retry per Stage-8 robustness:**

1. **KPI row** — numeric displays (reuse `StatCard`): open findings, active epics, in-flight work items, open PRs, connectors healthy / total, and an "attention" count (see 11c). Each card carries a small delta/sub-label (e.g. "3 due this week").
2. **Attention panel** — the headline region (11c): a ranked table of items that are *prioritized* or *due soon*, drawn across collections, with a reason chip per row.
3. **Connector health strip** — a condensed read of `/api/connectors` (the bubbles already powering the Hub) showing status dots + one-line summary; click → Hub bubble.
4. **Collection tables** — a compact, multi-table region presenting the most recent rows of the key compliance collections (findings, epics, work items, PRs) side by side, each row click-through into the Hub / record.
5. **Activity trend** — the existing audit-log per-day chart, retained but demoted below the compliance regions.

### 11b. Architecture (keep the established shape)

- **Server-side aggregation.** Add a single read endpoint that returns the whole overview payload in one round-trip, so the page makes one polled call rather than fanning out N queries from the browser. Logic lives in `mcp/` (a new aggregation tool, mirroring how `wrangler_*` / `connector_*` are exposed), and `web/main.py` proxies it.
  - `mcp`: `overview_summary` tool → counts per compliance collection + the computed attention list (11c) + connector health roll-up. Reuses existing `mongo_*` reads and the connector registry; no new external calls.
  - `web/main.py`: `GET /api/overview` → `_mcp_tool("overview_summary", …)`, returning `{ kpis, attention[], connectors[], tables: { findings[], epics[], work_items[], pr_records[] } }`.
- **Web only proxies / renders.** No business logic in the SPA beyond formatting and grouping.
- **One query, polled.** `useOverview()` in `web/src/lib/queries.ts` (`refetchInterval`, e.g. 30s) so the "dynamic view" stays live without manual refresh. Connector health may keep its own faster cadence if reused from the Hub.
- **Components are reused first.** `StatCard` for KPIs; a small generic `MiniTable` (new, in `web/src/components/`) for the multi-table region; the Hub's status-dot styling for the connector strip; the existing chart for the trend. Anything genuinely new is a thin presentational component.

### 11c. "Points of concern" — the attention model (the core of this stage)

The defining feature is surfacing **what needs work now**. Define a server-side computed `attention[]` list, each item normalized to a common shape regardless of source collection:

`{ id, kind (finding|epic|work_item|pr), title, reason, severity, priority, due_date?, days_until_due?, link }`

An item earns a slot if **any** rule fires (rules evaluated server-side in `overview_summary`):

| Reason | Source | Rule |
| --- | --- | --- |
| **Prioritized** | `epics`, `audit_findings` | `priority` ∈ {high, critical} **and** `status` not done/closed |
| **Due soon** | any with a `due_date` | `due_date` within `OVERVIEW_DUE_SOON_DAYS` (default 14) and not done |
| **Overdue** | any with a `due_date` | `due_date` in the past and not done |
| **High severity** | `audit_findings` | `severity` ∈ {high, critical} and `status="open"` |
| **Stalled** | `work_items`, `pr_records` | open/in-progress with no update in `OVERVIEW_STALE_DAYS` (default 7) |
| **Blocked PR** | `pr_records` | `state` open with a failing check in `checks[]` |

Items are ranked: overdue > due-soon > prioritized > high-severity > stalled, with severity/priority as the tiebreak. The panel renders the top N (default 10) with a reason chip and a "days until due" / "X days overdue" badge; a footer link expands the full list (could route to a filtered Hub view).

> **Due dates don't exist in the seed yet.** `epics`/`audit_findings`/`work_items` currently carry `priority`/`severity`/`status` but no `due_date`. Stage 11 adds a `due_date` (and where useful `updated_at` for staleness) to the relevant seeds so the attention rules have real data to act on. This is the one data-model addition; everything else reads existing fields.

### 11d. Data model (additions — minimal)

- `audit_findings`: add `due_date` (ISO), keep `severity`/`status`.
- `epics`: add `due_date`, keep `priority`/`status`.
- `work_items`: add `due_date`, ensure `updated_at` is seeded with a spread of dates so "stalled" is demonstrable.
- `pr_records`: ensure `checks[]` includes at least one failing example so "blocked PR" renders.
- No new collections. The seed scripts (`mongo-seed/04-epics.js`, `05-audit_findings.js`, `06-work_items.js`, `07-pr_records.js`) gain these fields; `12-scale-data.js` should propagate a realistic spread of due dates across the scaled rows.

### 11e. UX details

- **Dynamic-first:** every region updates on the poll; no full-page reload. Stale-while-revalidate so the page never blanks on refetch.
- **Click-through everywhere:** KPI cards, attention rows, connector dots, and table rows all deep-link to the Hub (and, where it exists, the specific record/drawer).
- **Attention is visually dominant:** it sits directly under the KPI row, full-width, with severity/overdue color cues using existing theme tokens (`--destructive`, `--chart-*`) — no new color system.
- **Multi-table region** uses a responsive grid (1 col mobile → 2 cols desktop), each `MiniTable` capped at ~5 rows with a "view all in Hub" link.
- **Empty/error states** per region (Stage-8): an empty attention list reads "Nothing needs attention — all clear" rather than a blank box; a failed `/api/overview` shows a retry.
- **A11y/theming:** reuse Stage-8 patterns (semantic headings per region, keyboard-focusable rows, dark/light tokens).

### 11f. Env surface (additions — tunables, all defaulted)

| Var | Default | Required | Stage | Notes |
| --- | --- | --- | --- | --- |
| `OVERVIEW_DUE_SOON_DAYS` | `14` | no | 11 | Window for the "due soon" attention rule |
| `OVERVIEW_STALE_DAYS` | `7` | no | 11 | No-update window for the "stalled" rule |
| `OVERVIEW_ATTENTION_LIMIT` | `10` | no | 11 | Max rows in the attention panel |
| `OVERVIEW_TABLE_ROWS` | `5` | no | 11 | Rows shown per mini-table |
| `OVERVIEW_POLL_MS` | `30000` | no | 11 | Front-end poll cadence for `/api/overview` |

### 11g. Verification (intent)

1. Opening `/` renders the KPI row with live counts that match the Stage-9 collections (cross-check against `/hub` and `mongo_*`).
2. With seeded due dates, the attention panel lists the RDS priority epic (prioritized) and at least one due-soon / overdue item, correctly ranked, each with a reason chip and days-to-due badge.
3. The connector strip mirrors the Hub bubbles' health (same `/api/connectors` source); clicking a dot lands on that bubble in the Hub.
4. Each mini-table shows recent rows of its collection; a row click deep-links into the Hub/record.
5. Leaving the page open shows regions updating on the poll without a manual refresh; refetch never blanks the page.
6. Killing MCP shows per-region error+retry, not a white screen; an all-done dataset shows the "all clear" empty state.
7. `/api/overview` returns the full payload in one call; the SPA makes one polled request per cadence (verify in network tab).

---

# Task checklist — Stage 11

- [ ] **S11.api.1 — `overview_summary` aggregation tool (MCP)**
  - Files: `mcp/server.py` (register tool), `mcp/` aggregation module (new, e.g. `mcp/overview.py`).
  - Done when: a single MCP tool returns `{ kpis, attention[], connectors[], tables{} }` computed from existing `mongo_*` reads + the connector registry, with the 11c attention rules applied server-side. No new external calls.
  - Depends on: S9.model.1, S9.connect (connector registry).

- [ ] **S11.api.2 — `GET /api/overview` proxy (web)**
  - Files: `web/main.py`.
  - Done when: the route proxies `overview_summary` and returns the payload unchanged; documented in the route list at the top of `main.py`.
  - Depends on: S11.api.1.

- [ ] **S11.data.1 — Seed due dates + staleness/check fixtures**
  - Files: `mongo-seed/04-epics.js`, `05-audit_findings.js`, `06-work_items.js`, `07-pr_records.js`, `12-scale-data.js`.
  - Done when: findings/epics/work-items carry a realistic spread of `due_date` (some overdue, some due-soon, most future), work-items have varied `updated_at`, and at least one `pr_record` has a failing check — so every 11c rule has data to fire on.
  - Depends on: none (data only).

- [ ] **S11.web.1 — `useOverview()` query hook**
  - Files: `web/src/lib/queries.ts`, `web/src/lib/types.ts`.
  - Done when: a polled (`OVERVIEW_POLL_MS`) `useOverview()` hook + typed response exist, stale-while-revalidate.
  - Depends on: S11.api.2.

- [ ] **S11.web.2 — KPI row + connector strip**
  - Files: `web/src/routes/overview.tsx`.
  - Done when: the KPI row (reusing `StatCard`) shows the compliance counts + attention count with sub-labels, and a condensed connector-health strip click-throughs to the Hub. Loading/empty/error per region.
  - Depends on: S11.web.1.

- [ ] **S11.web.3 — Attention panel (points of concern)**
  - Files: `web/src/routes/overview.tsx`, `web/src/components/` (attention table component).
  - Done when: the ranked attention list renders with reason chips + due/overdue badges, severity/overdue color cues from theme tokens, an "all clear" empty state, and row click-through. Sits directly under the KPI row, full-width.
  - Depends on: S11.web.1.

- [ ] **S11.web.4 — Multi-table region + retained trend**
  - Files: `web/src/routes/overview.tsx`, `web/src/components/mini-table.tsx` (new).
  - Done when: a responsive grid of `MiniTable`s (findings/epics/work-items/PRs, capped at `OVERVIEW_TABLE_ROWS`) renders with per-table "view all in Hub" links, and the existing audit trend is retained as a secondary panel below.
  - Depends on: S11.web.1.

- [ ] **S11.verify.1 — Smoke + intent checks**
  - Files: `scripts/smoke_overview.sh` (new).
  - Done when: the script asserts `/api/overview` returns all four payload sections and that the attention list is non-empty against the seeded data; the 11g intent checks pass by inspection in the running app.
  - Depends on: S11.api.2, S11.data.1, S11.web.2–4.

---

## Stage 12 — Domain-rich connector data + cross-system topology visualization

> **Pick-up point.** Stages 9–11 stood up the connector registry, the Hub detail panes, and the Overview command center. Today every connector's `summary()` returns a thin, mostly-identical `sample_data` shape (Jira/GitHub/Confluence/Snowflake) — and **AWS and ServiceNow return no `sample_data` at all**, so their Hub panes show the empty state. Stage 12 makes each connector's mock data **look like its real domain**, renders that data faithfully in the Hub, and adds a dedicated, **interactive "Architecture" page** whose sole focus is an AWS-architecture-style interconnectivity diagram tying every system together with endpoints, statuses, and highlighted weak-spots. Start at `S12.mock.1` and proceed in task order. Additive; no new compose services. The visualization uses a **flow/graph library (React Flow — `@xyflow/react`)** — the one new web dependency in this stage.

**Goal:** Each connector pane reads like a screen from the real product (an AWS console row, a Jira sprint board grouped by epic, a ServiceNow incident queue + change calendar, a GitHub commit feed tagged to epics, a Confluence "related pages" panel). A dedicated **Architecture** page is given over entirely to an interactive diagram showing how those systems connect — nodes per system, edges for the real data relationships (finding→epic→ticket→branch/PR→doc→logs→cloud resource), endpoints and live status in tooltips/node details, and visually flagged **points of concern**: neglected Jira tickets, PRs with failing checks, and upcoming changes that threaten an outage or the business.

> **Status: COMPLETE & verified live.** All `S12.*` tasks landed and were checked against the running stack: `/api/topology` returns 8 nodes / 11 edges / 6 ranked concerns; `/api/connectors` carries `schema` + populated `sample_data` for every connector (AWS `aws_resources` 9 rows, ServiceNow `snow_grc` 5 rows, Jira `jira_sprint` 6 rows, …); the `/architecture` route renders the React Flow diagram (HTTP 200). Persistence (`S12.persist.1`) was proven: a marker row survived `docker compose down && docker compose up --build -d`. Only `@xyflow/react` was added to `web/package.json`.

### 12a. Why this exists / what's wrong today

- **AWS / ServiceNow have no `sample_data`.** `aws.py.summary()` returns only `rds_instances_count`; `servicenow.py.summary()` returns only counts. The Hub (`hub.tsx`) has no column block for either, so selecting them yields "No simulation records loaded."
- **The data is generic.** Jira rows are flat (key/summary/status/assignee/updated) with no sprint or epic grouping; GitHub shows PRs, not commits-per-project-with-epic-tags; Confluence shows pages, not *related* pages keyed off tickets/users/projects; Snowflake is fine but isolated.
- **Nothing shows how the systems relate.** The relationships exist in the Stage-9 data model (cross-linked ids) but there's no visual that makes the estate legible at a glance or surfaces where it's weak.

### 12b. Per-connector domain data (the mock content contract)

Each connector keeps the existing `summary()` contract (`{status, …counts, sample_data[]}`) but `sample_data` becomes domain-shaped. To let the Hub pick the right columns without sniffing field names, add a `schema` hint to each summary: `"schema": "<connector-domain>"` (e.g. `"aws_resources"`, `"jira_sprint"`). The Hub renders columns by `schema`, falling back to the current name-based switch.

- **AWS** — `schema: "aws_resources"`. Rows model real cloud inventory:
  `{ account_id, account_alias, region, resource_id, service, resource_type, status, env, audit_logging }`
  Span services beyond RDS so the "service type" request is met: `RDS` (db instances), `S3` (log archive bucket), `CloudTrail` (trail), `KMS` (CMK), `ELB/ALB` (load balancer), `IAM` (role). Vary `region` (`us-east-1`, `eu-west-1`, `us-west-2`), `env` (`prod`/`staging`), and `audit_logging` (`enabled`/`disabled`) — a `disabled` row on a prod RDS is a deliberate weak-spot the topology highlights. Keep `rds_instances_count` and add `resources_count`.
- **Jira** — `schema: "jira_sprint"`. Add an `active_sprint` object (`{name, ends, committed, completed}`) and group `sample_data` so the pane can show **tickets grouped by epic and by assignee**. Each row: `{ key, summary, status, assignee, epic_key, epic_name, story_points, updated, age_days, flagged }`. Seed enough rows that the RDS epic (`RDS-LOG-1`) has several stories, plus `SEC-SCAN`/`ALB-ROT` epics. Mark at least one ticket `flagged` with a high `age_days` (no update in N days) — the "neglected ticket" weak-spot. Keep personas already in use (Alex SecOps, Sultan DevOps, Sarah SRE).
- **ServiceNow** — `schema: "snow_grc"`. Two row kinds via a `record_type` field: **incidents** (`{record_type:"incident", number:"INC…", priority:"P1|P2", summary, ci, opened, sla_breach}`) showing **high-priority open incidents**, and **scheduled changes** (`{record_type:"change", number:"CHG…", summary, ci, window_start, window_end, risk, impact}`) for the **change calendar**. Include at least one `P1` open incident and one high-`risk`/high-`impact` upcoming change (the "upcoming change that could cause an outage" weak-spot). Add `open_incidents`/`upcoming_changes` counts.
- **GitHub** — `schema: "github_commits"`. Shift from PRs to **recent commits across active projects**, each tagged to an epic via auto-applied labels: `{ sha, message, repo, project, author, committed, epic_key, tags[], pr_number?, checks_state }`. `tags[]` is the "automatically applied tags" (e.g. `["epic:RDS-LOG", "compliance", "sox-404"]`); `checks_state` ∈ {passing, failing, pending} — a `failing` row is a weak-spot. Keep a `prs_count` and add `commits_count`.
- **Confluence** — `schema: "confluence_links"`. Model **auto-surfaced related articles** keyed off shared signals: `{ id, title, space, url, last_updated, matched_on{ keywords[], ticket_refs[], users[], projects[] }, relevance }`. `url` points at the enterprise base (e.g. `https://enterprise.atlassian.net/wiki/…`) configurable via `CONFLUENCE_BASE_URL`. `matched_on` explains *why* the page surfaced (shared ticket number `RDS-LOG-1`, user `Sultan DevOps`, project `infra-terraform`, keyword `audit logging`).
- **Snowflake** — keep `schema: "snowflake_audit"` (current rows are already domain-correct); add a couple rows and ensure one `DENIED`/`sql-error` row remains as the visible anomaly.
- **MongoDB** — `schema: "mongo_collections"`; surface the system-of-record collections + counts it already reads so it isn't blank.
- **Archer** — `schema: "archer_findings"`; a small mock list of risk/audit findings feeding the workflow (placeholder, clearly labeled).

> All of this is **mock data** living in each connector's `summary()` (disabled path) — no live calls, defaults stay off. Where a base URL makes the mock more realistic (Confluence/Jira), it's read from an env var with a sensible default and never requires credentials.

### 12c. Topology / relationship payload (feeds the visualization)

Add one server-side aggregation the Overview can call: a **topology graph** describing nodes (systems) and edges (relationships) plus per-node health and per-edge/per-node concern flags.

- **MCP**: a `topology_graph` tool (new, e.g. `mcp/topology.py`) returns
  `{ nodes:[{ id, label, kind, status, endpoint, metrics{}, concerns[] }], edges:[{ from, to, label, kind, concern? }], concerns:[{ id, severity, kind, title, node_id?, edge?, link }] }`.
  - `nodes` = the 8 connectors (status/endpoint pulled from each connector's `health()`), plus optionally the MongoDB system-of-record as the hub node.
  - `edges` = the workflow relationships: ServiceNow/Archer → finding → Jira epic/ticket → GitHub branch/PR → Confluence doc → MongoDB record; AWS resource ↔ the RDS epic it satisfies; Snowflake/Mongo log warehouse ↔ the control it proves. Derive from the Stage-9 cross-links where present; otherwise from the seeded mock relationships.
  - `concerns` = computed weak-spots reusing Stage-11 attention rules **plus** connector-specific ones: neglected Jira ticket (`flagged`/stale), failing GitHub checks, AWS prod resource with `audit_logging:"disabled"`, ServiceNow P1 open incident, high-risk upcoming change. Each concern references the node/edge it sits on so the diagram can highlight it.
- **web/main.py**: `GET /api/topology` → proxies `topology_graph`.

### 12d. The visualization (dedicated "Architecture" page, React Flow)

- **Placement**: its **own route** — a new `Architecture` page (`/architecture`) added to the sidebar (`app-sidebar.tsx`) and routed in `App.tsx`. The page is given over **strictly to the interactive visualization and the interconnectivity** — no KPI rows or unrelated panels; just the diagram, its controls, and the concern list/legend that supports it. (The Overview keeps its Stage-11 layout unchanged; it may carry a small "View architecture →" link, but the diagram itself does not live there.)
- **Render**: **React Flow (`@xyflow/react`)** — the one new dependency this stage adds. Use custom node types (one per system "kind") rendered with a service-style icon (`lucide-react`), label, status dot, and key metric; edges are React Flow edges with labels and `MarkerType` arrowheads. Provide pan/zoom, a `Background`, `Controls`, and a `MiniMap`. Layout is deterministic (computed node positions in zoned columns: sources left → workflow systems middle → evidence stores right), grouped visually into labeled "zones" like an AWS architecture diagram.
- **Tooltips / details**: hover a node for a tooltip (`@radix-ui/react-tooltip`, or React Flow's own hover affordance) showing `endpoint`, `status`, and key `metrics` (e.g. "RDS: 4 instances, 1 logging-disabled"); edges show the relationship label. Clicking a node opens a side detail panel with its full metrics + a deep-link to the matching Hub bubble.
- **Weak-spot highlighting**: nodes/edges carrying a `concern` render with a destructive-token outline/glow and a warning badge (custom node styling + edge `style`/`animated`); a concern legend/list sits beside the canvas — clicking a concern pans/zooms to and selects its node and deep-links to the relevant Hub bubble / record. Color strictly from existing theme tokens (`--destructive`, `--chart-*`, `--border`); React Flow's theme variables are mapped to these.
- **States**: loading skeleton, empty ("no systems registered"), error+retry — per Stage-8 robustness. Polls on the Stage-11 cadence; node/edge positions are stable across refetches.
- **A11y**: nodes are focusable with `role`/`aria-label`; the concern list is a real list (and the page's primary readable artifact) so the canvas isn't the only way to read the weak-spots; keyboard users can tab the concern list to navigate.

### 12e. Hub rendering updates

- `hub.tsx`: replace the per-name column `switch` with a `schema`-keyed column registry, and **add column blocks for `aws_resources` and `snow_grc`** (today missing). For Jira, render the `active_sprint` header and group rows by `epic_name` (and offer an assignee grouping toggle if cheap). For GitHub, render commits with their epic tag chips and a checks-state badge. For Confluence, render the `matched_on` chips so it's clear *why* each article surfaced.
- Keep the existing empty/selected behavior; the fallback name-based columns remain for any connector without a `schema`.

### 12f. Env surface (additions — all defaulted, mock-friendly)

| Var | Default | Required | Stage | Notes |
| --- | --- | --- | --- | --- |
| `CONFLUENCE_BASE_URL` | `https://enterprise.atlassian.net/wiki` | no | 12 | Base for mock Confluence article links |
| `JIRA_BASE_URL` | `https://enterprise.atlassian.net` | no | 12 | Base for mock Jira issue links |
| `TOPOLOGY_INCLUDE_DISABLED` | `true` | no | 12 | Show disabled connectors as nodes (greyed) vs hide them |

> **New web dependency:** `@xyflow/react` (React Flow) is added to `web/package.json` for the Architecture page. It is the only new dependency in this stage; the Vite build picks it up on the next `docker compose build`. No new compose service.

### 12g. Verification (intent)

1. With all connectors disabled (default), selecting **AWS** in the Hub shows a multi-service resource table (RDS/S3/CloudTrail/KMS/ELB/IAM) with account/region/resource-id/service/status — not the empty state.
2. Selecting **ServiceNow** shows high-priority open incidents and an upcoming-change calendar, with at least one P1 and one high-risk change.
3. **Jira** shows the active sprint header and tickets grouped by epic (RDS-LOG-1 with several stories), with a visibly flagged/neglected ticket.
4. **GitHub** shows recent commits per active project with auto-applied epic tags and a checks-state badge (one failing).
5. **Confluence** shows related articles each annotated with what it matched on (ticket #, user, project, keyword) and links under the enterprise base URL.
6. A dedicated **Architecture** page (`/architecture`, in the sidebar) renders the React Flow diagram: 8 system nodes in labeled zones, edges tracing finding→epic→ticket→PR→doc→logs and AWS↔RDS-epic, pan/zoom + minimap + controls, node/edge tooltips showing endpoint+status, node-click detail panel, and weak-spots (neglected ticket, failing checks, prod RDS logging disabled, P1 incident, risky change) highlighted with a clickable concern list that focuses the node. The Overview's Stage-11 layout is unchanged.
7. `GET /api/topology` returns nodes+edges+concerns; `GET /api/connectors` reflects the enriched `sample_data` with `schema` hints. Killing MCP shows error+retry, not a blank canvas.
8. `@xyflow/react` is the **only** new dependency in `web/package.json` (verify the diff adds nothing else); defaults keep every connector mocked/off.

### 12h. Field fidelity — real ServiceNow ticketing + Atlassian structure

The 12b mock data is domain-*shaped* but still simplified. To make the panes and any future live wiring faithful, model the **actual field structures** of each system. This is a documentation + mock-shape upgrade; the live adapters (Stage 9) consume the same shapes later.

- **ServiceNow ticketing structure** — mirror the real ITSM/GRC tables and their canonical fields rather than ad-hoc keys:
  - **Incident (`incident` table)**: `number` (INC-prefixed), `short_description`, `description`, `priority` (P1–P5 derived from `impact`×`urgency`), `impact`, `urgency`, `state` (New/In Progress/On Hold/Resolved/Closed), `assignment_group`, `assigned_to`, `cmdb_ci` (configuration item), `opened_at`, `sla_due`, `sys_id`.
  - **Change Request (`change_request` table)**: `number` (CHG-prefixed), `short_description`, `type` (normal/standard/emergency), `risk`, `impact`, `state` (Assess/Authorize/Scheduled/Implement/Review/Closed), `start_date`/`end_date` (planned window), `cab_required`, `assignment_group`, `cmdb_ci`, `sys_id`.
  - **GRC linkage**: incidents/changes reference a `cmdb_ci` and (where relevant) a `control`/`citation` so they tie back to `audit_findings`.
  - Render the Hub pane as the two real queues (incident queue + change calendar) using these field names; keep `record_type` as the discriminator.
- **Atlassian (Jira) field structure** — use canonical Jira issue fields rather than flat keys:
  - **Issue**: `key`, `fields.summary`, `fields.issuetype` (Epic/Story/Task/Bug/Sub-task), `fields.status` (with `statusCategory`: To Do/In Progress/Done), `fields.priority`, `fields.assignee.displayName`, `fields.reporter`, `fields.labels[]`, `fields.components[]`, `fields.fixVersions[]`, `fields.customfield_story_points`, `fields.parent` (epic link), `fields.created`/`fields.updated`, `fields.duedate`.
  - **Epic**: `key`, `name`, child issue list, `status`, `duedate`; epic→story is the `parent` link.
  - **Sprint (Agile API)**: `id`, `name`, `state` (active/closed/future), `startDate`, `endDate`, `goal`, `boardId`; issues carry the sprint via `customfield_sprint`.
  - Group the board by epic (`fields.parent`) and offer an assignee grouping; show `statusCategory` color, `duedate`, and `story_points`.
- **Atlassian (Confluence) field structure** — model content + CQL relevance:
  - **Page/content**: `id`, `type` (page/blogpost), `title`, `space.key`/`space.name`, `version.number`, `version.when`, `version.by.displayName`, `_links.webui` (full URL), `ancestors[]` (page tree), `labels[]`.
  - **Relatedness** is expressed as the CQL-style match that surfaced the page (`matched_on`): shared `ticket_refs` (issue keys), `users` (mentions/authors), `projects`/`spaces`, and `keywords` — keep the Stage-12b `matched_on` but align field names to the above.
- These shapes are captured here and reflected in each connector's mock `sample_data`; the Hub renders the canonical fields. No new live calls.

### 12i. Mock-data persistence across rebuilds (bind mount)

Seeded Mongo data **must survive `docker compose down/up` and `--build`**. The previous setup used a named volume (`mongo-data:/data/db`); under `down -v` / volume prune the seeded data was lost.

- **Bind mount**: Mongo data is moved to a **host bind mount** — `./perm/db:/data/db` in `compose.yaml` (the user-requested `./perm` location; Mongo stores under `/data/db`). A host bind mount is never removed by `down -v` or `volume prune`, so data persists across rebuilds. `./perm/` is gitignored.
- **First-init vs reseed**: the `mongo-seed/*.js` scripts under `/docker-entrypoint-initdb.d` only run when the data dir is **empty** (first init). With a persistent bind mount they won't re-run automatically — which is the desired "data survives" behavior. To (re)apply seeds after editing them or to refresh mock data, use `scripts/reseed.sh` (`--wipe` to drop+reseed). This is the supported path for landing new Stage-11/12 seed fields onto an already-initialized DB.
- **Ownership**: Mongo runs as uid 999 in the container; the host `./perm/db` dir must be writable by it (created on first `up`; if pre-created, ensure permissions allow the container user to write).

---

# Task checklist — Stage 12

- [x] **S12.mock.1 — AWS multi-service resource data**
  - Files: `mcp/connectors/aws.py`.
  - Done when: `summary()` returns `schema:"aws_resources"` + `sample_data[]` spanning RDS/S3/CloudTrail/KMS/ELB/IAM with account/region/resource-id/service/status/env/audit_logging, including a prod RDS row with `audit_logging:"disabled"`.

- [x] **S12.mock.2 — Jira sprint + epic-grouped tickets**
  - Files: `mcp/connectors/jira.py`.
  - Done when: `summary()` returns `schema:"jira_sprint"`, an `active_sprint` object, and `sample_data[]` rows carrying `epic_key/epic_name/story_points/age_days/flagged`, with the RDS epic well-populated and ≥1 flagged/neglected ticket. Add `JIRA_BASE_URL` link building.

- [x] **S12.mock.3 — ServiceNow incidents + change calendar**
  - Files: `mcp/connectors/servicenow.py`.
  - Done when: `summary()` returns `schema:"snow_grc"` with `record_type`-tagged incidents (≥1 P1 open) and scheduled changes (≥1 high-risk/high-impact upcoming), plus `open_incidents`/`upcoming_changes` counts.

- [x] **S12.mock.4 — GitHub commits tagged to epics**
  - Files: `mcp/connectors/github.py`.
  - Done when: `summary()` returns `schema:"github_commits"` with recent commits per active project, auto-applied `tags[]` (incl. `epic:*`), and `checks_state` (≥1 failing). Keep PR fields available if cheap.

- [x] **S12.mock.5 — Confluence related-article linking**
  - Files: `mcp/connectors/confluence.py`.
  - Done when: `summary()` returns `schema:"confluence_links"` with articles annotated by `matched_on{keywords,ticket_refs,users,projects}` and `url` under `CONFLUENCE_BASE_URL`.

- [x] **S12.mock.6 — Snowflake/MongoDB/Archer schema hints + fill-out**
  - Files: `mcp/connectors/snowflake.py`, `mcp/connectors/mongodb.py`, `mcp/connectors/archer.py`.
  - Done when: each returns a `schema` hint and non-empty `sample_data` (Snowflake keeps a DENIED row; Mongo surfaces SoR collections+counts; Archer lists mock findings).

- [x] **S12.topo.1 — `topology_graph` MCP tool**
  - Files: `mcp/topology.py` (new), `mcp/server.py` (register).
  - Done when: returns `{nodes, edges, concerns}` computed from connector `health()` + the mock relationships + Stage-11/connector-specific weak-spot rules. No live calls.
  - Depends on: S12.mock.1–6.

- [x] **S12.topo.2 — `GET /api/topology` proxy + query hook**
  - Files: `web/main.py`, `web/src/lib/queries.ts`, `web/src/lib/types.ts`.
  - Done when: route proxies `topology_graph`; a polled `useTopology()` typed hook exists.
  - Depends on: S12.topo.1.

- [x] **S12.web.1 — Add React Flow dependency + Architecture route/sidebar entry**
  - Files: `web/package.json` (add `@xyflow/react`), `web/src/App.tsx` (route `/architecture`), `web/src/components/app-sidebar.tsx` (nav item, e.g. a `Network`/`Workflow` icon), `web/src/routes/architecture.tsx` (new, scaffold).
  - Done when: `@xyflow/react` is installed and imported, `/architecture` routes to a new page, and the sidebar links to it; the page builds (empty scaffold acceptable here). `@xyflow/react` is the only dependency added.
  - Depends on: S12.topo.2.

- [x] **S12.web.2 — Architecture page: React Flow topology visualization**
  - Files: `web/src/routes/architecture.tsx`, `web/src/components/topology/` (custom node/edge components, layout helper).
  - Done when: the page is *strictly* the interactive diagram — custom system nodes (icon/label/status/metric) in zoned columns, labeled edges with arrowheads, pan/zoom + `Background` + `Controls` + `MiniMap`, node hover tooltip (endpoint/status/metrics) and click→detail panel, weak-spot highlighting + a clickable concern list/legend that focuses its node and deep-links to the Hub. Loading/empty/error states; theme-token colors only (React Flow vars mapped to `--*`); a11y per 12d. Polls on the Stage-11 cadence with stable node positions.
  - Depends on: S12.web.1.

- [x] **S12.web.3 — Hub schema-keyed columns (AWS + ServiceNow + grouping)**
  - Files: `web/src/routes/hub.tsx`.
  - Done when: column rendering is keyed by `schema`; AWS and ServiceNow panes render their tables; Jira shows sprint header + epic grouping; GitHub shows commit tags + checks badge; Confluence shows `matched_on` chips. Name-based fallback retained.
  - Depends on: S12.mock.1–6.

- [x] **S12.field.1 — Proper ServiceNow ticketing structure**
  - Files: `mcp/connectors/servicenow.py`, `web/src/routes/hub.tsx`.
  - Done when: incident rows use canonical `incident`-table fields (`number`, `short_description`, `impact`, `urgency`, `priority`, `state`, `assignment_group`, `assigned_to`, `cmdb_ci`, `opened_at`, `sla_due`, `sys_id`) and change rows use `change_request` fields (`number`, `short_description`, `type`, `risk`, `impact`, `state`, `start_date`, `end_date`, `cab_required`, `assignment_group`, `cmdb_ci`, `sys_id`); the Hub renders the incident queue + change calendar with these field names. Per 12h.

- [x] **S12.field.2 — Proper Atlassian Jira/Confluence fields**
  - Files: `mcp/connectors/jira.py`, `mcp/connectors/confluence.py`, `web/src/routes/hub.tsx`.
  - Done when: Jira rows model canonical issue fields (`key`, `fields.{summary,issuetype,status+statusCategory,priority,assignee,labels,components,story_points,parent,created,updated,duedate}`) with sprint via the Agile-API shape (`id/name/state/startDate/endDate/goal`); Confluence rows model content fields (`id`, `type`, `title`, `space.{key,name}`, `version.{number,when,by}`, `_links.webui`, `ancestors`, `labels`) with `matched_on` relatedness; the Hub renders epic-grouped boards and content rows using these names. Per 12h.

- [x] **S12.persist.1 — Mongo data survives down/up/--build (bind mount)**
  - Files: `compose.yaml`, `.gitignore`, `scripts/reseed.sh` (new).
  - Done when: Mongo uses a host bind mount `./perm/db:/data/db` (named volume removed), `./perm/` is gitignored, and `scripts/reseed.sh` re-applies `mongo-seed/*.js` against the running container (`--wipe` to drop first). Verified: seed → `docker compose down && docker compose up --build -d` → data still present. Per 12i.

- [x] **S12.verify.1 — Smoke + intent checks**
  - Files: `scripts/smoke_topology.sh` (new).
  - Done when: asserts `/api/topology` returns nodes/edges/concerns and `/api/connectors` carries `schema` + non-empty `sample_data` for AWS/ServiceNow; the 12g checks pass by inspection in the running app; `web/package.json` diff adds only `@xyflow/react`; persistence verified per S12.persist.1.
  - Depends on: S12.topo.2, S12.web.2, S12.web.3, S12.persist.1.


---

## Stage 13 — Fleet-Dispatch design system (Roboto + navy/amber/teal restyle)

> **Pick-up point.** Stages 8–12 settled the IA and the data; the look is the generic "fintech-admin" oklch palette in `web/src/index.css` (Inter font, blue-grey neutrals). Stage 13 restyles the whole SPA toward a **fleet-dispatch tablet dashboard** aesthetic (ref: dribbble.com/shots/27367688-Fleet-Dispatch-Tablet-Dashboard) — a dark navy control-room surface with a single bright amber accent and teal as the secondary. Because every component already references **semantic tokens only** (never raw hex), this is almost entirely a **token + font remap in one file** plus a chart/edge color pass — not a component rewrite. Start at `S13.tokens.1`.

**Goal:** The app reads like an operations dashboard: deep indigo/navy canvas and cards, white text, **amber (`#FFD000`) as the primary call-to-action / active-state / key-metric accent**, **teal (`#06748C`) as the secondary / links / chart series**, on a white-and-navy base. Typography switches to **Roboto**. No layout or component-structure changes; the change is the palette, the font, and the accent behavior.

> **Status: COMPLETE (with one follow-up).** Tokens remapped to the brand palette in `web/src/index.css` (dark navy is now the default/headline theme; amber primary; teal secondary; charts lead amber+teal; destructive/success kept distinct). `--font-sans` is Roboto, self-hosted via `@fontsource/roboto` (offline-safe). The SPA typechecks and builds clean. **Follow-up `S13.cleanup.1` is partial**: the Architecture page uses theme tokens, but `hub-columns.tsx`/`hub.tsx`/`workflow-stepper.tsx` still use some hardcoded Tailwind color literals (e.g. status chips) — left intentionally for the status red/green semantics; a fuller token migration of the non-semantic blues/purples remains.

### 13a. Brand palette → token mapping

The four brand colors and their roles:

| Hex | Name | Role |
| --- | --- | --- |
| `#FFFFFF` | White | Light-mode background / dark-mode foreground text / card text on navy |
| `#FFD000` | Amber | **Primary** accent — buttons, active nav, focus ring, key KPI numbers, "needs attention" highlights, chart series 1 |
| `#1A1446` | Navy (deep indigo) | Dark-mode canvas + cards + sidebar; light-mode primary text; brand chrome |
| `#06748C` | Teal | **Secondary** — links, secondary buttons, chart series 2, info states, edge lines in topology |

Because the design target is a **dark control-room** look, treat **dark mode as the primary/intended theme** (navy canvas), while keeping a clean light variant (white canvas, navy text, amber/teal accents). Map onto the existing semantic tokens in `web/src/index.css` (convert hex → oklch to stay consistent with the file's convention; keep raw hex only in a comment for reference):

- **Dark theme (`.dark`, the headline look)**: `--background`/`--sidebar` ≈ `#1A1446` (and a slightly lighter navy for `--card`/`--popover`); `--foreground` ≈ `#FFFFFF`; `--primary` = `#FFD000` with `--primary-foreground` = `#1A1446` (dark text on amber); `--secondary`/`--ring`/links = `#06748C`; `--border`/`--input` = a translucent white/navy mix; `--accent` = amber-tinted hover.
- **Light theme (`:root`)**: `--background` = `#FFFFFF`; `--foreground` = `#1A1446`; `--primary` = `#FFD000` (amber, navy text); `--secondary`/links = `#06748C`; navy used for headings/chrome.
- **Charts**: `--chart-1` = amber `#FFD000`, `--chart-2` = teal `#06748C`, `--chart-3..5` = tints/shades of navy + teal + a desaturated amber so multi-series stays on-brand.
- **Status semantics stay legible**: keep `--destructive` red and `--success` green (don't fold these into brand colors — they carry meaning), but retune `--warning` toward the brand amber. The topology "weak-spot" highlight keeps using `--destructive`.

### 13b. Typography (Roboto)

- Set `--font-sans: "Roboto", Arial, sans-serif;` in the `@theme` block of `web/src/index.css` (replacing the Inter stack). `body` already uses `var(--font-sans)`.
- Load Roboto **self-hosted** via `@fontsource` (preferred — no external CDN call, works offline in the Docker build) or a `<link>` to Google Fonts in `web/index.html` if a CDN is acceptable. Default to `@fontsource/roboto` (weights 400/500/700) imported in `web/src/main.tsx`, added to `web/package.json`. Note: this is a second new web dependency after Stage-12's `@xyflow/react`.
- Keep the existing monospace token usage (`font-mono`) for ids/SQL/keys.

### 13c. Accent behavior (what "amber-forward" means)

- **Primary buttons / active nav item / current tab**: amber fill, navy text.
- **Focus ring** (`--ring`): amber, for a high-visibility tablet/touch target.
- **Key metrics** (Stage-11 KPI numbers, the attention count): amber numerals on navy cards.
- **Links / secondary actions / chart secondary**: teal.
- **Topology (Architecture page)**: node borders/edges default to teal; **weak-spot** nodes/edges stay destructive-red so concern signaling isn't diluted by brand color; the React Flow theme variables are mapped to these tokens.
- Maintain WCAG AA contrast: amber `#FFD000` on navy passes for large text/UI; for small body text prefer white-on-navy and reserve amber for accents/numerals/icons, not paragraphs.

### 13d. Scope / non-goals

- **In scope**: `web/src/index.css` token values (`:root`, `.dark`, `@theme`), `--font-sans`, font loading (`main.tsx`/`package.json` or `index.html`), and a small pass on any component that hardcoded a non-token color (e.g. the Tailwind palette literals like `text-blue-600`/`bg-emerald-100` used in `hub.tsx`/`hub-columns.tsx`/`workflow-stepper.tsx` — migrate the load-bearing ones to semantic tokens or on-brand equivalents).
- **Out of scope**: component structure, IA, copy, data. No new routes. Status red/green stay.

### 13e. Verification (intent)

1. Dark mode renders a navy (`#1A1446`) canvas with white text, amber primary buttons/active nav, teal links — matching the fleet-dispatch reference vibe.
2. Light mode renders white canvas, navy text, same amber/teal accents.
3. All text/UI meets WCAG AA contrast (spot-check amber-on-navy, white-on-navy, teal-on-white).
4. Body copy is Roboto (verify computed `font-family`); the app builds offline (no blocking external font fetch if `@fontsource` is used).
5. Charts use amber + teal as the lead two series; status red/green still signal correctly; topology weak-spots remain red.
6. No component references a raw brand hex directly — colors flow through tokens (grep for the four hexes finds them only in `index.css` comments).

---

# Task checklist — Stage 13

- [x] **S13.tokens.1 — Remap semantic color tokens to the brand palette**
  - Files: `web/src/index.css` (`:root`, `.dark`, `@theme inline`, chart vars).
  - Done when: dark = navy canvas/white text/amber primary/teal secondary; light = white/navy/amber/teal; charts lead amber+teal; destructive/success unchanged; brand hexes appear only in reference comments. Per 13a.

- [x] **S13.font.1 — Switch typography to Roboto**
  - Files: `web/src/index.css` (`--font-sans`), `web/package.json` + `web/src/main.tsx` (`@fontsource/roboto`) or `web/index.html` (`<link>`).
  - Done when: `--font-sans` is Roboto/Arial/sans-serif, the font loads (offline-safe if `@fontsource`), and body computed font is Roboto. Per 13b.

- [x] **S13.accent.1 — Amber-forward accent behavior**
  - Files: `web/src/index.css` (`--ring`, `--accent`, `--warning`), targeted component tweaks.
  - Done when: primary buttons/active nav/focus ring/key KPI numerals are amber; links/secondary are teal; AA contrast holds. Per 13c.

- [ ] **S13.cleanup.1 — Migrate hardcoded literals to tokens**
  - Files: `web/src/components/hub-columns.tsx`, `web/src/routes/hub.tsx`, `web/src/components/workflow-stepper.tsx`, others surfaced by grep.
  - Done when: load-bearing hardcoded Tailwind color literals are replaced with semantic tokens / on-brand equivalents; status red/green retained for meaning. Per 13d.

- [x] **S13.verify.1 — Theme + contrast check**
  - Files: (manual + `scripts/` if useful).
  - Done when: the 13e intent checks pass by inspection in both themes; AA contrast spot-checks pass; build is offline-safe.
  - Depends on: S13.tokens.1, S13.font.1.

---

## Stage 14 — Docs Wiki library (in-app MkDocs/Docusaurus-style) + Confluence sync

> **Pick-up point.** Docs today are scattered Markdown at the repo root (`README.md`, `IMPLEMENT.md`, `CLAUDE.md`, `PLANTMUX.md`, `progress.md`, `WAVE1–6.md`, `docs/*.md`) with no index, lifecycle, or audience control. Stage 14 stands up a **documentation library inside the app** — an MkDocs/Docusaurus-style wiki — as the single home for **100% of our docs**. Each doc carries lifecycle/visibility **flags** and **tags**; **public** docs sync to **Confluence** mirroring the same tree; and an **agent workflow** keeps the two in sync and proposes improvements to the docs themselves. Builds on the Stage-9 Confluence connector and the Stage-6 audited write-layer. Start at `S14.model.1`.

**Goal:** A `/docs` section in the SPA renders a navigable, searchable wiki (left tree, article view, edit). Every document lives in MongoDB as the system of record with front-matter-style metadata. An author flags a doc **public** and it appears in Confluence under the same path; flags like **needs-attention** / **archivable** drive review queues; an agent workflow reconciles MongoDB ↔ Confluence and raises suggested edits.

### 14a. Scope of "100% of our docs"

- **Migration**: the existing root/`docs/` Markdown files are imported as the initial corpus (one wiki doc per file, path-mapped, history preserved as v1). New docs are authored in the wiki; the repo Markdown becomes a generated export (or is retired) so there's one source of truth.
- **Coverage rule**: going forward, design notes / runbooks / specs land in the wiki, not as ad-hoc root `.md` files. `IMPLEMENT.md` may remain the engineering backlog, but its narrative sections become wiki docs over time.

### 14b. Data model (MongoDB — system of record)

New collections (audited via the Stage-6 write-layer, `source="docs_*"`):

- `docs` — `{_id, slug, path (e.g. "runbooks/rds-audit-logging"), title, body_md, tags[], status, visibility, owner, version, confluence_page_id?, last_reviewed_at, created_at, updated_at}`.
- `doc_revisions` — append-only history `{_id, doc_id, version, body_md, author, created_at, note}`.
- `doc_sync_log` — Confluence reconciliation events `{_id, doc_id, direction (push|pull), confluence_page_id, action (create|update|skip|conflict), at, detail}`.

**Flags / lifecycle** (the requested set), as two orthogonal fields:

- `visibility`: `internal` (default) | `public` (eligible for Confluence sync).
- `status`: `up_to_date` | `needs_attention` | `archivable` | `archived`.
- `tags[]`: free-form topical tags (e.g. `rds`, `sox-404`, `runbook`, `onboarding`) for filtering/search and to drive Confluence labels.

Lifecycle rules (computed/assisted, not just manual): `needs_attention` auto-set when `now - last_reviewed_at > DOCS_REVIEW_DAYS`; `archivable` suggested when a doc is stale **and** unreferenced; `archived` hides from default views but is retained. Transitions are audited.

### 14c. Architecture (server-side first, web proxies)

Keep the established shape — logic in `mcp/`, web proxies, agent tool-loop can drive it:

- `mcp/docs.py` — CRUD + search over `docs`/`doc_revisions` (Markdown stored as-is; render client-side). Tools: `docs_list` (tree + filters by tag/status/visibility), `docs_get`, `docs_upsert` (writes a revision), `docs_set_flags` (visibility/status/tags), `docs_search` (text). All writes go through the audited write-layer.
- `mcp/docs_sync.py` — Confluence reconciliation built on the **Stage-9 Confluence connector** (`confluence_search_pages` / `confluence_create_page`, extended with an update path). Maps wiki `path` → Confluence space + page tree; pushes **public** docs; records every action to `doc_sync_log`. Gated by the existing `WORKFLOW_WRITES_ENABLED` + `CONN_CONFLUENCE_ENABLED` flags (dry-run by default).
- `web/main.py` — `/api/docs*` proxies (`GET /api/docs/tree`, `GET /api/docs/{slug}`, `POST /api/docs`, `POST /api/docs/{slug}/flags`, `GET /api/docs/search`, `POST /api/docs/sync`).
- Web SPA — a `/docs` route: left nav tree (grouped by path), article view (reuse the existing `react-markdown` + `remark-gfm` + `rehype-highlight` `Markdown` component), an editor (textarea + preview), and per-doc flag/tag controls. Search box. Status/visibility shown as badges; `needs_attention`/`archivable` surfaced in a review queue and (optionally) feed the Stage-11 attention panel + Stage-12 topology concerns.

### 14d. Confluence sync (same structure)

- **Mapping**: wiki `path` segments → Confluence ancestor pages (create intermediate pages as needed) so the Confluence tree mirrors the wiki tree exactly; `tags[]` → Confluence labels; `title` → page title; `body_md` → storage format (Markdown→Confluence storage conversion, server-side).
- **Direction**: primary push (wiki → Confluence) for `public` docs. Detect drift on pull (Confluence newer) and mark `needs_attention` rather than overwriting — surface as a conflict in `doc_sync_log`.
- **Idempotency**: store `confluence_page_id` on the doc; sync updates that page in place.
- **Safety**: no live writes unless `CONN_CONFLUENCE_ENABLED` and `WORKFLOW_WRITES_ENABLED`; otherwise dry-run producing the would-create/update plan.

### 14e. Agent workflow (sync + suggestions)

A LangGraph workflow (reuse the Stage-9 orchestrator pattern + checkpointer), exposed as an MCP tool `docs_agent_run` and a `/api/docs/agent` proxy:

1. **Reconcile** — diff wiki ↔ Confluence for `public` docs; push/queue per 14d; log to `doc_sync_log`.
2. **Triage** — flag stale/unreferenced docs (`needs_attention`/`archivable`) with reasons.
3. **Suggest** — for `needs_attention` docs, the agent drafts improvement suggestions (clarity, broken links, outdated commands/paths, missing sections) as a **proposed revision** (never auto-applied) plus a short rationale; a human approves/edits before it becomes a new `doc_revisions` entry. Human-in-the-loop interrupt at the apply gate.
- All agent edits are proposals; applying one is an audited `docs_upsert`.

### 14f. Env surface (additions — defaulted, sync off by default)

| Var | Default | Required | Stage | Notes |
| --- | --- | --- | --- | --- |
| `DOCS_REVIEW_DAYS` | `90` | no | 14 | Age after which a doc auto-flags `needs_attention` |
| `DOCS_CONFLUENCE_SPACE` | `COMP` | no | 14 | Confluence space key public docs sync into |
| `DOCS_SYNC_ENABLED` | `false` | no | 14 | Master gate for Confluence push (also needs Stage-9 flags) |
| `DOCS_DEFAULT_VISIBILITY` | `internal` | no | 14 | New-doc default visibility |

### 14g. Verification (intent)

1. `/docs` renders a tree of the migrated corpus; clicking a doc shows rendered Markdown; search returns matches by title/body/tag.
2. Editing a doc writes a `doc_revisions` entry (version increments) and an `audit_log` row (`source="docs_upsert"`); history is viewable.
3. Setting `visibility=public` + running sync (mocks/dry-run) yields a `doc_sync_log` plan that mirrors the wiki path into `DOCS_CONFLUENCE_SPACE`; enabling the Stage-9 flags performs the create/update and stores `confluence_page_id`.
4. A doc past `DOCS_REVIEW_DAYS` auto-shows `needs_attention`; an archived doc is hidden from default views but retrievable.
5. `docs_agent_run` (dry-run) reconciles, triages, and emits suggested revisions as proposals with rationales — none auto-applied; approving one creates a new revision (audited).
6. Every doc write is audited; sync respects `DOCS_SYNC_ENABLED` + `CONN_CONFLUENCE_ENABLED` + `WORKFLOW_WRITES_ENABLED` (no outbound calls when off).

---

# Task checklist — Stage 14

- [ ] **S14.model.1 — Docs collections + audited writes**
  - Files: `mongo-seed/` (new seed for `docs`/`doc_revisions`/`doc_sync_log`), `mcp/db.py` (collection registration if needed).
  - Done when: the three collections exist with the 14b shape; writes route through the Stage-6 audited write-layer (`source="docs_*"`).

- [ ] **S14.api.1 — `mcp/docs.py` CRUD + search tools**
  - Files: `mcp/docs.py` (new), `mcp/server.py` (register).
  - Done when: `docs_list`/`docs_get`/`docs_upsert`/`docs_set_flags`/`docs_search` work; `docs_upsert` writes a `doc_revisions` entry + bumps version; flags validated against the 14b enums.

- [ ] **S14.migrate.1 — Import existing Markdown corpus**
  - Files: `scripts/import_docs.py` (new).
  - Done when: root/`docs/` `.md` files are imported as v1 wiki docs with path-mapped slugs and sensible default tags/status; idempotent re-run.

- [ ] **S14.web.1 — `/api/docs*` proxies + `useDocs*` hooks**
  - Files: `web/main.py`, `web/src/lib/queries.ts`, `web/src/lib/types.ts`.
  - Done when: tree/get/upsert/flags/search/sync routes proxy the MCP tools; typed hooks exist.
  - Depends on: S14.api.1.

- [ ] **S14.web.2 — Docs Wiki SPA route**
  - Files: `web/src/routes/docs.tsx` (new), `web/src/App.tsx`, `web/src/components/app-sidebar.tsx`.
  - Done when: `/docs` renders nav tree + Markdown article (reusing the `Markdown` component) + editor with preview + flag/tag controls + search; status/visibility badges; a `needs_attention`/`archivable` review queue. Loading/empty/error per Stage-8.
  - Depends on: S14.web.1.

- [ ] **S14.sync.1 — Confluence reconciliation (same tree)**
  - Files: `mcp/docs_sync.py` (new), `mcp/connectors/confluence.py` (add update path), `mcp/server.py`.
  - Done when: public docs map path→Confluence ancestors+page; push creates/updates idempotently (stores `confluence_page_id`), tags→labels; drift detection marks `needs_attention`; all actions logged to `doc_sync_log`; gated dry-run by default.
  - Depends on: S14.model.1, S9 Confluence connector.

- [ ] **S14.agent.1 — Docs agent workflow (sync + suggestions)**
  - Files: `mcp/workflow/` (new graph or node set), `mcp/server.py` (`docs_agent_run`), `web/main.py` (`/api/docs/agent`).
  - Done when: reconcile→triage→suggest runs (LangGraph + checkpointer); suggestions are human-in-the-loop proposals (never auto-applied); approving one is an audited `docs_upsert`.
  - Depends on: S14.api.1, S14.sync.1.

- [ ] **S14.verify.1 — Smoke + intent checks**
  - Files: `scripts/smoke_docs.sh` (new).
  - Done when: asserts CRUD+revision+audit, flag transitions, dry-run sync plan mirrors the tree, and `docs_agent_run` emits proposals without applying; the 14g checks pass by inspection.
  - Depends on: S14.web.2, S14.sync.1, S14.agent.1.

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

- [ ] **S9.model.1 — New MongoDB collections + seed**
  - Files: `mongo-seed/` (new seed for `epics` with the RDS priority epic + a sample `audit_findings` row), `mcp/db.py` (extend `KNOWN_COLLECTIONS`? — decide: workflow collections are **separate** from the read-only enterprise allowlist; add a dedicated workflow allowlist instead).
  - Done when: `audit_findings`, `epics`, `work_items`, `pr_records`, `doc_records`, `log_samples`, `workflow_runs` exist with seed data for the RDS epic + one finding.
  - Depends on: —

- [ ] **S9.connect.1 — Lock connector decisions**
  - Files: this doc (record in §9b).
  - Done when: chosen MCP servers (image/version/auth) for Jira/Confluence/GitHub/AWS recorded; ServiceNow + Snowflake adapter approach confirmed; Archer placeholder contract defined.
  - Depends on: —

### S9.connect — Connector layer (server-side, mock-first)

- [ ] **S9.connect.2 — `Connector` protocol + registry**
  - Files: `mcp/connectors/__init__.py`, `mcp/connectors/base.py`, `mcp/server.py` (registry → `tools/list`).
  - Done when: a common `health()/summary()/tools` contract exists; a registry enumerates connectors with enable flags; `audit_recent`-style proxying works for connector tools.
  - Depends on: S9.connect.1

- [ ] **S9.connect.3 — MongoDB connector (wrap existing)**
  - Files: `mcp/connectors/mongodb.py`.
  - Done when: existing `mongo_*` tools surface through the registry with health/summary; serves as the reference connector.
  - Depends on: S9.connect.2

- [ ] **S9.connect.4 — MCP-client connectors: Jira, Confluence, GitHub, AWS**
  - Files: `mcp/connectors/{jira,confluence,github,aws}.py`.
  - Done when: each connects to its upstream MCP server when `CONN_*_ENABLED=true`, else returns mock `health()/summary()` + sample items; tools refuse cleanly when disabled.
  - Depends on: S9.connect.2

- [ ] **S9.connect.5 — ServiceNow REST adapter**
  - Files: `mcp/connectors/servicenow.py`, `mcp/server.py`.
  - Done when: read tools (findings/CRs) over `SERVICENOW_BASE_URL`; mock mode when disabled.
  - Depends on: S9.connect.2

- [ ] **S9.connect.6 — Snowflake SQL adapter (tool_calls)**
  - Files: `mcp/connectors/snowflake.py`, `mcp/server.py`.
  - Done when: a read-only `snowflake_query` tool runs warehoused-log queries (validated/limited like `mongo_query`); mock rows when disabled.
  - Depends on: S9.connect.2

- [ ] **S9.connect.7 — Archer placeholder connector**
  - Files: `mcp/connectors/archer.py`.
  - Done when: typed contract + mock findings; bubble renders "placeholder/not-connected"; no outbound calls.
  - Depends on: S9.connect.2

### S9.workflow — Orchestrator (steps 1→6, dry-run first)

- [ ] **S9.workflow.1 — Workflow state model + collections wiring**
  - Files: `mcp/workflow/models.py`.
  - Done when: Pydantic models for the run + each artifact; cross-link ids resolved against the 9d collections.
  - Depends on: S9.model.1

- [ ] **S9.workflow.2 — LangGraph orchestrator with approval interrupts**
  - Files: `mcp/workflow/graph.py`, checkpointer reuse.
  - Done when: steps 1→6 run in dry-run (writes gated by `WORKFLOW_WRITES_ENABLED` + per-step `interrupt()`); each step persists its artifact + cross-links; `workflow_runs` updated; audited (`source="workflow_<step>"`).
  - Depends on: S9.workflow.1, S9.connect.4

- [ ] **S9.workflow.3 — Jira ticket generation from epic template**
  - Files: `mcp/workflow/jira_template.py`.
  - Done when: given a finding + epic, emits a best-practice ticket payload (dry-run returns it; live creates via the Jira connector when enabled).
  - Depends on: S9.workflow.2, S9.connect.4

- [ ] **S9.workflow.4 — PR template + Actions/review wiring (dry-run)**
  - Files: `mcp/workflow/pr_template.py`.
  - Done when: produces the branch name (references Jira key), PR body template, required checks list, and reviewer set (Copilot + 2); live opens the PR via the GitHub connector when enabled.
  - Depends on: S9.workflow.2, S9.connect.4

- [ ] **S9.workflow.5 — Confluence Epic-Log documentation (dry-run)**
  - Files: `mcp/workflow/epic_log.py`.
  - Done when: renders the Epic-Log section for the work item; live publishes via the Confluence connector when enabled; `doc_records` updated.
  - Depends on: S9.workflow.2, S9.connect.4

### S9.report — PDF / PPT artifacts

- [ ] **S9.report.1 — Pick libraries + report data aggregator**
  - Files: `mcp/report/aggregate.py`, `mcp/requirements.txt`.
  - Done when: PDF + PPTX libs chosen/pinned; aggregator pulls a finding's full graph from the 9d collections + live reads into one report model.
  - Depends on: S9.workflow.2

- [ ] **S9.report.2 — `report_pdf` + `report_ppt` MCP tools**
  - Files: `mcp/report/pdf.py`, `mcp/report/ppt.py`, `mcp/server.py`.
  - Done when: both tools write to `REPORT_OUTPUT_DIR`, audience-tuned (layman/manager/audit-manager); returned path is downloadable by the web.
  - Depends on: S9.report.1

### S9.web — Dashboard hub UI

- [ ] **S9.web.1 — Connector proxy routes + types/hooks**
  - Files: `web/main.py` (`/api/connectors`, `/api/connectors/{name}`), `web/src/lib/{types,queries}.ts`.
  - Done when: the SPA can enumerate bubbles + health and read each connector's recent items via typed hooks.
  - Depends on: S9.connect.2

- [ ] **S9.web.2 — Connections grid (bubbles)**
  - Files: `web/src/routes/overview.tsx` (or a new `hub.tsx`), `web/src/components/connection-bubble.tsx`.
  - Done when: 8 bubbles render with status dot/summary/last-sync; click opens a detail drawer; mock states render with no live calls.
  - Depends on: S9.web.1

- [ ] **S9.web.3 — Workflow lane + "Relate everything" view**
  - Files: `web/src/routes/workflow.tsx`, components.
  - Done when: select a finding/epic → horizontal stepper (1→9) with each artifact + cross-links; a single relate-everything panel pulls all associated records; click-through opens records.
  - Depends on: S9.web.1, S9.workflow.2

- [ ] **S9.web.4 — Report export buttons**
  - Files: `web/main.py` (download proxy), `web/src/routes/workflow.tsx`.
  - Done when: "Export PDF"/"Export PPT" scoped to the current finding/epic call the report tools and download the file.
  - Depends on: S9.report.2, S9.web.3

### S9.verify — End-to-end

- [ ] **S9.verify.1 — `scripts/smoke_workflow.sh` (mock mode)**
  - Files: `scripts/smoke_workflow.sh`.
  - Done when: seeds a finding → dry-run orchestrator → asserts `audit_findings/epics/work_items/pr_records/doc_records/log_samples/workflow_runs` populated + cross-linked → generates a PDF; exit 0.
  - Depends on: S9.workflow.5, S9.report.2

- [ ] **S9.verify.2 — Build + dashboard walkthrough**
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

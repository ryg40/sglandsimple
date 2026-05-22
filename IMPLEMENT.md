# IMPLEMENT.md — sglandsimple enterprise rollout (LangGraph edition)

This document is the implementation plan for evolving the current stack into an enterprise-shaped pattern: **server-side LangGraph agent workflows over a NoSQL store, fronted by both a web UI and direct MCP access from IDE/agent clients (opencode, VS Code Chat, PiAgent).**

> The repo name `sglandsimple` predates the framework choice. Despite the name, **this plan uses LangGraph**, not SGLang.

> **Archive note (2026-05-22):** Stages 0–2, 4, 7–12, 16, 17 are complete and verified. Their full narrative + task checklists were moved to **`IMPLEMENT-ARCHIVE.md`** to keep this file focused on open work. See the "Completed stages" table below for one-line summaries; open `IMPLEMENT-ARCHIVE.md` for the full detail of any archived stage. This file retains the header/ground-rules, the **Env surface** table (live reference), and the **full content of every stage with open tasks** (3, 5, 6-followups, 13, 14, 15).

## How to use this document

The narrative sections describe the *shape* of each stage. The **Task checklist** items are the executable plan: granular, dependency-ordered units of work, each small enough to pick up cold.

Convention:

- Tasks are `S<stage>.<group>.<n>`. Example: `S1.db.3 — Write validate_spec`.
- Check a task off (`[x]`) when **all** of its "Done when" bullets are satisfied. Partial work stays `[ ]` (or `[~]` for explicitly-partial).
- A task lists explicit **Files**, **Done when**, and **Depends on** so it can run in isolation.
- When a task creates new env vars, ports, or compose services, update the **Env surface** table in the same change.
- When multiple agents are active, read `COORDINATION.md` first and obey its file-ownership map.

## Ground rules

- **Model runtime: external, fixed.** Every LLM call goes to an upstream OpenAI-compatible endpoint. The URL, API key, and model id live in `.env.local` (gitignored), injected via `${UPSTREAM_*:?required}` in `compose.yaml`. No values hardcoded in committed files.
- **All graph code is server-side.** It lives in the MCP service container. Clients (web UI, OpenAI-API consumers, MCP clients) never import LangGraph; they call MCP tools or `/v1/chat/completions` and get final results.
- **Each stage lands as a usable system.** Don't move to stage N+1 until stage N is verified end-to-end.
- **External Docker network `proxy`** lets the stack's containers be reached by an existing Caddy reverse proxy and reach LAN services (upstream LLM, SearXNG). Create once with `docker network create proxy` if missing.
- **Public surface = agent only.** `PUBLIC_HOSTNAME` (in `.env.local`) is fronted by Caddy and points at the agent's OpenAI-compatible endpoint. MCP stays LAN-only.
- **Host port block: 5450, 5451, 5452, …** — contiguous, one per service in stage order. Stored as `AGENT_PORT`/`MCP_PORT`/`WEB_PORT` in `.env.local`.
- **Compose file name is `compose.yaml`** so Dockge auto-discovers the stack.

## Why LangGraph here

Explicit graph of nodes + edges with conditional routing; typed `StateGraph` state; native parallel fan-out via `Send(...)`; checkpointing to Mongo (resumable/observable/replayable runs); human-in-the-loop `interrupt()`; ToolNode integration with the upstream model's OpenAI-shaped tool-calling.

## Current state (baseline)

```
agent/                  FastAPI, /v1/chat/completions, server-side tool loop calling MCP
mcp/                    FastAPI, JSON-RPC at /mcp; Mongo, LangGraph workflows, connectors, docs
web/                    React + TS + Vite + Tailwind v4 + shadcn SPA, FastAPI serves dist/
compose.yaml            Dockge-discoverable; services: mongo, mcp, agent, web; all on `proxy`
.env.local              gitignored runtime values
.env.example            sanitized template
```

---

## Completed stages (archived → `IMPLEMENT-ARCHIVE.md`)

Full narrative + checklists for each of these live in `IMPLEMENT-ARCHIVE.md`. One-line summaries:

| Stage | Title | Outcome |
| --- | --- | --- |
| **0** | Baseline | Agent + MCP scaffold, compose stack, env hygiene, Caddy wiring, port block, repo published. |
| **1** | Mongo + LangGraph `ask_data` | Mongo 7 service + seed; `db.py` read-only access layer (`validate_spec` allowlist); `llm.py` (`chat_model`/`structured`); Mongo checkpointer; `ask_data` StateGraph; `web_research` rewritten as LangGraph; 5 new MCP tools. |
| **2** | Web frontend | Original FastAPI + Jinja/vanilla chat SPA + "Ask data" shortcut (later replaced in S8). |
| **3** | MCP hardening | **Mostly done — see below.** Session IDs + bearer auth + rate limit + client docs + Streamable-HTTP SSE framing + opt-in Caddy snippet done; only manual external-client smoke remains. |
| **4** | Deep-Agents planner/builder | Two-role LLM seam (`PLANNER_*`/`BUILDER_*`); sandbox fs/shell tools; `plan_task`/`run_plan`/`deep_agent` graphs; token-budget enforcement; step/runtime caps. |
| **6** | Spreadsheet UI + NL editing | Complete in main. Audited write-layer (`validate_write_spec`, `insert/update/delete_one`, `audit_log`); `sheet_*` MCP tools; `sheet_apply_nl` NL planner; grid UI; followups fixed (accurate row counts, NL columns, boolean/string-array editors). |
| **7** | Reactive aggregation builder | Data-Wrangler-shaped `/wrangler`: per-stage `wrangler_run_prefix`, save/load pipelines, agent-suggested pipelines; bounded stage grammar over `validate_spec`. |
| **8** | React + shadcn admin SPA | Full Vite/React/TS/Tailwind v4/shadcn rewrite; AppShell + routing + theming; Overview dashboard; Chat/Sheet/Wrangler panels; multi-stage Docker, FastAPI serves `dist/`; `audit_recent` tool. |
| **9** | Compliance workflow hub | Connector registry (Jira/Confluence/GitHub/AWS/ServiceNow/Snowflake/Mongo/Archer, mock-first); workflow collections + LangGraph orchestrator w/ approval interrupts; PDF/PPT report tools; Hub dashboard UI. |
| **10** | Service-specific micro-agents | Node-level tool scoping in `mcp/workflow/nodes.py` (each node sees only its connector's tools); least-privilege credential isolation. |
| **11** | Compliance command center | Overview promoted to live roll-up: `overview_summary` tool, KPI row, attention panel ("points of concern" rules), connector strip, multi-table region; due-date/staleness seed fixtures. |
| **12** | Domain-rich connector data + topology | Domain-shaped mock `sample_data` per connector (`schema` hints); `topology_graph` tool; React Flow `/architecture` page; Mongo bind-mount persistence (`./perm/db`). |
| **16** | Editable Jira table + HIL bulk apply | `jira_staged_changes` store + five Jira staging tools (stage/validate/revert/apply, dry-run gated by `JIRA_WRITES_ENABLED`); editable Hub grid w/ Save/Validate/Revert/Apply; wired to hosted Atlassian MCP. LanGarland rebrand. |
| **17** | Builder model → APEX + per-role max_tokens | Builder on `Qwen3.6-35B-A3B-APEX-MTP-I-Balanced` w/ 60k budget; `llm_max_tokens(role)`; agent omits empty `tools` field; `UPSTREAM_MAX_TOKENS`/`BUILDER_MAX_TOKENS`. |

---

# Open work

The remaining sections below are the stages with unfinished tasks: **3** (manual external-client smoke), **5** (TBD), **13** (one cleanup task), **14** (`S14.agent.1` StateGraph conversion), **15** (operational fixes). Stage 6 followups are complete but retained here until the next archive pass.

---

## Stage 3 — MCP server hardening for external clients

**Goal:** Make `mcp:8080/mcp` directly consumable by opencode, VS Code Chat, PiAgent, etc. (Session IDs, bearer auth, rate limiting, Streamable-HTTP SSE framing, and client docs are **done**; public exposure and manual external-client smoke remain deferred.)

### S3.transport — Streamable HTTP

- [x] **S3.transport.1 — Session IDs on `initialize`** (done; see archive)
- [x] **S3.transport.2 — SSE event framing on `GET /mcp`**
  - Done in `mcp/server.py`: `GET /mcp` validates bearer/session headers, emits `ready` + idle `ping` SSE events, and mirrors same-session JSON-RPC POST responses as `event: message` for Streamable-HTTP clients. POST remains synchronous by default; `Prefer: respond-async` or `X-MCP-Response-Mode: sse` returns HTTP 202 and delivers the response on SSE.

### S3.expose — Publish MCP via Caddy

- [x] **S3.expose.1 — Decide MCP public surface** — **Decision: LAN-only for now.** The agent already exposes MCP tools via `/v1/chat/completions` at `${PUBLIC_HOSTNAME}`; IDE clients reach `mcp:8080/mcp` via host port or VPN. Public Caddy routing remains opt-in only when an external MCP surface is explicitly needed.
- [x] **S3.expose.2 — Caddy labels / static snippet for MCP**
  - Static snippet documented in `caddy/Caddyfile.snippet.example` as an opt-in `handle_path /mcp*` reverse proxy to `sglandsimple-mcp:8080` with `flush_interval -1` for SSE. Compose remains LAN-only by default; do not enable public routing without `MCP_AUTH_TOKEN`.

### S3.clients — Client recipes

- [x] **S3.clients.1 — `docs/clients.md` with paste-ready configs** (done)

### S3.verify

- [ ] **S3.verify.1 — External-client smoke**
  - Depends on manually testing opencode or VS Code Chat against `http://<host>:${MCP_PORT}/mcp` from a remote machine.

---

## Stage 6 — Spreadsheet UI + NL editing — open follow-ups

> The stage is complete and verified live (audited write-layer, `sheet_*` tools, `sheet_apply_nl`, grid UI). Full narrative + the S6.env/db/mcp/web/verify checklists are in `IMPLEMENT-ARCHIVE.md`. Only the known nits below remain.
>
> **Note:** these followups predate the Stage-8 React rewrite. The sheet UI now lives in **`web/src/routes/sheet.tsx`** (React + TanStack Query), not the old `web/static/sheet.js`. Apply the fixes there.

### S6.followups — Known nits (not blockers)

- [x] **S6.followups.1 — `total` row count drifts after writes**
  - Files: `mcp/db.py::get_rows`.
  - Done: `get_rows()` now uses `count_documents({})` (unconditional — cheap on these tiny collections) so the grid header stays accurate after inserts/deletes.

- [x] **S6.followups.2 — Reactivity after NL edits**
  - Files: `web/src/routes/sheet.tsx`.
  - Done: after an NL apply, `op.field`s from `res.applied` are unioned into an `nlExtraColumns` state set and merged into the visible columns; reset on collection change. Newly-`$set` fields now appear immediately.

- [x] **S6.followups.3 — Cell type inference for booleans / arrays**
  - Files: `web/src/routes/sheet.tsx`.
  - Done: `isBoolField`/`isStringArrayField` predicates added; booleans render as a checkbox committing a real boolean, string arrays render a comma/tag editor committing a `string[]` (via a new `commitValue` helper); text/number/date paths unchanged.

---

## Stage 13 — Fleet-Dispatch design system — open cleanup

> The restyle (navy/amber/teal tokens + Roboto) is complete and verified; full narrative + checklist in `IMPLEMENT-ARCHIVE.md`. Only the token-migration cleanup remains.

- [ ] **S13.cleanup.1 — Migrate hardcoded literals to tokens**
  - Files: `web/src/components/hub-columns.tsx`, `web/src/routes/hub.tsx`, `web/src/components/workflow-stepper.tsx`, others surfaced by grep.
  - Done when: load-bearing hardcoded Tailwind color literals are replaced with semantic tokens / on-brand equivalents; status red/green retained for meaning.

---

## Stage 14 — Docs Wiki library (in-app MkDocs/Docusaurus-style) + Confluence sync

> **Pick-up point.** Docs today are scattered Markdown at the repo root (`README.md`, `IMPLEMENT.md`, `CLAUDE.md`, etc.) with no index, lifecycle, or audience control. Stage 14 stands up a **documentation library inside the app** — an MkDocs/Docusaurus-style wiki — as the single home for all docs. Each doc carries lifecycle/visibility **flags** and **tags**; **public** docs sync to **Confluence** mirroring the same tree; an **agent workflow** keeps the two in sync and proposes improvements. Builds on the Stage-9 Confluence connector and the Stage-6 audited write-layer.
>
> **Status:** backend, migration, web proxies/hooks, and `/docs` SPA are done in main (`S14.model.1`, `S14.api.1`, `S14.migrate.1`, `S14.web.1`, `S14.web.2`, `S14.sync.1` ✅). `S14.agent.1` remains partial: the procedural agent is reachable from the UI, but still needs conversion to a checkpointed LangGraph `StateGraph` with interrupt/resume at the apply gate.

### 14a. Scope of "100% of our docs"

- **Migration**: existing root/`docs/` Markdown files are imported as the initial corpus (one wiki doc per file, path-mapped, v1). New docs are authored in the wiki.
- **Coverage rule**: going forward, design notes / runbooks / specs land in the wiki, not as ad-hoc root `.md` files.

### 14b. Data model (MongoDB — system of record)

New collections (audited via the Stage-6 write-layer, `source="docs_*"`):

- `docs` — `{_id, slug, path (e.g. "runbooks/rds-audit-logging"), title, body_md, tags[], status, visibility, owner, version, confluence_page_id?, last_reviewed_at, created_at, updated_at}`.
- `doc_revisions` — append-only history `{_id, doc_id, version, body_md, author, created_at, note}`.
- `doc_sync_log` — Confluence reconciliation events `{_id, doc_id, direction, confluence_page_id, action, at, detail}`.

**Flags / lifecycle** as two orthogonal fields:

- `visibility`: `internal` (default) | `public` (eligible for Confluence sync).
- `status`: `up_to_date` | `needs_attention` | `archivable` | `archived`.
- `tags[]`: free-form topical tags driving filtering/search and Confluence labels.

Lifecycle rules (computed/assisted): `needs_attention` auto-set when `now - last_reviewed_at > DOCS_REVIEW_DAYS`; `archivable` suggested when stale **and** unreferenced; `archived` hides from default views but is retained. Transitions audited.

### 14c. Architecture (server-side first, web proxies)

- `mcp/docs.py` — CRUD + search over `docs`/`doc_revisions`. Tools: `docs_list` (tree + filters), `docs_get`, `docs_upsert` (writes a revision), `docs_set_flags`, `docs_search`. All writes go through the audited write-layer. **(Done.)**
- `mcp/docs_sync.py` — Confluence reconciliation on the Stage-9 Confluence connector; maps wiki `path` → space + page tree; pushes **public** docs; logs to `doc_sync_log`. Gated by `DOCS_SYNC_ENABLED` + `CONN_CONFLUENCE_ENABLED` + `WORKFLOW_WRITES_ENABLED` (dry-run by default). **(Done.)**
- `web/main.py` — `/api/docs*` proxies (`GET /api/docs/tree`, `GET /api/docs/{slug}`, `POST /api/docs`, `POST /api/docs/{slug}/flags`, `GET /api/docs/search`, `POST /api/docs/sync`, `POST /api/docs/agent`). **(Done — S14.web.1.)**
- Web SPA — a `/docs` route: left nav tree (grouped by path), article view (reuse the existing `react-markdown` + `remark-gfm` + `rehype-highlight` `Markdown` component), an editor (textarea + preview), per-doc flag/tag controls, search box, status/visibility badges, and a `needs_attention`/`archivable` review queue. **(Done — S14.web.2.)**

### 14d. Confluence sync (same structure)

- **Mapping**: wiki `path` segments → Confluence ancestor pages; `tags[]` → labels; `title` → page title; `body_md` → storage format (server-side).
- **Direction**: primary push (wiki → Confluence) for `public` docs; detect drift on pull (mark `needs_attention` rather than overwrite).
- **Idempotency**: store `confluence_page_id`; sync updates that page in place.
- **Safety**: no live writes unless `CONN_CONFLUENCE_ENABLED` and `WORKFLOW_WRITES_ENABLED`; otherwise dry-run plan.

### 14e. Agent workflow (sync + suggestions)

A LangGraph workflow (reuse the Stage-9 orchestrator pattern + checkpointer), exposed as MCP tool `docs_agent_run` and a `/api/docs/agent` proxy:

1. **Reconcile** — diff wiki ↔ Confluence for `public` docs; push/queue per 14d; log to `doc_sync_log`.
2. **Triage** — flag stale/unreferenced docs (`needs_attention`/`archivable`) with reasons.
3. **Suggest** — for `needs_attention` docs, draft improvement suggestions as a **proposed revision** (never auto-applied) + rationale; human approves/edits before it becomes a new `doc_revisions` entry. HIL interrupt at the apply gate.

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
3. Setting `visibility=public` + running sync (dry-run) yields a `doc_sync_log` plan mirroring the wiki path into `DOCS_CONFLUENCE_SPACE`; enabling the Stage-9 flags performs the create/update and stores `confluence_page_id`.
4. A doc past `DOCS_REVIEW_DAYS` auto-shows `needs_attention`; an archived doc is hidden from default views but retrievable.
5. `docs_agent_run` (dry-run) reconciles, triages, and emits suggested revisions as proposals — none auto-applied; approving one creates a new revision (audited).
6. Every doc write is audited; sync respects the three flags (no outbound calls when off).

### Task checklist — Stage 14

- [x] **S14.model.1 — Docs collections + audited writes** ✅ DONE & verified live
  - Files: `mongo-seed/14-docs.js`, `mcp/db.py` (docs system-of-record helpers).
  - Done: three collections with the 14b shape; every write routes through `_audit` with `source="docs_*"`.

- [x] **S14.api.1 — `mcp/docs.py` CRUD + search tools** ✅ DONE & verified live
  - Files: `mcp/docs.py`, `mcp/server.py` (7 docs tools registered + dispatched).
  - Done: `docs_list`/`docs_get`/`docs_upsert`/`docs_set_flags`/`docs_search` work; `docs_upsert` appends a `doc_revisions` entry + bumps version; flags validated against the 14b enums.

- [x] **S14.migrate.1 — Import existing Markdown corpus** ✅ DONE
  - Files: `scripts/import_docs.py` (new).
  - Done: stdlib-only MCP JSON-RPC client (initialize → `docs_upsert` per file) walks root `*.md`, `docs/*.md`, `scripts/*.md`; H1-derived titles, path-mapped slugs (`docs/clients.md`→`clients`/`docs/clients`), inferred default tags, `status=up_to_date`/`visibility=internal`; idempotent (by-slug upsert); `--dry-run` flag; `MCP_URL`/`MCP_AUTH_TOKEN` env. Run against the live stack to populate.

- [x] **S14.web.1 — `/api/docs*` proxies + `useDocs*` hooks** ✅ DONE
  - Files: `web/main.py`, `web/src/lib/queries.ts`, `web/src/lib/types.ts`.
  - Done: 7 proxy routes (tree/search/get/upsert/flags/sync/agent) via the existing `_mcp_tool`/`_extract_json_block` pattern; full TS type set (no `any`); hooks `useDocsTree`/`useDoc`/`useDocsSearch`/`useUpsertDoc`/`useSetDocFlags`/`useDocsSync`/`useDocsAgent` with query keys + invalidation.

- [x] **S14.web.2 — Docs Wiki SPA route** ✅ DONE
  - Files: `web/src/routes/docs.tsx` (new), `web/src/App.tsx`, `web/src/components/app-sidebar.tsx`.
  - Done: `/docs` route registered + `BookText` sidebar entry; path-grouped nav tree, Markdown article view (reuses the `Markdown` component), textarea editor with preview toggle, flag/tag controls (status+visibility selects, tag editor), search box, status/visibility badges, `needs_attention`/`archivable` review queue, agent + sync panels, loading/empty/error states.

- [x] **S14.sync.1 — Confluence reconciliation (same tree)** ✅ DONE & verified live (dry-run)
  - Files: `mcp/docs_sync.py`, `mcp/connectors/confluence.py` (`confluence_update_page` + deterministic create page id), `mcp/server.py` (`docs_sync` tool).
  - Done: public docs map path→Confluence ancestors+page; create stores `confluence_page_id`, subsequent runs update in place; `tags[]`→labels; actions logged to `doc_sync_log`; dry-run by default. Pull-side drift detection is stubbed for the mock connector.

- [~] **S14.agent.1 — Docs agent workflow (sync + suggestions)** ◑ PARTIAL — procedural form done & verified
  - Files: `mcp/docs_agent.py`, `mcp/server.py` (`docs_agent_run`).
  - Done: reconcile→triage→suggest runs; triage flags stale/unreferenced; suggestions are HIL proposals returning `proposed_body_md`, never auto-applied; applying one is a separate audited `docs_upsert`.
  - Remaining: not yet a checkpointed LangGraph `StateGraph` (so a run can interrupt at the apply gate and resume). The `/api/docs/agent` web proxy + `useDocsAgent` hook now exist (landed with S14.web.1), so the procedural agent is reachable from the UI; only the StateGraph conversion is left.

---

## Stage 15 — Operational fixes & UX quick-wins

> Standalone, independent fixes that don't belong to a themed stage. Each is self-contained; pick up in any order.

### 15a. Wrangler — bulk field projection ("Add all" / "Exclude all")

**Problem.** In the Wrangler (`/wrangler`), a `project` stage builds its field list one row at a time via the "+ field" button (`web/src/routes/wrangler.tsx`, the `st.kind === "project"` block — `projects: [{field, include}]`). Building a projection over a wide collection is tedious; there's no way to seed all fields at once or to start from "exclude everything."

**Goal.** Add two one-click actions to each `project` stage editor:
- **Add all fields** — populate `projects` with every field from the current sample (`fieldNames`, computed from `sample.data.field_summary`) as `{field, include: true}`, de-duplicated against what's already there.
- **Exclude all (`*:0`)** — set the stage to an exclude-everything projection: all `fieldNames` as `{field, include:false}` (check `compileStage`/`newStage` before assuming a `{ "*": 0 }` shorthand).

Both respect the existing live-rerun/debounce path (`liveRerun(idx)`); a "clear fields" affordance is a nice-to-have.

- [ ] **S15.wrangler.1 — Bulk projection actions on the project stage**
  - Files: `web/src/routes/wrangler.tsx` (project-stage block + field-chip helpers), the wrangler-stages helper (`compileStage`/`newStage`/`EditableStage` — imported at top of `wrangler.tsx`).
  - Done when: a `project` stage shows **Add all fields** and **Exclude all (`*:0`)** buttons; "Add all" seeds all sampled fields as includes, "Exclude all" sets all to exclude; both flow through live-rerun and round-trip through save/`compileStage`; no illegal mixed projection (exclude-all is all-`:0`, add-all is all-`:1`).

### 15b. Ask Data — fix timeouts / empty responses

**Problem.** The Chat **"Ask Data"** function (`/api/ask_data` → `mcp/ask_data.py::run_ask_data`, surfaced in `web/src/routes/chat.tsx`) **times out and returns no data**. The graph makes several **sequential** upstream LLM calls (`discover_schema → plan_query → execute_query → fan_out interpret_doc per doc → synthesize`) throttled by `LLM_CONCURRENCY=2` and fanned out up to `ASK_DATA_MAX_DOCS=10`; on the slow upstream the end-to-end latency exceeds the client/proxy timeout, so the UI gets nothing.

**Goal.** Make Ask Data return within the request budget, and degrade gracefully instead of returning empty.

Address (in priority order):
1. **Timeout budget alignment** — confirm the actual failure (client fetch vs. web `REQUEST_TIMEOUT` vs. agent/MCP upstream timeout vs. graph wall-clock). Align them; give `run_ask_data` an explicit overall deadline (`asyncio.wait_for`) so it returns a partial/explanatory answer rather than hanging.
2. **Reduce serial LLM hops** — the per-doc fan-out is the main cost. Lower `ASK_DATA_MAX_DOCS`, raise `LLM_CONCURRENCY` if the upstream allows, or collapse per-doc interpretation into a single batched call when the doc set is small.
3. **Graceful failure** — on timeout/partial, return the rows actually fetched (`execute_query` output) with a "summarization timed out, showing raw results" note. Surface a clear error in `chat.tsx` instead of a silent empty bubble.
4. **Streaming/feedback (optional)** — emit progress so the UI shows it's working.

- [ ] **S15.askdata.1 — Make Ask Data return within budget (no more timeouts)**
  - Files: `mcp/ask_data.py` (deadline, fan-out tuning, partial-result fallback), `web/main.py` (`/api/ask_data` timeout + error passthrough), `web/src/routes/chat.tsx` (error/empty-state surfacing), env defaults in `.env.example`/compose.
  - Done when: an Ask Data question over a seeded collection returns a useful answer (or a clear partial/error) within the request budget — never a silent empty response; verified with `scripts/smoke_ask_data.sh`. Capture the root-cause finding (which timeout fired) in the commit/PR.

---

## Stage 5 — GitHub Copilot as an upstream provider (TBD)

**Goal:** Let the stack target a GitHub Copilot subscription as `UPSTREAM_*` so the same agent + MCP plumbing can run on Copilot-hosted models.

> Status: **TBD.** Not started. The §5e open questions must be resolved before scheduling.

### 5a. Why this is non-trivial

Copilot is **not** a clean OpenAI base-URL + key. Three extra moving parts:

1. **GitHub device-flow login** → a `ghu_…` GitHub OAuth token (per-user, long-lived).
2. **Token exchange** → `GET https://api.github.com/copilot_internal/v2/token` with `Authorization: token ghu_…` returns a short-lived HMAC bearer (~30 min TTL). Must be cached and refreshed on expiry/401.
3. **Editor-spoof headers** on every request: `Copilot-Integration-Id`, `Editor-Version`, `Editor-Plugin-Version`, `User-Agent`. Drift in any can flip the account into a rejected state.

The chat endpoint is OpenAI-shaped (`POST https://api.githubcopilot.com/chat/completions`) for most models; Codex models use `/responses` and are out of scope.

### 5b. Two implementation routes

Pick one in S5.decide.1.

**Route A — Sidecar proxy (low effort).** Run a community proxy (e.g. `ericc-ch/copilot-api`) as a new compose service handling device flow, token cache, refresh, header spoofing, exposing a local `/v1/chat/completions`. Agent and MCP point at `UPSTREAM_BASE_URL=http://copilot-api:4141/v1`. No Python changes. Cons: third-party dep, header-rotation breakage.

**Route B — Native client in this repo (more work).** Add `mcp/copilot_auth.py` (device flow, `ghu_` storage, bearer cache+refresh) and inject editor headers into the `httpx.AsyncClient` calls in `mcp/llm.py` and `agent/main.py` when `UPSTREAM_PROVIDER=copilot`. Cons: we own the breakage surface; headless device-flow UX needs care.

### 5c. Constraints we already know will bite

- **Against Copilot's ToS.** Non-editor use is unsanctioned; bursty parallel traffic (web_research fan-out, Stage-4 builder loop) draws attention. Mitigation in S5.safety.
- **Tighter rate limits** than the self-hosted endpoint — `LLM_CONCURRENCY`/`ASK_DATA_MAX_DOCS` must drop (likely 1 concurrent + smaller fan-out).
- **No grammar-enforced constrained JSON.** `structured()` must make prompt-only JSON + Pydantic validate + bounded retry the *primary* path under Copilot.
- **Tool-calling varies by model.** Restrict `UPSTREAM_MODEL` to a known-good tool-calling model (`claude-sonnet-4.5`, `gpt-4.1`; Codex out).

### 5d. Env surface (proposed)

| Var | Default | Required | Notes |
| --- | --- | --- | --- |
| `UPSTREAM_PROVIDER` | `openai` | no | `copilot` enables the auth/headers path (B) or selects the sidecar (A). |
| `COPILOT_TOKEN_FILE` | `/data/copilot/ghu_token` | no | Host-mounted `ghu_…` token. |
| `COPILOT_BEARER_TTL` | `1500` | no | Seconds to cache the exchanged bearer (refresh slightly early). |
| `COPILOT_EDITOR_VERSION` | `vscode/1.104.1` | no | Editor-spoof header. |
| `COPILOT_PLUGIN_VERSION` | `copilot-chat/0.26.7` | no | Editor-plugin-version header. |
| `COPILOT_INTEGRATION_ID` | `vscode-chat` | no | Integration-id header. |

### 5e. Open questions (resolve before scheduling)

1. **Route A or B?**
2. **Which Copilot model id?** (verify tool-calling under the agent loop first)
3. **Where does device-flow login happen?** (headless container UX; where `ghu_…` lives)
4. **Does Stage-4 split survive Copilot rate limits?** (else planner-only, or postpone)
5. **Constrained-JSON fallback acceptable?** (verify `ask_data`/`web_research` still parse)

### 5f. Verification (intent)

1. `UPSTREAM_PROVIDER=copilot` → `curl … "model":"<copilot-model>"` returns a completion.
2. Agent tool loop dispatches an `ask_data` call end-to-end via Copilot.
3. Bearer refresh after TTL succeeds without restart.
4. Reduced concurrency produces no 429s across the three smoke tests.
5. Route choice documented in `docs/clients.md`.

### Task checklist — Stage 5

> All tasks below are **TBD**. Resolve §5e and pick a route (S5.decide.1) before starting anything else.

- [ ] **S5.decide.1 — Pick Route A (sidecar) vs Route B (native client)** — record decision + rationale in §5b; prune downstream tasks to match. Depends on §5e Q1.
- [ ] **S5.decide.2 — Pick the Copilot model id** — chosen model verified to honor OpenAI `tools` against the agent loop; recorded in `.env.example`. Depends on §5e Q2.
- [ ] **S5.deps.1 — Add Stage-5 env vars to `.env.example`** — all six §5d vars present with defaults.
- [ ] **S5.deps.2 — Host-mounted token directory** — `./copilot/` bind-mounts to `/data/copilot` in the owning service(s), uid 1000, gitignored. Depends on S5.decide.1.
- [ ] **S5.proxy.1 — Add `copilot-api` service to `compose.yaml`** (Route A) — starts, joins `proxy`, exposes `4141` in-stack, healthcheck green. Depends on S5.decide.1(A), S5.deps.2.
- [ ] **S5.proxy.2 — One-shot device-flow login** (Route A) — `scripts/copilot_login.sh` persists `ghu_…`; `curl :4141/v1/models` succeeds. Depends on S5.proxy.1.
- [ ] **S5.proxy.3 — Point upstream at the sidecar** (Route A) — `UPSTREAM_BASE_URL=http://copilot-api:4141/v1`; stack comes up against it. Depends on S5.proxy.2, S5.decide.2.
- [ ] **S5.native.1 — `mcp/copilot_auth.py` (device flow + bearer cache)** (Route B) — `python -m mcp.copilot_auth login` writes `ghu_…`; `get_bearer()` caches + refreshes on 401/TTL; thread-safe. Depends on S5.decide.1(B), S5.deps.1/2.
- [ ] **S5.native.2 — Copilot-aware client wrapper in `mcp/llm.py`** (Route B) — under `copilot`, `AsyncOpenAI` built with a custom `httpx.AsyncClient` injecting the four headers + bearer per request; non-Copilot path unchanged. Depends on S5.native.1.
- [ ] **S5.native.3 — Same wrapping in `agent/main.py`** (Route B) — identical header set. Depends on S5.native.2.
- [ ] **S5.native.4 — Document login UX** — `docs/clients.md` "Copilot as upstream" section with the `docker compose exec` recipe + where `ghu_…` lands + revoke. Depends on S5.native.1.
- [ ] **S5.json.1 — Prompt-only JSON primary path when provider=copilot** — `structured()` skips `response_format=json_schema`, uses prompt-only + Pydantic + 1 retry; logs the path taken. Depends on S5.decide.1.
- [ ] **S5.safety.1 — Drop concurrency defaults under Copilot** — default `LLM_CONCURRENCY=1`, `ASK_DATA_MAX_DOCS=2` unless overridden. Depends on S5.decide.1.
- [ ] **S5.safety.2 — Backoff on 429/403** — exponential backoff w/ jitter, max 3 retries, then clear error. Depends on S5.decide.1.
- [ ] **S5.verify.1 — Direct curl against agent** — Copilot model returns a completion; logs show Copilot endpoint. Depends on route tasks.
- [ ] **S5.verify.2 — `ask_data` end-to-end via Copilot** — `scripts/smoke_ask_data.sh` passes; JSON fallback handles schema misses. Depends on S5.verify.1, S5.json.1.
- [ ] **S5.verify.3 — Bearer refresh works** — invalidated/expired bearer → next call refreshes + succeeds without restart. Depends on S5.verify.1.
- [ ] **S5.verify.4 — Sustained-burst rate-limit check** — Stage-1 smoke 10× back-to-back, no 429s under dropped defaults. Depends on S5.safety.1, S5.verify.2.
- [ ] **S5.verify.5 — Decide on Stage-4 + Copilot compatibility** — `deep_agent` runs (planner on Copilot + builder self-hosted), or combo marked out-of-scope and §5e Q4 closed. Depends on S5.verify.4.

---

## Out of scope (for now)

- Multi-tenant auth (per-user Mongo namespaces).
- Streaming responses from the agent (`stream: true`). Still 400s.
- Observability (OTel, structured logs to a collector).
- Vector search / semantic retrieval.
- SSE server-push of POST responses (deferred in S3.transport.2).
- Public Caddy routing for MCP (deferred in S3.expose.2).

---

## Env surface (all stages)

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
| `BUILDER_BASE_URL` | — | yes (stage 4) | 4 | builder/executor LLM endpoint |
| `BUILDER_MODEL` | — | yes (stage 4) | 4 | builder model id |
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
| `WEB_BUILD_MODE` | `production` | no | 8 | `vite build` mode |
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
| `SERVICENOW_TOKEN` | — | no | 9 | ServiceNow auth |
| `CONN_SNOWFLAKE_ENABLED` | `false` | no | 9 | Enable Snowflake SQL adapter |
| `SNOWFLAKE_ACCOUNT` | — | no | 9 | Snowflake account/locator |
| `SNOWFLAKE_USER` | — | no | 9 |  |
| `SNOWFLAKE_TOKEN` | — | no | 9 | Snowflake auth |
| `CONN_ARCHER_ENABLED` | `false` | no | 9 | Placeholder; mock data when off |
| `REPORT_OUTPUT_DIR` | `/sandbox/reports` | no | 9 | Where generated PDF/PPT land |
| `OVERVIEW_DUE_SOON_DAYS` | `14` | no | 11 | Window for the "due soon" attention rule |
| `OVERVIEW_STALE_DAYS` | `7` | no | 11 | No-update window for the "stalled" rule |
| `OVERVIEW_ATTENTION_LIMIT` | `10` | no | 11 | Max rows in the attention panel |
| `OVERVIEW_TABLE_ROWS` | `5` | no | 11 | Rows shown per mini-table |
| `OVERVIEW_POLL_MS` | `30000` | no | 11 | Front-end poll cadence for `/api/overview` |
| `CONFLUENCE_BASE_URL` | `https://enterprise.atlassian.net/wiki` | no | 12 | Base for mock Confluence article links |
| `JIRA_BASE_URL` | `https://enterprise.atlassian.net` | no | 12 | Base for mock Jira issue links |
| `TOPOLOGY_INCLUDE_DISABLED` | `true` | no | 12 | Show disabled connectors as nodes (greyed) |
| `DOCS_REVIEW_DAYS` | `90` | no | 14 | Age after which a doc auto-flags `needs_attention` |
| `DOCS_CONFLUENCE_SPACE` | `COMP` | no | 14 | Confluence space key public docs sync into |
| `DOCS_SYNC_ENABLED` | `false` | no | 14 | Master gate for Confluence push |
| `DOCS_DEFAULT_VISIBILITY` | `internal` | no | 14 | New-doc default visibility |
| `JIRA_WRITES_ENABLED` | `false` | no | 16 | When `false`, `jira_apply_staged` produces a dry-run plan |
| `JIRA_STAGE_MAX_EDITS` | `100` | no | 16 | Hard cap on issues per `jira_stage_edits` call |
| `UPSTREAM_MAX_TOKENS` | `0` | no | 17 | Default `max_tokens` forwarded to upstream when client omits it |
| `BUILDER_MAX_TOKENS` | `60000` | no | 17 | Output budget for builder LLM calls |
| `UPSTREAM_PROVIDER` | `openai` | no | 5 (TBD) | `copilot` enables Copilot path |
| `COPILOT_TOKEN_FILE` | `/data/copilot/ghu_token` | no | 5 (TBD) | Host-mounted `ghu_…` token |
| `COPILOT_BEARER_TTL` | `1500` | no | 5 (TBD) | Bearer cache TTL seconds |
| `COPILOT_EDITOR_VERSION` | `vscode/1.104.1` | no | 5 (TBD) | Editor-spoof header |
| `COPILOT_PLUGIN_VERSION` | `copilot-chat/0.26.7` | no | 5 (TBD) | Editor-plugin-version header |
| `COPILOT_INTEGRATION_ID` | `vscode-chat` | no | 5 (TBD) | Integration-id header |

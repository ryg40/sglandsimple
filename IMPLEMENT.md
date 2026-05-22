# IMPLEMENT.md — sglandsimple enterprise rollout (LangGraph edition)

This document is the implementation plan for evolving the current stack into an enterprise-shaped pattern: **server-side LangGraph agent workflows over a NoSQL store, fronted by both a web UI and direct MCP access from IDE/agent clients (opencode, VS Code Chat, PiAgent).**

> The repo name `sglandsimple` predates the framework choice. Despite the name, **this plan uses LangGraph**, not SGLang.

> **Archive note (2026-05-22):** Stages 0–2, 4, 7–12, 13, 15, 16, 17 are complete and verified. Their full narrative + task checklists were moved to **`IMPLEMENT-ARCHIVE.md`** to keep this file focused on open work. See the "Completed stages" table below for one-line summaries; open `IMPLEMENT-ARCHIVE.md` for the full detail of any archived stage. This file retains the header/ground-rules, the **Env surface** table (live reference), and the **full content of every stage with open tasks** (3, 5, 6, 14, 18, 19, 20, 21, 22). Stages 6 (followups), 13, 14, and 15 are complete but retained here until the next archive pass.

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
| **13** | Fleet-Dispatch design system | Navy/amber/teal tokens + Roboto + token-migration cleanup (6 components). Complete — eligible for archive. |
| **15** | Operational fixes & UX quick-wins | ask_data deadline + batch notes + wrangler bulk projection + pipeline code view. Complete — eligible for archive. |

---

# Open work

The remaining sections below are the stages with unfinished tasks: **3** (manual external-client smoke), **5** (TBD — shelved), **13** (cleanup DONE — eligible for archive), **14** (DONE — eligible for archive), **15** (DONE — eligible for archive), **18** (architecture diagram v2 — 3 tasks remaining), **19** (web auth/RBAC — nearly complete, 2 tasks remaining), **20** (Standup Jira cockpit — initial slice done, 6 tasks remaining), **21** (Deep Agent platform — all TBD), **22** (UX/chat polish + Wrangler derived fields — all TBD). Stages **6** (followups — all done), **14** (Docs Wiki), and **15** (operational fixes) are complete but retained here until the next archive pass.

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

- [x] **S13.cleanup.1 — Migrate hardcoded literals to tokens** ✅ DONE
  - Files: `web/src/components/hub-columns.tsx`, `web/src/routes/hub.tsx`, `web/src/components/workflow-stepper.tsx`, `web/src/components/connection-bubble.tsx`, `web/src/components/relate-panel.tsx`, `web/src/routes/workflow.tsx`.
  - Done: load-bearing hardcoded Tailwind color literals replaced with semantic tokens / on-brand equivalents across 6 components; status red/green retained for meaning. Ported from pi-stage13-15 worktree; workflow.tsx token changes applied surgically to preserve S19 auth gating. Committed `fdd3c02`.
  - **Stage 13 is now COMPLETE — eligible for archival to IMPLEMENT-ARCHIVE.md.**

---

## Stage 14 — Docs Wiki library (in-app MkDocs/Docusaurus-style) + Confluence sync

> **Pick-up point.** Docs today are scattered Markdown at the repo root (`README.md`, `IMPLEMENT.md`, `CLAUDE.md`, etc.) with no index, lifecycle, or audience control. Stage 14 stands up a **documentation library inside the app** — an MkDocs/Docusaurus-style wiki — as the single home for all docs. Each doc carries lifecycle/visibility **flags** and **tags**; **public** docs sync to **Confluence** mirroring the same tree; an **agent workflow** keeps the two in sync and proposes improvements. Builds on the Stage-9 Confluence connector and the Stage-6 audited write-layer.
>
> **Status: COMPLETE & verified live.** All `S14.*` tasks done: backend system-of-record + CRUD/search tools, Markdown corpus migration script, web proxies/hooks, `/docs` SPA, Confluence reconciliation (dry-run), and the docs agent — now a checkpointed LangGraph `StateGraph` with a human-in-the-loop interrupt/resume at the apply gate. Eligible for archival to `IMPLEMENT-ARCHIVE.md`.

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

- [x] **S14.agent.1 — Docs agent workflow (sync + suggestions)** ✅ DONE & verified live
  - Files: `mcp/docs_agent.py` (LangGraph `StateGraph`), `mcp/server.py` (`docs_agent_run` + resume args), `web/main.py` (`/api/docs/agent` run_id/resume passthrough), `web/src/lib/{types,queries}.ts`, `web/src/routes/docs.tsx` (apply-gate UI).
  - Done: rewritten as a checkpointed `StateGraph` `do_reconcile → do_triage → do_suggest → apply_gate (interrupt) → apply_approved → END`, compiled with a `MemorySaver` keyed by `thread_id`. A fresh run pauses at the gate (`status="waiting_approval"`, returns `run_id` + proposals); resuming with `{run_id, resume_decision}` (slugs / `"all"` / `"reject"`) applies only approved proposals via an audited `docs_upsert` (`source="docs_agent_apply"`). The `/docs` Agent panel renders the gate with per-proposal checkboxes + Apply selected / Apply all / Reject.
  - Verified live (mcp+web rebuilt): fresh run → `waiting_approval`; resume `reject` → `completed`, no writes; resume `all` on a seeded `needs_attention` doc → doc v1→v2, status→`up_to_date`, new audited revision; web proxy returns the run_id/status payload.

---

## Stage 15 — Operational fixes & UX quick-wins

> Standalone, independent fixes that don't belong to a themed stage. Each is self-contained; pick up in any order.

### 15a. Wrangler — bulk field projection ("Add all" / "Exclude all")

**Problem.** In the Wrangler (`/wrangler`), a `project` stage builds its field list one row at a time via the "+ field" button (`web/src/routes/wrangler.tsx`, the `st.kind === "project"` block — `projects: [{field, include}]`). Building a projection over a wide collection is tedious; there's no way to seed all fields at once or to start from "exclude everything."

**Goal.** Add two one-click actions to each `project` stage editor:
- **Add all fields** — populate `projects` with every field from the current sample (`fieldNames`, computed from `sample.data.field_summary`) as `{field, include: true}`, de-duplicated against what's already there.
- **Exclude all (`*:0`)** — set the stage to an exclude-everything projection: all `fieldNames` as `{field, include:false}` (check `compileStage`/`newStage` before assuming a `{ "*": 0 }` shorthand).

Both respect the existing live-rerun/debounce path (`liveRerun(idx)`); a "clear fields" affordance is a nice-to-have.

- [x] **S15.wrangler.1 — Bulk projection actions on the project stage** ✅ DONE
  - Files: `web/src/routes/wrangler.tsx` (project-stage block + field-chip helpers).
  - Done: a `project` stage now shows **Add all fields**, **Exclude all (`*:0`)**, and **Clear fields** actions. Add-all de-dupes sampled/existing fields and normalizes to all includes; exclude-all emits explicit sampled-field excludes; all actions use the existing `onChange` → live-rerun/save/`compileStage` path with no mixed projection.

### 15b. Wrangler — live MongoDB aggregation pipeline code view

**Problem.** Wrangler teaches users how to build data transformations visually, but teammates cannot see the actual MongoDB aggregation pipeline JavaScript being generated. That makes it harder for team members to learn database query skills or copy a working pipeline into an editor, shell, runbook, or review comment.

**Goal.** Add a code-focused column/panel in `/wrangler` that displays the full current MongoDB aggregation pipeline as JavaScript and updates dynamically after each successful stage/run. Users should be able to copy the entire pipeline or stage-specific snippets to the clipboard.

Requirements:

- Show a readable JS snippet such as:
  ```js
  db.<collection>.aggregate([
    { $match: { ... } },
    { $project: { ... } }
  ])
  ```
- Update the displayed pipeline after successful preview/rerun/save operations so the code always matches the currently valid staged pipeline.
- Show per-stage snippets next to, or underneath, each stage so users can copy individual `$match`, `$project`, `$group`, etc. fragments.
- Include **Copy full pipeline** and **Copy stage** buttons with clear success/error feedback.
- If the current visual config is invalid or has not successfully run yet, keep showing the last successful pipeline and label it as such (`last successful`, `current invalid`, etc.) instead of teaching from broken code.
- Prefer a syntax-highlighted, monospace code block; avoid introducing a heavy dependency unless the existing markdown/highlight stack can be reused.

- [x] **S15.wrangler.2 — Live aggregation pipeline JS column + copy actions**
  - Files: `web/src/routes/wrangler.tsx`.
  - Done: `/wrangler` now shows an XL-screen right-side MongoDB aggregation JS panel with `db.<collection>.aggregate([...])`, Copy full pipeline, per-stage snippets with Copy stage buttons, and success/error toasts. The code view updates after successful preview/run, save, or load; in-progress invalid/untested edits preserve and label the last successful pipeline instead of overwriting it.
  - Verified: `cd web && npm run build` passes.

### 15c. Ask Data — fix timeouts / empty responses

**Problem.** The Chat **"Ask Data"** function (`/api/ask_data` → `mcp/ask_data.py::run_ask_data`, surfaced in `web/src/routes/chat.tsx`) **times out and returns no data**. The graph makes several **sequential** upstream LLM calls (`discover_schema → plan_query → execute_query → fan_out interpret_doc per doc → synthesize`) throttled by `LLM_CONCURRENCY=2` and fanned out up to `ASK_DATA_MAX_DOCS=10`; on the slow upstream the end-to-end latency exceeds the client/proxy timeout, so the UI gets nothing.

**Goal.** Make Ask Data return within the request budget, and degrade gracefully instead of returning empty.

Address (in priority order):
1. **Timeout budget alignment** — confirm the actual failure (client fetch vs. web `REQUEST_TIMEOUT` vs. agent/MCP upstream timeout vs. graph wall-clock). Align them; give `run_ask_data` an explicit overall deadline (`asyncio.wait_for`) so it returns a partial/explanatory answer rather than hanging.
2. **Reduce serial LLM hops** — the per-doc fan-out is the main cost. Lower `ASK_DATA_MAX_DOCS`, raise `LLM_CONCURRENCY` if the upstream allows, or collapse per-doc interpretation into a single batched call when the doc set is small.
3. **Graceful failure** — on timeout/partial, return the rows actually fetched (`execute_query` output) with a "summarization timed out, showing raw results" note. Surface a clear error in `chat.tsx` instead of a silent empty bubble.
4. **Streaming/feedback (optional)** — emit progress so the UI shows it's working.

- [x] **S15.askdata.1 — Make Ask Data return within budget (no more timeouts)** ✅ DONE
  - Files: `mcp/ask_data.py`, `web/main.py`, `web/src/routes/chat.tsx`, `.env.example`, `compose.yaml`.
  - Done: `run_ask_data` now has an explicit overall deadline (`ASK_DATA_DEADLINE_SECONDS`), defaults `ASK_DATA_MAX_DOCS` to 4, batches per-doc notes by default (`ASK_DATA_BATCH_NOTES=true`), and returns raw-result fallback evidence if late-stage summarization times out/fails. `/api/ask_data` now calls the MCP tool directly and returns chat-shaped markdown, avoiding the extra agent final-summary LLM hop; chat UI renders explicit error/empty details. Root cause: slow upstream + serial LLM hops + extra web→agent summary exceeded request budget; compose previously defaulted to 10 docs while `.env.example` said 4. Verified with py_compile, web build, `scripts/smoke_ask_data.sh`.

---

## Stage 18 — Architecture diagram v2: AWS topology + enterprise data-flow overlay

**Goal:** Replace/extend the current connector-centric `/architecture` graph with a modern, classic AWS/network-topology diagram that is useful for both technical and non-technical audiences. It should show **where systems live** (on-prem, AWS, Azure, GCP, Atlassian/SaaS, data/observability, artifact generation) and optionally overlay the main **risk-to-artifact data flow**:

`RISK / SNOW → Atlassian → implementation → data storage + observability → artifact generation`

The diagram must accommodate detailed infrastructure metadata later (VPCs, accounts, regions, CIDRs, IPs/hostnames, EC2 instance types/sizing, MongoDB fork/data-warehouse topology, webhook/API endpoints), but it should be immediately useful with mock/placeholder data. The default view should be readable by non-technical stakeholders; a details mode should expose engineering metadata for team learning and documentation.

### 18a. Information architecture

Represent the estate as layered containers rather than a flat node graph:

1. **Source environments** — on-prem, AWS, Azure, GCP, SaaS sources; all produce logs/events/findings.
2. **Risk / ITSM intake** — Archer/RISK and ServiceNow/SNOW as finding/incident/change sources.
3. **Atlassian work management** — Jira epics/issues and Confluence docs/epic logs.
4. **Implementation** — GitHub repos/PRs/actions, deployment path, agentic workflow workers.
5. **Data storage + observability** — EC2-hosted MongoDB NoSQL fork/data warehouse as the central evidence/log store; optional Snowflake/other analytical stores; log pipelines from every environment.
6. **Artifact generation** — PDF/PPT reports, audit packets, Confluence/public docs, Jira status updates.

Use environment boundaries that can later map to real accounts/VPCs/subnets:

- AWS: accounts, regions, VPCs, subnets/security groups, EC2 compute, MongoDB warehouse.
- On-prem: network zones, log shippers, private services.
- Azure/GCP: projects/subscriptions, services, log exporters.
- SaaS: Atlassian, ServiceNow, Archer/RISK, GitHub, Snowflake.

### 18b. Data-flow overlay

Add a toggleable overlay that draws the canonical end-to-end flow with numbered steps and directional edges:

1. Findings/incidents/changes originate in RISK/Archer and SNOW/ServiceNow.
2. Findings become Jira epics/issues and Confluence epic logs via REST APIs/webhooks.
3. Implementation work happens in GitHub/CI/CD and agentic workflows coordinate planned actions.
4. Runtime logs, evidence, tickets, docs, PR records, and connector snapshots land in the EC2-hosted MongoDB warehouse; logs from on-prem/AWS/Azure/GCP also land there.
5. Observability/analytics read from the warehouse and related stores.
6. Artifact generation emits PDFs/PPTs/audit packets and updates docs/tickets.

Overlay requirements:

- Toggle **Topology** vs **Data flow** vs **Both**.
- Edges carry a `protocol`/`transport` label (`webhook`, `REST`, `log shipper`, `MCP tool`, `agent workflow`, `SQL/export`, etc.).
- Edges distinguish current integrations (webhooks/REST/log shipping) from planned agentic workflows.
- Highlight weak spots from Stage 11/12 concerns without obscuring the high-level flow.

### 18c. Data model and backend shape

Keep Stage 12 `topology_graph` compatible or add a v2 tool (`architecture_graph`) if the old graph would become too overloaded.

Proposed JSON shape:

```json
{
  "layers": [{"id":"aws-prod","label":"AWS prod","kind":"aws_account","parent_id":null,"meta":{}}],
  "nodes": [{"id":"ec2-mongo-wh","label":"MongoDB Warehouse","kind":"ec2_mongodb","layer_id":"aws-prod", "meta":{}}],
  "edges": [{"from":"servicenow","to":"jira","label":"finding → ticket","protocol":"REST/webhook","flow":"risk_to_artifact","planned":false}],
  "flows": [{"id":"risk_to_artifact","label":"Risk to artifact","steps":["archer","servicenow","jira","github","ec2-mongo-wh","reports"]}],
  "concerns": []
}
```

Initial data can be mocked/static in code, but the schema must reserve fields for later technical detail:

- `account_id`, `subscription_id`, `project_id`, `region`, `vpc_id`, `subnet_id`, `cidr`, `security_groups`, `hostname`, `private_ip`, `public_url`, `instance_type`, `storage_gb`, `retention_days`, `owner`, `data_classification`, `criticality`, `runbook_slug`.
- `integration`: `direction`, `protocol`, `auth_mode`, `endpoint_ref`, `frequency`, `sla`, `agentic_status` (`current` | `planned` | `experimental`).

### 18d. Frontend design direction

Build a new architecture experience on `/architecture` (or `/architecture?view=v2`) using React Flow, but make it look closer to an AWS/network diagram than a generic node graph:

- Group boxes for environments/accounts/VPCs/subnets with subtle branded headers.
- AWS-style icons where possible via the existing icon set or lightweight inline SVGs; avoid large icon packages unless justified.
- Distinct visual lanes for: Sources → Risk/ITSM → Atlassian → Implementation → Warehouse/Observability → Artifacts.
- A legend explaining icons, protocols, line styles, and current vs planned/agentic integrations.
- Stakeholder mode: simplified labels and plain-English descriptions.
- Engineer mode: details drawer with endpoints, network/account metadata, owners, sizing, runbook/doc links, and raw JSON.
- Search/filter by environment, service, owner, data classification, and integration protocol.
- Export/download path: at minimum PNG/SVG from the canvas or a copyable Mermaid/PlantUML representation; later tie to Stage 14 docs.

### 18e. Documentation and data capture

Because exact infrastructure details will arrive later, provide a durable capture path:

- `docs/architecture-inventory-template.md` or a wiki doc template listing every field needed from platform/network teams.
- Seed placeholders for unknown VPC/account/IP/sizing values as `TBD`, never fake exact technical identifiers.
- Add a "Known unknowns" panel in the UI so non-technical users can see which details are still pending.
- Link nodes to docs/runbooks when a `runbook_slug` exists.

### 18f. Verification intent

1. `/architecture` loads with a modern topology layout and no console/runtime errors.
2. The default non-technical view clearly communicates the high-level system shape in under 30 seconds.
3. Data-flow overlay shows the full RISK/SNOW → Atlassian → implementation → warehouse/observability → artifact path with numbered steps.
4. Engineer details expose placeholder-ready technical fields without requiring real IPs/accounts yet.
5. Existing Stage 12 topology concerns still appear or have an equivalent concerns panel.
6. Build stays clean: `cd web && npm run build`; backend compiles if a new MCP tool is added.

### Task checklist — Stage 18

- [x] **S18.discovery.1 — Inventory exact questions for later technical fill-in** ✅ DONE
  - Files: `docs/architecture-inventory-template.md` (new), `IMPLEMENT.md`.
  - Done: template captures environments/accounts (kind, account/subscription/project id, region, owner, classification, criticality), AWS network detail (VPC/subnet/CIDR/security groups/peering), compute & data nodes (hostname/private_ip/instance_type/storage_gb/retention_days/runbook_slug), integrations/edges (protocol/auth_mode/endpoint_ref/frequency/sla/agentic_status), the RISK→artifact flow checklist, and a Known-unknowns table. Field names align with the Stage-18 graph schema's reserved metadata keys; all unknown infra values are `TBD` — no invented IPs/account IDs. Importable into the Stage-14 Docs Wiki via `scripts/import_docs.py`.

- [x] **S18.model.1 — Define architecture graph v2 schema** ✅ DONE — `mcp/architecture.py` (new) `build_architecture()` → `{layers,nodes,edges,flows,concerns}`; nested layers via `parent_id`; reserved infra meta keys; matching TS interfaces appended to `types.ts`; unknown infra = `"TBD"`.
  - Files: `mcp/topology.py` or new `mcp/architecture.py`, `web/src/lib/types.ts`.
  - Done when: typed model supports layers/groups, nodes, edges, flows, concerns, environment/network metadata, integration protocol/auth/frequency, current vs planned/agentic status, and runbook/doc links.
  - Depends on: S18.discovery.1.

- [x] **S18.model.2 — Seed v2 graph with placeholder enterprise topology** ✅ DONE — 7 layers (on-prem/AWS prod+VPC/AWS non-prod/Azure/GCP/SaaS), 18 nodes across all 6 lanes incl. EC2 `ec2_mongodb` warehouse, 22 edges encoding `risk_to_artifact` + log-shipper flows, planned/agentic edges marked. All exact infra `"TBD"`.
  - Files: `mcp/architecture.py` or `mcp/topology.py`.
  - Done when: graph includes on-prem, AWS, Azure, GCP, Atlassian, GitHub, ServiceNow/SNOW, Archer/RISK, Snowflake/analytics, EC2 compute, MongoDB NoSQL fork/data warehouse, observability/log-ingest, and artifact generation nodes; unknown exact infra values are represented as `TBD`.
  - Depends on: S18.model.1.

- [x] **S18.api.1 — Expose architecture graph endpoint/tool** ✅ DONE — new `architecture_graph` MCP tool (def+handler+dispatch in `mcp/server.py`), `/api/architecture` proxy in `web/main.py`, `useArchitecture()` hook in `queries.ts`. Mirrors Stage-12 topology wiring; py_compile + tsc clean.
  - Files: `mcp/server.py`, `web/main.py`, `web/src/lib/queries.ts`.
  - Done when: either `topology_graph` returns v2-compatible data without breaking existing callers, or a new `architecture_graph` MCP tool + `/api/architecture` proxy + `useArchitectureGraph()` hook are added. Errors are surfaced clearly.
  - Depends on: S18.model.2.

- [x] **S18.layout.1 — Build environment-aware React Flow layout** ✅ DONE — six labelled vertical lanes (Sources→Artifacts), deterministic column/row positions, per-node layer badge, `fitView`.
  - Files: `web/src/routes/architecture.tsx` (or split components under `web/src/components/architecture/`).
  - Done when: nodes are arranged into visible environment/lane/group boxes (sources, risk/ITSM, Atlassian, implementation, warehouse/observability, artifacts) with deterministic positions and responsive fit; no overlap at common desktop sizes.
  - Depends on: S18.api.1.

- [x] **S18.visual.1 — Apply modern AWS/network-diagram visual system** ✅ DONE — lucide icons per kind, cloud-kind colour accents (AWS amber/Azure blue/GCP red/on-prem slate/SaaS violet), solid (current) vs dashed-animated (planned/agentic) vs destructive (concern) edges with protocol labels, legend panel.
  - Files: `web/src/routes/architecture.tsx`, optional architecture components/styles.
  - Done when: environment group headers, iconography, edge styles, badges, legend, and color semantics read as a modern AWS/network diagram while staying on the Fleet-Dispatch design tokens; current vs planned/agentic integrations are visually distinct.
  - Depends on: S18.layout.1.

- [x] **S18.flow.1 — Add RISK/SNOW → artifact data-flow overlay** ✅ DONE — Topology/Data flow/Both segmented control; `risk_to_artifact` highlighted with numbered step badges; protocol labels visible at normal zoom.
  - Files: `web/src/routes/architecture.tsx`, graph data model.
  - Done when: user can toggle Topology/Data flow/Both; numbered flow steps and directional edges show RISK/SNOW → Atlassian → implementation → data storage/observability → artifact generation; protocol labels are visible at normal zoom.
  - Depends on: S18.layout.1.

- [x] **S18.details.1 — Add stakeholder/engineer modes and details drawer** ✅ DONE — Stakeholder/Engineer toggle; click-to-open drawer exposing meta + edge integration fields + raw JSON in engineer mode; `"TBD"` rendered as muted "pending" pills; runbook link to `/docs/<runbook_slug>` when set.
  - Files: `web/src/routes/architecture.tsx` or components.
  - Done when: stakeholder mode hides noisy metadata and uses plain-English descriptions; engineer mode exposes account/VPC/IP/hostname/sizing/owner/classification/runbook/raw JSON fields in a drawer; `TBD` values are clearly marked as unknown.
  - Depends on: S18.visual.1.

- [x] **S18.filter.1 — Add search, filters, and known-unknowns panel** ✅ DONE — free-text search + filters by environment/kind/owner/classification/agentic_status (dims non-matching); Known-unknowns panel listing all `"TBD"` meta fields grouped by node with count badge; concerns list with focus-on-click retained.
  - Files: `web/src/routes/architecture.tsx` or components.
  - Done when: users can filter by environment, service kind, owner, classification, protocol, and current/planned/agentic status; a panel lists missing technical details grouped by owner/environment.
  - Depends on: S18.details.1.

- [ ] **S18.export.1 — Add share/export artifact path**
  - Files: `web/src/routes/architecture.tsx`, optional utility module.
  - Done when: user can export the current view as SVG/PNG or copy a Mermaid/PlantUML text representation; exported artifact includes title, timestamp, mode, and legend.
  - Depends on: S18.flow.1.

- [ ] **S18.docs.1 — Link diagram to Stage-14 Docs Wiki**
  - Files: `web/src/routes/architecture.tsx`, `docs/architecture-inventory-template.md`, optional `scripts/import_docs.py` runbook note.
  - Done when: architecture page links to relevant wiki docs/runbooks when `runbook_slug` is present and the inventory template is importable into the Docs Wiki.
  - Depends on: S18.details.1.

- [ ] **S18.verify.1 — Verify build and high-level readability**
  - Files: `scripts/smoke_web_spa.sh` (optional update), `IMPLEMENT.md`.
  - Done when: `cd web && npm run build` passes; backend py_compile passes if backend touched; `/architecture` renders; at least one screenshot/manual note confirms the overlay is understandable by non-technical readers and details mode is useful for engineers.
  - Depends on: S18.flow.1, S18.details.1.

---

## Stage 19 — Web authentication, LDAP-backed RBAC, and auth-specialist workflow

**Goal:** Add an application auth/RBAC layer for the web UI and web `/api/*` proxies that starts POC-friendly but is shaped for the future internal LDAP/SSO scheme. **Production uses SSO** in front of the app; for now, the POC can use Basic Auth logins backed by seeded fake users. Usernames are assumed to be email-style identities in the form `firstname.lastname@lanGarland.com`. A user's network access can still be treated as proof they are in the broad **`sg_all_users`** group when `trusted_network` mode is enabled. The code should model group membership explicitly so the placeholder names can later be swapped for real LDAP groups and lookup code.

Initial placeholder groups:

| LDAP group | Role in app | Intended users | Access shape |
| --- | --- | --- | --- |
| `sg_all_users` | `viewer` / base authenticated user | Anyone allowed to reach the app network | Read-only landing pages, architecture/docs read, health/status. For POC this can be assumed from network access. |
| `sg_sec_admin` | `admin` | Security/admin operators; primary audience for this app | Full admin access: workflow orchestration, connector management, Jira apply gates, docs sync, auth diagnostics, all artifacts. |
| `sg_app_user` | `app_user` | Application/database owners onboarding their systems | Onboarding flows, architecture inventory updates for owned apps/databases, docs/runbook authoring, limited artifact viewing. |
| `sg_audit_users` | `audit_user` | Audit team members | Pull artifacts, run reports, update Archer findings, dynamically read context from Jira/Confluence/GitHub/SNOW/Snowflake/Mongo; no infrastructure/admin changes by default. |

### 19a. Security model and assumptions

- **Production mode:** `AUTH_MODE=sso` trusts a production SSO / reverse-proxy integration to authenticate the user and forward an identity + group claims. The app still performs authorization locally from group→role→capability mappings.
- **POC mode:** `AUTH_MODE=basic` provides a small Basic Auth login surface backed by seeded fake users. Optional `trusted_network` mode remains available when network access alone should imply `sg_all_users`.
- **Seeded identities:** fake users use Faker-style names and the canonical login format `firstname.lastname@lanGarland.com`. Each placeholder LDAP group/role must have at least one seeded user, plus at least one multi-role user for testing precedence.
- **Future mode:** `AUTH_MODE=ldap` delegates identity/group lookup to an internal LDAP adapter; placeholder group names are config values, not hardcoded policy literals. SSO can later feed the same adapter or pass signed group claims.
- **Defense-in-depth:** the web service enforces route/API permissions even if the React UI hides nav items. MCP write tools and connector mutations keep their existing gates (`WORKFLOW_WRITES_ENABLED`, `JIRA_WRITES_ENABLED`, `DOCS_SYNC_ENABLED`, etc.).
- **Least privilege:** roles should unlock explicit capabilities (`canRunWorkflow`, `canApplyJira`, `canUpdateArcher`, `canManageDocs`, `canEditArchitectureInventory`, `canAdminAuth`) rather than broad route checks only.
- **Auditability:** every privileged action should carry `actor`, `roles`, and `groups` into audit logs where practical.

### 19b. RBAC capability matrix

Initial capabilities (adjust as routes evolve):

| Capability | `viewer` (`sg_all_users`) | `app_user` (`sg_app_user`) | `audit_user` (`sg_audit_users`) | `admin` (`sg_sec_admin`) |
| --- | --- | --- | --- | --- |
| View overview/architecture/docs | yes | yes | yes | yes |
| Chat/read-only Ask Data | optional read-only | yes for owned app data | yes | yes |
| Edit sheet/data records | no | owned onboarding records only | no, unless artifact metadata | yes |
| Wrangler/read analytics | no or read-only | owned datasets | yes | yes |
| Workflow orchestration | no | request/preview only | report/audit workflows | yes |
| Jira staged apply | no | no | validate/comment only | yes |
| Archer finding update | no | no | yes | yes |
| Docs author/edit | read-only | own app docs/runbooks | audit artifacts/docs | yes |
| Docs Confluence sync | no | no | request only | yes |
| Architecture inventory edit | no | own app/db entries | audit annotations | yes |
| Auth/admin diagnostics | no | no | no | yes |

### 19c. Backend architecture

Add a small auth module to the web service first, because the browser only talks to `web/main.py` for app APIs:

- `web/auth.py` (new): `UserContext`, `Role`, `Capability`, group→role mapping, `get_current_user(request)`, `require_capability(...)` dependencies/decorators.
- `AUTH_MODE=sso|basic|trusted_network|headers|ldap|disabled`:
  - `sso`: production path; derive user from trusted SSO/proxy headers (`X-Forwarded-User`, group header, or future signed claims). Never accept spoofable dev headers in this mode.
  - `basic`: POC path; HTTP Basic Auth against seeded fake users, with password hashes or generated dev-only passwords stored outside committed secrets. Seeded users all use `firstname.lastname@lanGarland.com` usernames.
  - `trusted_network`: derive user from `X-Forwarded-User`/`REMOTE_USER` if present, otherwise `anonymous-network-user`; groups default to configured all-users group.
  - `headers`: dev/test mode; `X-SG-User` and `X-SG-Groups` simulate identity and groups. Must be disabled by default in production docs.
  - `ldap`: future adapter path; calls `auth_ldap_lookup` integration or internal LDAP client.
  - `disabled`: local-only escape hatch for development.
- `GET /api/me`: returns `{user, groups, roles, capabilities, auth_mode}` for the topbar/sidebar and troubleshooting.
- Route guards on web endpoints: reject with `401` if unauthenticated, `403` if authenticated but missing capability.
- Pass actor context to MCP tools where supported, either as explicit tool arguments (`actor`) or as MCP metadata once supported.

### 19d. Frontend behavior

- Add `useMe()` query and `AuthProvider`/capability helpers.
- In Basic Auth mode, browser-native login is acceptable for the POC; a custom login screen is optional unless needed for clearer demos.
- Topbar shows signed-in user, effective roles, and auth mode badge in POC/basic/trusted-network modes.
- Sidebar hides or badges routes the user cannot access; direct navigation still shows a clear `403` page.
- Admin-only affordances (apply, sync, workflow run, live connector writes, auth diagnostics) are disabled with explanatory tooltips for non-admins.
- Add an `/admin/auth` or `/settings/auth` page for admins showing current group mappings, simulated user in POC/header mode, recent auth decisions, and LDAP integration status.

### 19e. Seeded fake users for POC

Create deterministic Faker-style seed users that represent every group and role. Store them in a small seed file/collection or auth fixture, not in code paths that will conflict with future LDAP.

Example seed set (names are placeholders and can change):

| User | Email/login | Groups | Role coverage |
| --- | --- | --- | --- |
| Avery Stone | `avery.stone@lanGarland.com` | `sg_all_users` | base viewer |
| Simone Patel | `simone.patel@lanGarland.com` | `sg_all_users`, `sg_sec_admin` | admin |
| Marcus Chen | `marcus.chen@lanGarland.com` | `sg_all_users`, `sg_app_user` | application/database owner |
| Elena Brooks | `elena.brooks@lanGarland.com` | `sg_all_users`, `sg_audit_users` | audit user |
| Priya Morgan | `priya.morgan@lanGarland.com` | `sg_all_users`, `sg_app_user`, `sg_audit_users` | multi-role non-admin |
| Jordan Reyes | `jordan.reyes@lanGarland.com` | `sg_all_users`, `sg_sec_admin`, `sg_audit_users` | admin + audit |

Seed requirements:

- Passwords are POC-only and must be generated/configured safely (`AUTH_BASIC_SEED_PASSWORD` for local demos or per-user hashes in a gitignored file). Do not commit real passwords.
- Seed data should include display name, email, groups, disabled flag, created_at, and notes.
- The auth diagnostics page should make it easy to switch/test these fake identities in `headers` mode and to document which role each represents.

### 19f. LDAP lookup and auth-specialist agent/MCP direction

The real internal lookup code should be isolated behind a narrow interface so it can later become either a reusable skill, an MCP integration, or a locked-down auth-specific agent:

- **MCP integration option:** `auth_lookup_user`, `auth_lookup_groups`, `auth_check_membership`, `auth_explain_access` tools backed by internal LDAP. Only the web service / auth-agent should call them; ordinary chat agents should not get broad access to identity data.
- **Auth-specialist agent option:** an agent with only auth lookup/explanation tools, no data write tools, no broad connector access. Its job: answer "why can/can't this user access X?", help onboard group mappings, and produce audit explanations.
- **Skill option:** create a project skill once the internal LDAP scheme and lookup code are known, documenting exact group names, lookup APIs, failure modes, test fixtures, and safe redaction rules.
- **Privacy:** never expose full LDAP directory dumps to the model. Return minimal attributes: username, display name, email if needed, group DNs/names, lookup timestamp, source, and errors.

### 19g. Env surface (proposed)

| Var | Default | Required | Stage | Notes |
| --- | --- | --- | --- | --- |
| `AUTH_MODE` | `basic` | no | 19 | `sso`, `basic`, `trusted_network`, `headers`, `ldap`, or `disabled` |
| `AUTH_ALL_USERS_GROUP` | `sg_all_users` | no | 19 | Base authenticated/network group |
| `AUTH_ADMIN_GROUP` | `sg_sec_admin` | no | 19 | Grants `admin` role |
| `AUTH_APP_USER_GROUP` | `sg_app_user` | no | 19 | Grants `app_user` role |
| `AUTH_AUDIT_USER_GROUP` | `sg_audit_users` | no | 19 | Grants `audit_user` role |
| `AUTH_TRUSTED_HEADER_USER` | `X-Forwarded-User` | no | 19 | Header to read user from behind proxy/SSO |
| `AUTH_TRUSTED_HEADER_GROUPS` | `X-Forwarded-Groups` | no | 19 | Optional proxy/SSO group header |
| `AUTH_SSO_REQUIRED` | `false` | no | 19 | Production guardrail; require SSO mode when true |
| `AUTH_BASIC_USERS_FILE` | `/data/auth/users.json` | no | 19 | POC Basic Auth seeded users/hashes file |
| `AUTH_BASIC_SEED_PASSWORD` | — | no | 19 | Dev-only password for generated seed users; prefer gitignored secret |
| `AUTH_DEV_HEADERS_ENABLED` | `false` | no | 19 | Allows `X-SG-User`/`X-SG-Groups` in non-prod testing |
| `AUTH_LDAP_URL` | — | no | 19 | Future LDAP endpoint / adapter URL |
| `AUTH_LDAP_BASE_DN` | — | no | 19 | Future LDAP search base |
| `AUTH_LDAP_BIND_SECRET_FILE` | — | no | 19 | Future mounted secret path, never inline committed |
| `AUTH_CACHE_TTL_SECONDS` | `300` | no | 19 | Cache user/group lookup results |

### 19h. Verification intent

1. In default POC Basic Auth mode, each seeded `firstname.lastname@lanGarland.com` fake user can log in and `/api/me` shows the expected groups/roles/capabilities.
2. In production-like SSO mode, trusted SSO headers resolve identity/groups and dev spoof headers are ignored.
3. Trusted-network mode still works as a POC fallback and shows the user as authenticated with `sg_all_users`/`viewer`.
4. Header/dev mode can simulate each role and combined roles without code changes.
5. Non-admin users cannot call admin-only APIs even if they use curl directly.
6. UI hides/disables unauthorized actions and direct route access shows a useful `403` page.
7. Audit logs for privileged actions include actor + roles/groups where available.
8. LDAP mode can be stubbed with deterministic fixtures now, then swapped for internal lookup code later.
9. Build/checks pass: `python3 -m py_compile web/*.py`; `cd web && npm run build`.

### Task checklist — Stage 19

- [x] **S19.policy.1 — Finalize placeholder RBAC policy and capability map** ✅ DONE
  - Files: `docs/auth-rbac.md` (new), `IMPLEMENT.md`.
  - Done: `docs/auth-rbac.md` consolidates the group→role mapping (env-configurable placeholder groups), the per-role capability matrix, the explicit `/api/*` capability requirements (read open to `sg_all_users`, mutations gated; 401 vs 403 semantics), the SSO-in-prod / Basic-Auth-for-POC assumptions and all six `AUTH_MODE`s, the seeded POC user set, the LDAP/auth-agent privacy boundary, and an Open-questions list (LDAP DNs, ownership scoping, signed claims, auth-explanation surface, cache TTL) explicitly flagged as non-blocking for POC basic/trusted-network mode. Importable into the Stage-14 Docs Wiki.

- [x] **S19.model.1 — Add web auth model and config** ✅ DONE
  - Files: `web/auth.py` (new), `.env.example`, `compose.yaml`.
  - Done: `UserContext`, roles, capabilities, env-configured group names, Basic Auth config, SSO header config, and group→role derivation implemented with unit-testable pure functions. 6 auth modes: `sso`, `basic`, `trusted_network`, `headers`, `ldap`, `disabled`. Committed `98850b3`.
  - Depends on: S19.policy.1.

- [x] **S19.seed.1 — Seed deterministic Faker-style users per LDAP group/role** ✅ DONE
  - Files: `web/auth_seed.py` (new), `.env.example`, `compose.yaml`.
  - Done: 6 seeded `firstname.lastname@lanGarland.com` users covering all 4 groups (`sg_all_users`, `sg_sec_admin`, `sg_app_user`, `sg_audit_users`) plus multi-role users; passwords are POC-only via `AUTH_BASIC_SEED_PASSWORD`; compose volume mount `./perm/auth:/data/auth`. Committed `98850b3`.
  - **Hotfix 2026-05-22:** `auth_seed.py` was missing from `web/Dockerfile` COPY line, causing `ModuleNotFoundError` at login time. Added `auth_seed.py` to the COPY. Also ran the seed script to generate the missing `perm/auth/users.json` file. Without this, all logins returned HTTP 500.
  - Depends on: S19.model.1.

- [x] **S19.backend.1 — Add request identity resolution modes** ✅ DONE
  - Files: `web/auth.py`, `web/main.py`.
  - Done: `sso`, `basic`, `trusted_network`, `headers`, `disabled`, and stub `ldap` modes resolve a user consistently; Basic Auth validates seeded users; SSO trusts only configured proxy headers; dev headers are ignored unless explicitly enabled; failures produce clear 401/403 responses. Startup guardrail enforces `AUTH_SSO_REQUIRED`. Committed `98850b3`.
  - Depends on: S19.model.1, S19.seed.1.

- [x] **S19.backend.2 — Add `/api/me` and auth diagnostics payload** ✅ DONE
  - Files: `web/main.py`, `web/auth.py`, `web/src/lib/types.ts`, `web/src/lib/queries.ts`.
  - Done: `/api/me` returns user, groups, roles, capabilities, auth mode, and source; React Query hook `useMe()` available; always returns HTTP 200. Committed `98850b3`.
  - Depends on: S19.backend.1.

- [x] **S19.backend.3 — Guard web API endpoints by capability** ✅ DONE
  - Files: `web/main.py`, `docs/auth-rbac.md`.
  - Done: each `/api/*` route has an explicit required capability via `Depends(_guard_user/_guard_cap)`; admin-only mutation endpoints return 403 for non-admin; read-only endpoints remain available to `sg_all_users`. 33 guarded endpoints. Committed `98850b3`.
  - Depends on: S19.backend.2.

- [x] **S19.audit.1 — Propagate actor context into privileged actions** ✅ DONE
  - Files: `web/main.py`, `mcp/server.py`, `mcp/connectors/jira.py`, `mcp/jira_staging.py`, `mcp/sheet_apply.py`, `mcp/wrangler.py`, `mcp/db.py`.
  - Done: `_actor_from_request()` extracts user from `request.state.user` (set by guard dependencies); all 14 write endpoints inject `actor` dict into MCP args; MCP handlers pop `actor` from args and pass to `db._audit()`; audit rows now include `actor` when available. Committed `98850b3`.
  - Depends on: S19.backend.3.

- [x] **S19.frontend.1 — Add auth provider, route guard, and 403 page** ✅ DONE
  - Files: `web/src/App.tsx`, `web/src/components/auth-provider.tsx` (new), `web/src/components/forbidden.tsx` (new).
  - Done: `AuthProvider` wraps the full app tree; `RequireCapability` gates routes; `/forbidden` renders a clear 403 page with current user/roles; `useAuth()` hook exposes `authenticated`, `roles`, `hasCapability()`, `authMode`. Committed `98850b3`.
  - Depends on: S19.backend.2.

- [x] **S19.frontend.2 — Gate sidebar and privileged UI actions** ✅ DONE
  - Files: `web/src/components/app-sidebar.tsx`, `web/src/components/topbar.tsx`, `web/src/components/jira-editable-grid.tsx`, `web/src/routes/workflow.tsx`.
  - Done: sidebar items show lock icon + tooltip when cap is missing; topbar shows display name, roles, auth mode badge; jira grid uses `DisabledWithTooltip` for Save/Validate/Revert/Apply; workflow uses `DisabledWithTooltip` for Spawn/Approve/Reject. Committed `98850b3`.
  - Depends on: S19.frontend.1.

- [ ] **S19.admin.1 — Add auth diagnostics/admin page**
  - Files: `web/src/routes/auth-admin.tsx` (new), `web/src/App.tsx`, `web/src/components/app-sidebar.tsx`, `web/main.py` if additional diagnostics endpoint is needed.
  - Done when: `sg_sec_admin` users can view group mappings, current mode, cache status, simulated identity hints in POC mode, recent deny reasons, and LDAP adapter status; non-admins get 403.
  - Depends on: S19.frontend.2.
  - **Not yet implemented.** This is the only remaining S19 UI task.

- [x] **S19.ldap.1 — Define LDAP adapter interface and fixture implementation** ✅ DONE
  - Files: `web/auth_ldap.py` (new), `docs/auth-rbac.md`.
  - Done: `DirectoryAdapter` ABC with `lookup_user`, `lookup_groups`, `check_membership`; `FixtureAdapter` provides deterministic lookups for all 4 placeholder groups; real internal code can be swapped in without changing route guards. Committed `98850b3`.
  - Depends on: S19.backend.1.

- [x] **S19.agent.1 — Decide skill vs MCP integration vs auth-specialist agent**
  - Files: `IMPLEMENT.md`, `docs/auth-rbac.md`, optional project skill after decision.
  - Done when: decision is recorded: (a) create an auth MCP integration, (b) create a locked-down auth-specialist agent, (c) create a project skill for internal LDAP workflow, or (d) staged combination. Include rationale and privacy boundaries.
  - Depends on: S19.ldap.1.
  - Done: staged combination chosen — ship `web/auth_explain.py` as a self-contained pure module now; wrap as MCP tool (behind `canAdminAuth`) or auth-specialist agent later. Decision + privacy boundaries recorded in `docs/auth-rbac.md` §Decision (S19.agent.1).

- [x] **S19.agent.2 — Implement minimal auth explanation surface**
  - Files: chosen in S19.agent.1 (`mcp/auth_directory.py`, auth-agent config, or project skill).
  - Done when: an admin can ask "why does user X have/ lack access to Y?" and receive a minimal, non-sensitive explanation based on group membership and the capability map.
  - Depends on: S19.agent.1.
  - Done: `web/auth_explain.py` — `explain_access(username, capability_or_route) -> dict` with enforced privacy boundary (8 allowed output keys, no passwords/extra attrs). Route→capability map covers all 34 API endpoints. CLI: `python3 web/auth_explain.py <user> <cap_or_route>`. Verified: admin granted, viewer denied with reason, unknown user → clean not-found, no crash. `py_compile` passes.

- [x] **S19.tests.1 — Add auth/RBAC smoke tests** ✅ DONE
  - Files: `scripts/smoke_auth.sh` (new).
  - Done: smoke covers Basic Auth login for every seeded role, default trusted-network viewer fallback, production-like SSO header resolution, dev-header admin/app_user/audit_user simulation, denied admin endpoint as non-admin, and `/api/me` payload shape. Committed `98850b3`.
  - Depends on: S19.backend.3.

- [ ] **S19.verify.1 — Integrated verification**
  - Files: `IMPLEMENT.md`, `progress.md` after implementation.
  - Done when: `python3 -m py_compile web/*.py` and `cd web && npm run build` pass; smoke auth passes; manual UI checks confirm nav/action gating for all four groups; no secrets are committed.
  - Depends on: S19.frontend.2, S19.tests.1.
  - **Nearly complete.** py_compile + npm build are green. smoke_auth.sh exists. Remaining: manual UI gating verification across all 4 groups and S19.admin.1.

---

## Stage 20 — Standup Jira cockpit: explorer-centered teamwork + agentic follow-up capture

**Goal:** Promote the current Jira-focused **Interactive Compliance Proof Explorer** / editable Jira grid into a dedicated **Standup** page. The page is optimized for screen share during standup: the Explorer is the centerpiece, admin-group team members can open the same session, a live websocket chat appears in a compact bubble below/alongside the Explorer, and a scrum-master/product-owner-controlled agent turns noisy meeting chat into structured, dry-run follow-up proposals.

The Jira sprint board is too clunky for this workflow. The Standup view should keep the dynamic Jira Explorer interactions, but make it faster to capture concerns, links, implied follow-ups, missing associations, and new work while the team is talking.

### 20a. Audience, permissions, and workflow

Primary users are **admin group** members (`sg_sec_admin`) from Stage 19. Audit users may observe or contribute if allowed, but approval belongs to a scrum master/product owner capability (initially `admin`, later `canApproveStandupActions`).

Typical workflow:

1. Scrum master opens `/standup` and screen-shares it.
2. Team members open the same standup session and post notes/links/mentions in websocket chat.
3. The Explorer remains the bulk of the window for live Jira triage and bulk edits.
4. The side/bottom "Jira Configuration" / tool-call bubble is minimized by default; it can expand to show connector status, tool calls, and cross-service associations.
5. The standup agent continuously or on-demand summarizes chat into **important takeaways**, **risks/blockers**, **suggested new Jira work**, **meeting follow-ups**, **service associations**, and **Confluence/doc links**.
6. Suggested Jira creations/edits/links are staged as dry-run proposals. Nothing writes to production Jira/Confluence/Archer/etc. without HITL approval by the scrum master/product owner.
7. Approved actions flow through existing Stage-16 Jira staging/validation/apply gates; live writes still respect `JIRA_WRITES_ENABLED` and connector write gates.

### 20b. Standup page layout

Build a new route `/standup` (or `/standup/:sessionId`) rather than overloading the Compliance Hub:

- **Main area (70–80% of viewport):** Jira Explorer / editable Jira grid, with sprint/epic filters, staged-edit badges, validation state, bulk edit toolbar, and quick links to related services.
- **Live chat bubble/panel:** websocket chat docked below the Explorer or as a right/bottom bubble. It should support quick note entry, pasted links, mentions, and timestamped participant messages.
- **Agent suggestions panel:** shows extracted takeaways, candidate work items, proposed ticket edits/creates, links to Confluence docs, risk/SNOW/Archer references, and confidence/rationale.
- **Compact Jira Configuration bubble:** collapsed by default; expands for connector health, tool-call trace, dry-run plans, and cross-service association details.
- **Approval tray:** scrum master/product owner sees staged proposals with Approve/Reject/Edit/Request more context actions.

### 20c. Websocket collaboration model

Use FastAPI websockets in `web/main.py` first (browser already connects to web). Persist messages and proposals so refreshes do not lose meeting context.

Conceptual objects:

- `standup_sessions`: `{session_id, title, sprint, epic_keys[], status, created_by, started_at, ended_at}`
- `standup_messages`: `{id, session_id, author, body, kind, links[], mentions[], created_at}`
- `standup_agent_runs`: `{id, session_id, trigger, summary, proposals[], created_by, created_at}`
- `standup_proposals`: `{id, session_id, type, target_service, dry_run_payload, status, rationale, source_message_ids[], approval}`

Websocket events:

- client → server: `join`, `chat.message`, `typing`, `agent.summarize`, `proposal.approve`, `proposal.reject`, `proposal.edit`, `explorer.selection`.
- server → clients: `session.snapshot`, `chat.message`, `presence.update`, `agent.running`, `agent.summary`, `proposal.created`, `proposal.updated`, `jira.stage.updated`, `error`.

### 20d. Standup agent capabilities

The agent available from websocket chat should be narrow but context-rich:

- Inputs: live standup chat, selected Jira rows/epic context, docs/wiki search results, workflow/epic templates, Jira story templates, Confluence links, connector summaries, and optionally Archer/SNOW/Snowflake/GitHub context.
- Outputs:
  - standup summary and decisions
  - likely follow-ups and meeting requests
  - candidate Jira stories/tasks/bugs with summary, description, acceptance criteria, labels, epic link, related services, priority, story points, due-date hints
  - candidate bulk edits to existing Jira issues
  - cross-service associations (Jira ↔ Confluence ↔ GitHub ↔ SNOW/Archer/Snowflake/Mongo evidence)
  - rationale + source chat messages/links for every suggestion
- Constraints:
  - proposals are dry-run by default
  - all production mutations require HITL approval
  - approval actor must be recorded
  - agent should gracefully handle vague chat like "follow up on the RDS thing" by linking to the current Explorer selection and recent pasted links when possible

### 20e. Backend and integration shape

Reuse existing Stage-16 Jira staging APIs wherever possible rather than inventing a second write path:

- New MCP/agent module: `mcp/standup_agent.py` or workflow under `mcp/workflow/standup.py` to turn chat/session context into structured proposals.
- New MCP tools if useful: `standup_summarize`, `standup_plan_jira_work`, `standup_link_context`, `standup_stage_proposals`.
- Web proxies/websocket handlers in `web/main.py` call MCP tools and existing Jira tools (`jira_stage_edits`, `jira_validate_staged`, `jira_apply_staged`) for staged edits.
- Use Stage-14 docs tools (`docs_search`, `docs_get`) for runbooks/templates and Confluence links.
- Use Stage-9 connectors for cross-service context; keep live writes gated.
- Persist standup sessions/messages/proposals in Mongo (new seed/helpers in `mcp/db.py` or a web-owned collection helper) so reloads and screenshots retain context.

### 20f. HITL and production-safety rules

- Every proposed new Jira ticket, bulk edit, link operation, Archer update, Confluence update, or meeting/task artifact starts as `dry_run` / `proposed`.
- Scrum master/product owner approval is required before any external write. For now, require `sg_sec_admin`; after Stage 19 capability map lands, require `canApproveStandupActions`.
- Approvals record actor, timestamp, original proposal, edited payload, validation result, and final apply result.
- Live Jira writes still require `JIRA_WRITES_ENABLED=true`; otherwise Apply returns a dry-run plan.
- If the websocket agent suggests service associations, show them as links/proposals first; do not silently mutate remote services.

### 20g. Env surface (proposed)

| Var | Default | Required | Stage | Notes |
| --- | --- | --- | --- | --- |
| `STANDUP_WS_ENABLED` | `true` | no | 20 | Enable websocket endpoint for live standup sessions |
| `STANDUP_SESSION_TTL_HOURS` | `24` | no | 20 | How long inactive sessions remain active before archival |
| `STANDUP_MAX_MESSAGES` | `500` | no | 20 | Per-session message cap before archival/summarization |
| `STANDUP_AGENT_ENABLED` | `true` | no | 20 | Enables agent summarization/proposal generation |
| `STANDUP_AGENT_INTERVAL_SECONDS` | `0` | no | 20 | `0` means on-demand only; positive enables periodic suggestions |
| `STANDUP_REQUIRE_ADMIN` | `true` | no | 20 | Require admin/approval capability for session control and approvals |
| `STANDUP_DRY_RUN_ONLY` | `true` | no | 20 | Extra guardrail: never apply live writes even if connector writes are enabled |

### 20h. Verification intent

1. `/standup` renders with the Jira Explorer as the dominant element and the configuration/tool-call panel collapsed by default.
2. Two browser sessions can join the same standup session and exchange websocket chat messages live.
3. Pasted Jira/Confluence/GitHub/SNOW/Archer links are parsed into message metadata and shown as candidate associations.
4. Agent summarization produces takeaways and candidate Jira work from chat + selected Explorer context.
5. Candidate Jira ticket creations/edits are staged as dry-run proposals with source-message references and rationale.
6. Non-approvers cannot approve/apply proposals; scrum master/product owner/admin can approve, and approval is audited.
7. Existing Stage-16 Jira validation/apply gates are reused; live production writes remain gated by `JIRA_WRITES_ENABLED` and `STANDUP_DRY_RUN_ONLY`.
8. Build/checks pass: `python3 -m py_compile web/*.py mcp/*.py`; `cd web && npm run build`; websocket smoke passes.

### Task checklist — Stage 20

- [x] **S20.policy.1 — Define standup permissions and approval rules** ✅ DONE
  - Files: `docs/standup.md`.
  - Done: documented session owner/scrum-master/product-owner, participant, observer, admin fallback, dry-run-only safety policy, and the `STANDUP_DRY_RUN_ONLY` / `JIRA_WRITES_ENABLED` interaction. Current `/standup` disables Jira apply until approval/RBAC lands.

- [x] **S20.model.1 — Add standup session/message/proposal data model** ✅ DONE (web-owned JSON store)
  - Files: `web/standup_store.py`.
  - Done: sessions, messages, agent runs, and proposals have stable IDs, timestamps, actor fields, status fields, source-message references, dry-run payloads, and approval metadata. Store path is `STANDUP_STORE_PATH`, `/data/auth/standup_sessions.json` when mounted, or `/tmp/sglandsimple_standup_sessions.json` for local dev.
  - Depends on: S20.policy.1.

- [x] **S20.ws.1 — Add websocket endpoint and session fanout** ✅ DONE
  - Files: `web/standup_ws.py`, `web/main.py`, `scripts/smoke_standup_ws.py`.
  - Done: multiple clients can join a session, send `chat.message`, receive live fanout, get `session.snapshot` on connect, and reconnect without losing persisted JSON-store messages. Websocket smoke script added; full live run requires rebuilt web container.
  - Depends on: S20.model.1.

- [x] **S20.ui.1 — Create `/standup` route shell** ✅ DONE
  - Files: `web/src/routes/standup.tsx`, `web/src/App.tsx`, `web/src/components/app-sidebar.tsx`.
  - Done: `/standup` appears in navigation and lays out Explorer-dominant main area, live/fallback chat panel, agent suggestion previews, safety messaging, and collapsed Jira Configuration/tool-trace bubble.
  - Depends on: S20.policy.1.

- [x] **S20.explorer.1 — Extract/reuse Jira Explorer as standalone centerpiece** ✅ DONE
  - Files: `web/src/components/jira-editable-grid.tsx`, `web/src/routes/standup.tsx`.
  - Done: Standup renders the current Jira editable grid independently of Compliance Hub with the existing bulk edit toolbar, staged badges, and validation status. Added `allowApply` so Standup can disable Apply until approval/RBAC exists while Hub behavior remains unchanged.
  - Depends on: S20.ui.1.

- [x] **S20.chat.1 — Build live standup chat UI** ✅ DONE
  - Files: `web/src/components/standup-chat.tsx`, `web/src/routes/standup.tsx`.
  - Done: chat supports live websocket messages, presence, timestamps, author badges, paste/link display, mention/Jira-key highlighting, reconnect state, and local fallback alongside the Explorer.
  - Depends on: S20.ws.1, S20.ui.1.

- [x] **S20.links.1 — Parse links/mentions into service associations** ✅ DONE
  - Files: `mcp/standup_agent.py`, `web/standup_store.py`, `web/src/components/standup-chat.tsx`.
  - Done: Jira keys/URLs, Confluence URLs, GitHub URLs, ServiceNow/SNOW records, Archer references, Snowflake/Mongo references, generic URLs, and `@mentions` are extracted from chat and attached to messages/proposals; frontend displays association tokens.
  - Depends on: S20.chat.1.

- [x] **S20.agent.1 — Implement standup summarization/proposal agent** ✅ DONE (dry-run helper)
  - Files: `mcp/standup_agent.py`, `mcp/server.py`.
  - Done: MCP tools `standup_link_context` and `standup_summarize` summarize chat + selected Jira context into takeaways, blockers, follow-ups, Jira proposals, bulk-edit proposals, and cross-service associations with rationale/source IDs. Outputs are normalized to `status="proposed"` and `dry_run=true`; no external writes or Jira staging occur.
  - Depends on: S20.model.1, S20.links.1.

- [ ] **S20.agent.2 — Give agent docs/workflow/template context**
  - Files: `mcp/standup_agent.py`, Stage-14 docs tools/templates, `docs/standup.md`.
  - Done when: generated Jira work uses story templates, acceptance-criteria format, labels/tags, priority/story-point estimates, epic/workflow docs, and direct Confluence links when relevant.
  - Depends on: S20.agent.1.

- [ ] **S20.proposals.1 — Stage Jira creates/edits as dry-run proposals**
  - Files: `mcp/standup_agent.py`, `mcp/server.py`, `web/main.py`, existing Jira staging tools.
  - Done when: proposed new Jira tickets and bulk edits become `standup_proposals` and/or Stage-16 `jira_staged_changes` without live writes; each has validation state, dry-run payload, source messages, and rationale.
  - Depends on: S20.agent.1.

- [ ] **S20.approval.1 — Add scrum-master/product-owner HITL approval tray**
  - Files: `web/src/routes/standup.tsx`, `web/main.py`, auth helpers once Stage 19 exists.
  - Done when: approvers can edit/approve/reject proposals; non-approvers are read-only; approvals call validate/apply dry-run path, record actor/timestamp, and broadcast updates over websocket.
  - Depends on: S20.proposals.1.

- [ ] **S20.trace.1 — Add expandable tool-call/configuration bubble**
  - Files: `web/src/routes/standup.tsx`, existing connector/config components.
  - Done when: Jira Configuration is minimized by default but can expand to show connector health, dry-run/live-write gates, tool calls, proposal generation traces, and cross-service association details.
  - Depends on: S20.ui.1, S20.agent.1.

- [ ] **S20.auth.1 — Apply Stage-19 RBAC to standup route/actions**
  - Files: `web/main.py`, `web/src/routes/standup.tsx`, auth docs.
  - Done when: only authorized users can join sessions; only approvers/admins can approve proposals; audit users can observe/contribute according to policy; all denials are clear.
  - Depends on: S20.policy.1; integrate fully after Stage 19 backend exists.

- [ ] **S20.verify.1 — Websocket + agent + dry-run smoke**
  - Files: `scripts/smoke_standup_ws.sh` or `.py`, `scripts/smoke_jira_edit.sh`, `IMPLEMENT.md`.
  - Done when: smoke starts/joins a session, sends messages from two users, triggers agent summary, stages a dry-run Jira proposal, validates approval gating, and confirms no live external write occurs.
  - Depends on: S20.ws.1, S20.agent.1, S20.proposals.1.

- [ ] **S20.verify.2 — UI build and standup screen-share review**
  - Files: `web/src/routes/standup.tsx`, `IMPLEMENT.md`.
  - Done when: `cd web && npm run build` passes; manual screen-share review confirms Explorer dominates the view, chat captures noisy context quickly, suggestions are understandable, and configuration/tool traces do not distract.
  - Depends on: S20.explorer.1, S20.chat.1, S20.approval.1.

---

## Stage 21 — Deep Agent platform: containerized LangGraph agents + HITL deployment runtime

**Goal:** Evolve the current Stage-4 `deep_agent` planner/builder proof into a production-shaped **Deep Agent platform** for this project: containerized LangGraph agents, service-specific tool scopes, durable checkpointing, HITL approval gates, and deployment targets that can run on AWS Bedrock-backed models, Kubernetes, Fargate/ECS, or plain containers. This stage should turn the user's coding-agent orchestration paradigm (subagents, skills, MCPs, commands, workflows) into an enterprise runtime that can safely execute the previous HITL work in this plan.

This is not just "one big agent." The baseline should ship a small set of service-specific agents with strict tool scopes and a supervising orchestrator. The future direction should support more specialized on-rails workflows that are secure, context-efficient, and workflow-guided.

### 21a. Relationship to existing Stage 4

Stage 4 already provides a useful primitive:

- `plan_task`, `run_plan`, `deep_agent` MCP tools.
- Planner/builder role split.
- LangGraph state machine execution.
- Mongo persistence of plans/runs.
- Sandbox tools for filesystem/shell work.

Stage 21 builds on that by adding:

- named agent definitions and service-specific profiles
- per-agent tool allowlists and context packs
- HITL interrupt/resume patterns as first-class features
- deployment packaging and runtime configuration
- observability, audit, and security boundaries
- a migration path to Bedrock/K8S/Fargate/container deployments

### 21b. Basic implementation: service-specific deep agents

Start with a pragmatic set of agents aligned to existing services and stages:

| Agent | Primary scope | Allowed tools/context | Typical tasks |
| --- | --- | --- | --- |
| `jira_agent` | Jira issue triage and staged edits | Jira staging tools, Jira templates, selected docs/workflows | Create dry-run stories, bulk edit proposals, sprint/standup follow-ups, validate staged changes. |
| `docs_agent` | Docs Wiki + Confluence lifecycle | `docs_*`, `docs_sync`, Confluence read/write only when gated | Draft doc revisions, reconcile public docs, suggest stale-doc updates. |
| `architecture_agent` | Architecture inventory/diagram context | architecture graph, docs/runbooks, connector summaries | Fill TBD metadata, explain topology, propose diagram updates. |
| `audit_agent` | Evidence/artifact generation | report tools, Archer/RISK/SNOW/Snowflake/Mongo read surfaces, docs search | Pull evidence, draft audit packets, propose Archer updates. |
| `workflow_agent` | Compliance workflow orchestration | Stage-9 workflow tools, connector registry, HIL gates | Run/check workflows, collect approval questions, summarize outcomes. |
| `auth_agent` | Auth/RBAC explanation | auth lookup/explain tools only | Explain access, validate group mapping, support onboarding of auth policy. |
| `standup_agent` | Standup follow-up capture | standup session data, Jira/docs templates, selected explorer context | Summarize chat, generate dry-run Jira proposals, link cross-service context. |

Baseline behavior:

- One orchestrator chooses which service-specific agent(s) to invoke based on task intent and current UI/workflow context.
- Each agent has a strict tool allowlist, max runtime, max steps, and model budget.
- All writes are proposed/dry-run unless an explicit HITL approval node resumes execution.
- Agent outputs use typed Pydantic schemas (proposal, plan, action, evidence, approval_request) rather than free-form text only.
- Agent traces, tool calls, approvals, and final artifacts are persisted to Mongo.

### 21c. Advanced/future direction: on-rails workflow-guided agents

After the basic multi-agent platform works, evolve toward more constrained workflows:

- **Workflow-specific graphs:** one LangGraph per business workflow (standup follow-up, Jira bulk correction, audit artifact pack, docs reconciliation, architecture inventory intake), not one generic prompt for everything.
- **Node-level tool scoping:** each node sees only the minimum tools required for that step (already started in Stage 10; apply it consistently to Deep Agents).
- **Context packs:** prebuilt, versioned bundles of docs/templates/schemas/examples per service; agents request only the pack they need.
- **Approval contracts:** HIL gates declare exactly what can be approved, who can approve, expiration, rollback/revert path, and audit fields.
- **Policy engine:** RBAC/capabilities from Stage 19 plus workflow policy (`dry_run_only`, connector write gates, data classification) decide which actions can run.
- **Memory and learned procedures:** project skills document repeatable internal workflows, while runtime agent memory stores only approved durable facts/summaries with retention rules.
- **Secure delegation:** subagents cannot escalate tools, cannot read secrets, and cannot call arbitrary MCP tools outside their profile.

### 21d. Deployment architecture

Target containerized deployment first, with a path to managed platforms:

- **Local/compose baseline:** `mcp` continues to host LangGraph code and tools; add `agent-runtime` only if isolation is needed.
- **Container runtime:** package Deep Agent runtime as a container image with explicit environment, healthcheck, `/healthz`, `/metrics`, and JSON logs.
- **AWS ECS/Fargate:** run runtime tasks/services with task roles, secrets from Secrets Manager/SSM, CloudWatch logs, and VPC connectivity to Mongo/warehouse and connector endpoints.
- **Kubernetes:** Helm/Kustomize manifests for runtime deployment, config maps for agent profiles, secrets for model/connectors, HPA around concurrent runs.
- **AWS Bedrock:** optional model provider path for planner/builder roles; map `PLANNER_*`/`BUILDER_*` to Bedrock model IDs, IAM auth, and Bedrock guardrails where useful.
- **Durability:** Mongo/checkpointer remains the state store initially; consider external managed Mongo/document DB and S3 artifact storage for larger outputs.

### 21e. Runtime model and APIs

Expose a runtime API that works for web UI, MCP clients, and background jobs:

- `agent_profiles_list` — list available agents, scopes, required capabilities, allowed tools.
- `agent_run_start` — start a typed run with `{agent, goal, context_refs, mode}`.
- `agent_run_status` — inspect graph state, current node, tool calls, budget, pending approvals.
- `agent_run_resume` — resume from HITL interrupt with approval/rejection/edited payload.
- `agent_run_cancel` — cancel and persist a terminal state.
- `agent_run_artifacts` — fetch generated proposals, reports, docs, patches, logs.

Prefer adding these as MCP tools plus web `/api/agents/*` proxies, so existing clients and future UI pages share one runtime.

### 21f. Security, HITL, and audit requirements

- Every run has an actor, source (`web`, `mcp`, `standup`, `workflow`, etc.), agent profile, role/capability snapshot, and correlation ID.
- Tool calls are recorded with sanitized inputs/outputs; secrets are redacted.
- Write-capable tools require explicit profile permission and policy approval.
- HITL interrupts persist typed approval payloads and are resumable after restart.
- Approvals record actor, groups/roles, timestamp, original proposal, edited proposal, validation result, and apply result.
- Agent profiles can be marked `dry_run_only`, `read_only`, or `write_capable`.
- Service-specific agents should never receive unrelated connector credentials or broad tool catalogs.

### 21g. Observability and operations

- Structured logs for graph node start/end, tool call start/end, model request budget, approval events, failures, retries, and cancellations.
- `/metrics` counters: active runs, completed runs, failed runs, pending approvals, token usage, tool-call counts, average runtime per profile.
- Admin page for run history, pending approvals, traces, and profile config.
- Smoke tests for each profile and one end-to-end HITL resume path.
- Runbooks in Docs Wiki for operating the runtime, adding a new agent profile, and recovering stuck runs.

### 21h. Env surface (proposed)

| Var | Default | Required | Stage | Notes |
| --- | --- | --- | --- | --- |
| `DEEP_AGENT_RUNTIME_MODE` | `in_mcp` | no | 21 | `in_mcp`, `sidecar`, `remote` |
| `DEEP_AGENT_PROFILES_FILE` | `/app/deep_agent_profiles.yaml` | no | 21 | Agent profile/tool-scope config |
| `DEEP_AGENT_DEFAULT_PROVIDER` | `openai` | no | 21 | `openai`, `bedrock`, future providers |
| `DEEP_AGENT_BEDROCK_REGION` | — | no | 21 | Region for Bedrock planner/builder models |
| `DEEP_AGENT_CHECKPOINT_COLLECTION` | `deep_agent_checkpoints` | no | 21 | Durable LangGraph checkpoints |
| `DEEP_AGENT_RUN_COLLECTION` | `deep_agent_runs` | no | 21 | Run metadata/traces/artifacts |
| `DEEP_AGENT_ARTIFACT_DIR` | `/sandbox/agent-artifacts` | no | 21 | Local/container artifact output dir |
| `DEEP_AGENT_REQUIRE_HITL` | `true` | no | 21 | Require HITL for write-capable actions |
| `DEEP_AGENT_DRY_RUN_ONLY` | `true` | no | 21 | Global guardrail for production writes during POC |
| `DEEP_AGENT_MAX_PARALLEL_RUNS` | `4` | no | 21 | Runtime concurrency cap |
| `DEEP_AGENT_PROFILE_TIMEOUT_SECONDS` | `900` | no | 21 | Per-run wall-clock timeout |

### 21i. Verification intent

1. Profile list shows at least Jira, Docs, Audit, Workflow, Auth, Architecture, and Standup agents with non-overlapping tool scopes.
2. A Jira agent run generates dry-run ticket edits/creates and pauses at HITL approval.
3. A Docs agent run suggests a doc revision and pauses before applying.
4. A Standup agent run consumes session/chat context and emits Jira proposals without live writes.
5. A denied profile/tool call fails closed with a clear policy error.
6. Checkpoint/resume works across container restart.
7. Runtime can run in local compose; deployment manifests/docs exist for ECS/Fargate or K8S; Bedrock provider path is documented or stubbed.
8. Observability exposes logs/metrics and admin trace UI.

### Task checklist — Stage 21

- [ ] **S21.arch.1 — Write Deep Agent platform design doc**
  - Files: `docs/deep_agent_platform.md` (new), `IMPLEMENT.md`.
  - Done when: design explains relationship to Stage 4, profile model, service-specific agents, HITL pattern, deployment options (compose/Fargate/K8S/Bedrock), security boundaries, and future on-rails workflow direction.

- [ ] **S21.profile.1 — Define agent profile schema and config**
  - Files: `mcp/deep_agent/profiles.py` (new) or config loader, `mcp/deep_agent/profiles.yaml`, `.env.example`.
  - Done when: profiles declare name, description, allowed tools, context packs, model role/provider, budgets, capabilities required, write policy, and dry-run/read-only flags; invalid profiles fail at startup.
  - Depends on: S21.arch.1.

- [ ] **S21.policy.1 — Enforce per-profile tool allowlists**
  - Files: `mcp/deep_agent/catalog.py`, `mcp/deep_agent/planner.py`, runtime dispatcher.
  - Done when: planner and executor can only see/call tools allowed by the selected profile; attempts to call outside profile fail closed and are audited.
  - Depends on: S21.profile.1.

- [ ] **S21.context.1 — Add context packs for service-specific agents**
  - Files: `mcp/deep_agent/context.py` (new), Stage-14 Docs queries/templates, profile config.
  - Done when: Jira, Docs, Audit, Workflow, Auth, Architecture, and Standup profiles can load compact versioned context packs (templates, schemas, examples, runbook links) without dumping unrelated docs into prompt context.
  - Depends on: S21.profile.1.

- [ ] **S21.runtime.1 — Add typed agent runtime API/tools**
  - Files: `mcp/server.py`, `mcp/deep_agent/runtime.py` (new), `web/main.py`, `web/src/lib/types.ts`, `web/src/lib/queries.ts`.
  - Done when: `agent_profiles_list`, `agent_run_start`, `agent_run_status`, `agent_run_resume`, `agent_run_cancel`, and `agent_run_artifacts` exist as MCP tools and web proxies with typed request/response models.
  - Depends on: S21.policy.1, S21.context.1.

- [ ] **S21.hitl.1 — Implement reusable HITL interrupt/resume contract**
  - Files: `mcp/deep_agent/runtime.py`, `mcp/checkpointer.py`, workflow nodes that produce approvals.
  - Done when: write-capable profiles can pause with typed approval payloads, persist pending state, resume after approve/reject/edit, and survive container restarts.
  - Depends on: S21.runtime.1.

- [ ] **S21.agent.1 — Implement baseline service-specific agents**
  - Files: `mcp/deep_agent/profiles.yaml`, service-specific prompt/context modules, tests/smokes.
  - Done when: Jira, Docs, Audit, Workflow, Auth, Architecture, and Standup profiles each run a simple smoke goal using only their allowed tools and produce typed outputs.
  - Depends on: S21.hitl.1.

- [ ] **S21.ui.1 — Add Deep Agent operations/admin UI**
  - Files: `web/src/routes/agents.tsx` (new), `web/src/App.tsx`, `web/src/components/app-sidebar.tsx`.
  - Done when: admins can list profiles, start a run, inspect status/tool calls/artifacts, see pending approvals, and resume/cancel runs.
  - Depends on: S21.runtime.1.

- [ ] **S21.deploy.1 — Containerize/runtime deployment path**
  - Files: `compose.yaml`, optional `agent-runtime/` service, Dockerfiles, deployment docs.
  - Done when: runtime can run in current compose either in `mcp` or as a sidecar; healthcheck passes; secrets/config are env/secret-driven; no local-only assumptions block container deployment.
  - Depends on: S21.runtime.1.

- [ ] **S21.deploy.2 — Add ECS/Fargate or K8S deployment blueprint**
  - Files: `deploy/ecs/` or `deploy/k8s/`, `docs/deep_agent_platform.md`.
  - Done when: documented manifests/templates cover runtime container, task/service roles, secrets, network access, healthchecks, logs, scaling, and rollback. One target (ECS/Fargate or K8S) may be blueprint-only at this stage.
  - Depends on: S21.deploy.1.

- [ ] **S21.bedrock.1 — Design/implement Bedrock provider adapter path**
  - Files: `mcp/llm.py`, `mcp/deep_agent/provider.py` (new), `.env.example`, docs.
  - Done when: planner/builder roles can be configured for Bedrock model IDs or the Bedrock path is explicitly stubbed with interface + envs + IAM requirements; OpenAI-compatible path remains unchanged.
  - Depends on: S21.deploy.1.

- [ ] **S21.obs.1 — Add runtime observability and metrics**
  - Files: `mcp/deep_agent/runtime.py`, `mcp/server.py`, optional metrics endpoint, docs.
  - Done when: structured logs and metrics cover active/completed/failed runs, pending approvals, token budgets, tool-call counts, retries, cancellations, and per-profile latency.
  - Depends on: S21.runtime.1.

- [ ] **S21.security.1 — Add redaction and policy audit trail**
  - Files: runtime dispatcher, audit helpers, docs.
  - Done when: tool inputs/outputs are redacted for secrets, denied tool calls are persisted as policy events, approvals include actor/roles/groups, and dry-run/write-capable profile flags are enforced.
  - Depends on: S21.hitl.1.

- [ ] **S21.verify.1 — Deep Agent platform smoke suite**
  - Files: `scripts/smoke_deep_agent_platform.sh` or `.py`, existing `scripts/smoke_deep_agent.sh` updates.
  - Done when: smoke lists profiles, runs Jira and Docs profile dry-run goals, validates HITL pause/resume, verifies denied tool-call behavior, checks persistence, and confirms no live external writes occur.
  - Depends on: S21.agent.1, S21.security.1.

- [ ] **S21.verify.2 — Deployment and restart verification**
  - Files: deployment docs/scripts.
  - Done when: runtime restart does not lose pending HITL approvals; compose healthchecks pass; chosen deployment blueprint has a clear verification checklist.
  - Depends on: S21.deploy.1, S21.hitl.1.

---

## Stage 22 — UX polish: Dribbble-inspired chat, global assistant, Wrangler derived fields

**Goal:** Bring the app shell and high-use interaction surfaces up to the same visual quality as the LanGarland/Fleet-Dispatch design system. The current chat page is too barren; users should have a compact but accessible assistant available across views, with a full focused chat mode when chat is the primary task.

### 22a. Chat page + universal assistant

Reference design: Dribbble **Barista AI LLM SaaS Dashboard** — https://dribbble.com/shots/26781450-Barista-AI-LLM-SaaS-Dashboard

- Focused `/chat` should become a polished SaaS dashboard/chat experience inspired by the reference: richer hero/header, conversation list or context rail, prompt/action chips, readable message cards, and app-native navy/amber/teal styling.
- Add a **universal compact chat** at the bottom of the page for all major views unless chat is explicitly the page focus. It should be keyboard-accessible, screen-reader-friendly, and unobtrusive by default.
- The universal chat should expand into a detailed OpenWebUI/ChatGPT-style panel/drawer while preserving this app's styling and the Dribbble-inspired visual language.
- Avoid blocking route content, handle mobile/responsive layouts, and preserve existing `useChat` / `useAskData` behaviors unless a better shared hook abstraction is introduced.

### 22b. Wrangler successive-stage derived fields

Wrangler stage editors currently derive selectable fields mostly from the original sample/field summary. This breaks workflows where a prior stage creates derived fields (for example, a `group` stage adds `sum`/`count`, then a later `sort` stage cannot select that derived field).

- Track field names across successive stage previews, including fields introduced by `$group`, accumulator output names, `$project` aliases, and other derived output columns.
- Later stages should offer derived fields from the latest successful upstream preview, not only the original collection sample.
- Preserve existing validation and saved pipeline round-tripping; do not allow stale derived fields to silently compile if the upstream stage changes and the field disappears.

### 22c. Brand/banner image update

Update the top-left app banner/logo image to use:

`/opt/stacks/sglandsimple/web/dist/assets/d6057657-40c7-4112-85fa-06322881a692.png`

The image should be sized as a modern banner mark (not tiny, stretched, or pixelated), fit the sidebar/top-left chrome, and include appropriate alt text. If the source image should live under `web/src/assets` instead of committed `dist`, copy it into the source tree and reference it through the Vite asset pipeline.

### Task checklist — Stage 22

- [ ] **S22.chat.1 — Redesign focused `/chat` page from Dribbble reference**
  - Files: `web/src/routes/chat.tsx`, shared UI components as needed, possibly `web/src/components/*`.
  - Done when: `/chat` is no longer barren; it has a polished dashboard/chat layout inspired by the Barista AI reference, fits the existing navy/amber/teal design system, supports normal chat + Ask Data, and passes responsive/accessibility basics.

- [ ] **S22.chat.2 — Add universal compact bottom chat across app views**
  - Files: `web/src/App.tsx`, app shell/sidebar/layout components, `web/src/routes/chat.tsx` or shared chat components/hooks.
  - Done when: every non-focused major view has a compact bottom assistant entry point; it is keyboard-accessible, does not cover critical controls, expands into a fuller OpenWebUI/ChatGPT-style panel, and is hidden or transformed appropriately on `/chat` where chat is the primary focus.

- [ ] **S22.wrangler.1 — Offer derived fields in successive Wrangler stages**
  - Files: `web/src/routes/wrangler.tsx`, wrangler stage helper/types if needed, backend only if preview payload needs more metadata.
  - Done when: fields created by earlier stages (e.g. `$group` accumulator outputs such as `sum`, `count`, aliases from project stages) are available for later stage editors like sort/project; options update after successful upstream previews and stale derived fields are surfaced rather than silently accepted.

- [ ] **S22.brand.1 — Replace top-left banner image and modernize sizing**
  - Files: app shell/sidebar/logo component and asset location (`web/src/assets` preferred if using Vite-managed assets).
  - Done when: the top-left banner uses `d6057657-40c7-4112-85fa-06322881a692.png`, is sized/cropped as a modern banner image, includes useful alt text, and builds without relying on an ephemeral `dist`-only asset path.

---

## Stage 5 — GitHub Copilot as an upstream provider (SHELVED)

**Goal:** Let the stack target a GitHub Copilot subscription as `UPSTREAM_*` so the same agent + MCP plumbing can run on Copilot-hosted models.

> **Status: SHELVED (2026-05-22) — do not pick up.** Permanently parked at the user's
> direction until they say otherwise. No tasks below are eligible. The narrative is kept
> for reference only; do not start S5.* work, and skip Stage 5 when grabbing units from
> this backlog. (Also listed under "Out of scope" below.)

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
- GitHub Copilot as an upstream provider (Stage 5 — **shelved 2026-05-22** at user direction; full narrative retained under Stage 5 for if/when it's revived).

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
| `ASK_DATA_MAX_DOCS` | `4` | no | 1 | cap on per-doc fan-out |
| `ASK_DATA_DEADLINE_SECONDS` | `240` | no | 15 | overall wall-clock deadline for ask_data |
| `ASK_DATA_BATCH_NOTES` | `true` | no | 15 | batch per-doc interpretation into single LLM call |
| `ASK_DATA_LIMIT_CEILING` | `50` | no | 1 | hard limit on query results |
| `LANGGRAPH_CHECKPOINT_COLLECTION` | `lg_checkpoints` | no | 1 |  |
| `LLM_TIMEOUT` | `120` | no | 1 | per-LLM-call timeout in seconds |
| `LLM_CONCURRENCY` | `2` | no | 1 | semaphore cap for parallel LLM calls |
| `WEB_PORT` | `5452` | no | 2 | host bind for web frontend |
| `REQUEST_TIMEOUT` | `300` | no | 2 | web service proxy timeout (seconds) |
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
| `DEEP_AGENT_RUNTIME_MODE` | `in_mcp` | no | 21 | `in_mcp`, `sidecar`, or `remote` runtime mode |
| `DEEP_AGENT_PROFILES_FILE` | `/app/deep_agent_profiles.yaml` | no | 21 | Agent profile/tool-scope config |
| `DEEP_AGENT_DEFAULT_PROVIDER` | `openai` | no | 21 | `openai`, `bedrock`, future providers |
| `DEEP_AGENT_BEDROCK_REGION` | — | no | 21 | Region for Bedrock planner/builder models |
| `DEEP_AGENT_CHECKPOINT_COLLECTION` | `deep_agent_checkpoints` | no | 21 | Durable LangGraph checkpoints |
| `DEEP_AGENT_RUN_COLLECTION` | `deep_agent_runs` | no | 21 | Run metadata/traces/artifacts |
| `DEEP_AGENT_ARTIFACT_DIR` | `/sandbox/agent-artifacts` | no | 21 | Agent artifact output directory |
| `DEEP_AGENT_REQUIRE_HITL` | `true` | no | 21 | Require HITL for write-capable actions |
| `DEEP_AGENT_DRY_RUN_ONLY` | `true` | no | 21 | Global POC guardrail for production writes |
| `DEEP_AGENT_MAX_PARALLEL_RUNS` | `4` | no | 21 | Runtime concurrency cap |
| `DEEP_AGENT_PROFILE_TIMEOUT_SECONDS` | `900` | no | 21 | Per-run wall-clock timeout |
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
| `AUTH_MODE` | `basic` | no | 19 | Web auth mode: `sso`, `basic`, `trusted_network`, `headers`, `ldap`, or `disabled` |
| `AUTH_ALL_USERS_GROUP` | `sg_all_users` | no | 19 | Base authenticated/network group |
| `AUTH_ADMIN_GROUP` | `sg_sec_admin` | no | 19 | Grants admin role |
| `AUTH_APP_USER_GROUP` | `sg_app_user` | no | 19 | Grants app owner/onboarding role |
| `AUTH_AUDIT_USER_GROUP` | `sg_audit_users` | no | 19 | Grants audit artifact/finding role |
| `AUTH_TRUSTED_HEADER_USER` | `X-Forwarded-User` | no | 19 | Header for upstream proxy/SSO username |
| `AUTH_TRUSTED_HEADER_GROUPS` | `X-Forwarded-Groups` | no | 19 | Optional proxy/SSO group header |
| `AUTH_SSO_REQUIRED` | `false` | no | 19 | Production guardrail; require SSO mode when true |
| `AUTH_BASIC_USERS_FILE` | `/data/auth/users.json` | no | 19 | POC Basic Auth seeded users/hashes file |
| `AUTH_BASIC_SEED_PASSWORD` | — | no | 19 | Dev-only password for generated seed users; prefer gitignored secret |
| `AUTH_DEV_HEADERS_ENABLED` | `false` | no | 19 | Allows `X-SG-User`/`X-SG-Groups` simulation when true |
| `AUTH_LDAP_URL` | — | no | 19 | Future LDAP endpoint / adapter URL |
| `AUTH_LDAP_BASE_DN` | — | no | 19 | Future LDAP search base |
| `AUTH_LDAP_BIND_SECRET_FILE` | — | no | 19 | Future mounted bind secret path |
| `AUTH_CACHE_TTL_SECONDS` | `300` | no | 19 | User/group lookup cache TTL |
| `STANDUP_WS_ENABLED` | `true` | no | 20 | Enable websocket endpoint for live standup sessions |
| `STANDUP_SESSION_TTL_HOURS` | `24` | no | 20 | Inactive-session TTL before archival |
| `STANDUP_MAX_MESSAGES` | `500` | no | 20 | Per-session message cap before archival/summarization |
| `STANDUP_AGENT_ENABLED` | `true` | no | 20 | Enables standup summarization/proposal generation |
| `STANDUP_AGENT_INTERVAL_SECONDS` | `0` | no | 20 | `0` = on-demand only; positive enables periodic suggestions |
| `STANDUP_REQUIRE_ADMIN` | `true` | no | 20 | Require admin/approval capability for session control and approvals |
| `STANDUP_DRY_RUN_ONLY` | `true` | no | 20 | Extra guardrail: never apply live writes from Standup even if connector writes are enabled |
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

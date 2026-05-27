# IMPLEMENT.md — sglandsimple enterprise rollout (LangGraph edition)

This document is the implementation plan for evolving the current stack into an enterprise-shaped pattern: **server-side LangGraph agent workflows over a NoSQL store, fronted by both a web UI and direct MCP access from IDE/agent clients (opencode, VS Code Chat, PiAgent).**

> The repo name `sglandsimple` predates the framework choice. Despite the name, **this plan uses LangGraph**, not SGLang.

> **Archive note (2026-05-22):** Stages 0–2, 4, 7–12, 13, 15, 16, 17 are complete and verified. Their full narrative + task checklists were moved to **`IMPLEMENT-ARCHIVE.md`** to keep this file focused on open work. See the "Completed stages" table below for one-line summaries; open `IMPLEMENT-ARCHIVE.md` for the full detail of any archived stage. This file retains the header/ground-rules, the **Env surface** table (live reference), and the **full content of every stage with open tasks** (3, 5, 6, 14, 18, 19, 20, 21, 22, 23). Stages 6 (followups), 13, 14, and 15 are complete but retained here until the next archive pass.

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
| **23** | Confluence wire-up + cross-system enrichment | Live-capable Confluence MCP connector (dry-run/live-gated), `confluence_pages` canonical seed, cross-system overlap-chain enrichment, teaching docs, and smoke verification. Complete — eligible for archive. |

---

# Open work

The remaining sections below are the stages with unfinished tasks: **3** (manual external-client smoke), **5** (TBD — shelved), **20** (standup chat dedup followup), **21** (Deep Agent platform — in progress), **26** (chat runtime visibility — planned), **27** (standup view layout — **DONE**, retained until archive), **28** (standup multi-session chat + AI extraction — planned), **29** (standup approvals lifecycle + broader apply + admin gate toggle — planned), and **30** (multi-agent worktree/commit hygiene enforcement — planned). Stages **6** (followups), **13**, **14**, **15**, **18** (architecture diagram v2), **19** (web auth/RBAC), **22** (UX/chat polish + Wrangler derived fields), **23** (Confluence wire-up + cross-system enrichment), **24** (standup Epics + Templates reference rail), and **25** (standup production approvals viewport) are complete but retained here until the next archive pass.

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

- [x] **S18.export.1 — Add share/export artifact path** ✅ DONE
  - Files: `web/src/routes/architecture.tsx`, `web/src/lib/arch-export.ts`.
  - Done: `/architecture` now has an Export menu that copies Mermaid and downloads standalone SVG/PNG artifacts. Exports include a title, timestamp, mode/persona context, protocol/current-vs-planned styling, concern markers, and a legend.
  - Depends on: S18.flow.1.

- [x] **S18.docs.1 — Link diagram to Stage-14 Docs Wiki** ✅ DONE
  - Files: `web/src/components/architecture/arch-drawer.tsx`, `web/src/components/architecture/arch-filters.tsx`, `web/src/routes/docs.tsx`, `docs/architecture-inventory-template.md`.
  - Done: architecture runbook links deep-link into the Docs Wiki with `?doc=...`; the Known unknowns panel links to the architecture inventory capture form (`docs/architecture-inventory-template`); `/docs` initializes from the `doc` query parameter. The inventory template remains importable by `scripts/import_docs.py`.
  - Depends on: S18.details.1.

- [x] **S18.verify.1 — Verify build and high-level readability** ✅ DONE
  - Files: `IMPLEMENT.md`.
  - Done: `python3 -m py_compile mcp/*.py web/*.py scripts/*.py` and `cd web && npm run build` pass. Manual code/UI review confirms the default lane layout remains stakeholder-readable, the RISK/SNOW→artifact overlay is exportable, the legend travels with exports, and engineer mode still exposes details/runbooks/known unknowns.
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

- [x] **S19.admin.1 — Add auth diagnostics/admin page** ✅ DONE
  - Files: `web/src/routes/auth-admin.tsx` (new), `web/src/App.tsx`, `web/src/components/app-sidebar.tsx`, `web/main.py`, `web/auth.py`, `web/Dockerfile`, `web/src/lib/{queries,types}.ts`.
  - Done: `/api/auth/diagnostics` is guarded by `canAdminAuth` and returns current auth mode, group mappings, role→capability matrix, Basic-mode seeded identity hints, users-file cache status, LDAP adapter status, and the recent-deny ring buffer. `/auth-admin` is route-guarded for admins and renders diagnostics with no credential leakage; non-admin direct access gets the existing 403 route behavior.
  - Depends on: S19.frontend.2.

- [x] **S19.logout.1 — Add logout button + /api/logout endpoint** ✅ DONE
  - Files: `web/main.py`, `web/src/lib/queries.ts`, `web/src/components/topbar.tsx`.
  - Problem: With HTTP Basic Auth the browser caches credentials per-origin with no JS API to clear them. Sessions persisted even across incognito windows because the browser re-sends the cached Authorization header on every request to the same origin.
  - Done:
    1. Backend: `POST /api/logout` returns 401 with `WWW-Authenticate: Basic realm="sglandsimple"` — this forces the browser to forget its cached Basic Auth credentials for the origin.
    2. Frontend: `useLogout()` mutation in `queries.ts` calls `/api/logout` (swallowing the expected 401), clears the React Query cache via `qc.clear()`, and hard-navigates to `/` to trigger the browser's native login prompt.
    3. Topbar: `LogOut` icon button next to the display name calls `logout.mutate()`.
  - For non-basic auth modes (sso, trusted_network, headers, ldap, disabled) the endpoint still returns 401 as a uniform signal — the frontend handles it identically.
  - Depends on: S19.frontend.2.

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

- [x] **S19.verify.1 — Integrated verification** ✅ DONE
  - Files: `IMPLEMENT.md`, `progress.md` after implementation.
  - Done when: `python3 -m py_compile web/*.py` and `cd web && npm run build` pass; smoke auth passes; manual UI checks confirm nav/action gating for all four groups; no secrets are committed.
  - Depends on: S19.frontend.2, S19.tests.1.
  - Done (2026-05-22): `python3 -m py_compile web/*.py` and `cd web && npm run build` (tsc -b + vite) both clean. `scripts/smoke_auth.sh` in basic mode: 83 PASS / 0 FAIL / 3 SKIP (skips are non-basic modes — startup env, not per-request). New `/api/auth/diagnostics` verified end-to-end against the rebuilt `web` container: admin (`jordan.reyes`, `canAdminAuth`) → full payload (6 seeded users loaded, group→role map, role→capability matrix, fixture LDAP adapter, recent-deny ring buffer); viewer (`avery.stone`) → 403, and that deny was captured in `recent_denies`. Leak check: no `password`/`pbkdf2`/`hash` substrings in the payload. RBAC gating across all four groups confirmed via the seeded-user capability sets returned by `/api/me` + the route/action guards (`RequireCapability`, `DisabledWithTooltip`). No secrets committed: `perm/auth/` (the only place hashes live) is gitignored. NOTE for operator: verification re-seeded the gitignored `perm/auth/users.json` with the POC password `changeme-poc`; re-run `AUTH_BASIC_SEED_PASSWORD=<your-secret> python3 web/auth_seed.py` (then `docker compose up -d web` with that var exported) to restore your own password.

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

- [x] **S20.identity.1 — Wire standup chat to S19 auth identity (display name + cross-service user handle)** ✅ DONE
  - Files: `web/standup_ws.py`, `web/src/components/standup-chat.tsx`, `web/src/routes/standup.tsx`, `web/standup_store.py`.
  - Done: frontend uses the Stage-19 auth provider to derive display name/email and sends them on websocket join/chat. Backend websocket connect resolves `auth.resolve_user(websocket)` where possible, tracks `ClientState.email`, persists `author_email`, and emits structured presence entries with `display_name` + `email`. Auth-disabled or unresolved sessions keep the previous browser/header/query fallback behavior.
  - Depends on: S20.ws.1, S19.backend.1.

- [x] **S20.agent.2 — Give agent docs/workflow/template context** ✅ DONE
  - Files: `mcp/standup_agent.py`, Stage-9 workflow Jira template, `docs/standup.md`.
  - Done: `standup_summarize` now supplies deterministic story-template context to the planner: Jira story shape, acceptance criteria, default standup labels/tags, priority/story-point guidance, selected epic/issue context, and Docs Wiki/Confluence links. `new_jira_work` dry-run payloads are normalized with summary, description, issue type, labels, priority, story points, acceptance criteria, epic link, doc links, related links, and source message IDs when missing.
  - Depends on: S20.agent.1.

- [x] **S20.proposals.1 — Stage Jira creates/edits as dry-run proposals** ✅ DONE
  - Files: `web/standup_store.py`, `web/standup_ws.py`, `scripts/smoke_standup_ws.py`, existing Jira staging tools.
  - Done: websocket `agent.summarize` now calls MCP `standup_summarize`, persists an `agent_run` plus `standup_proposals` with validation state, dry-run payload, source messages, actor, and rationale. `new_jira_work` remains a persisted dry-run standup proposal; `jira_edit` proposals with `issue_key`/`changes` or `edits[]` are staged through Stage-16 `jira_stage_edits` and immediately validated via `jira_validate_staged` without live writes. Unsupported/unavailable agent calls degrade to a persisted dry-run placeholder.
  - Depends on: S20.agent.1.

- [x] **S20.approval.1 — Add scrum-master/product-owner HITL approval tray** ✅ DONE
  - Files: `web/src/routes/standup.tsx`, `web/src/components/standup-chat.tsx`, `web/standup_ws.py`, `web/standup_store.py`.
  - Done: the `/standup` aside renders a live approval tray fed by `proposal.created`/`proposal.updated`/`agent.summary` websocket events, plus a `Summarize` button. Approve/Reject are gated by the `canApproveStandupActions` capability (`DisabledWithTooltip`); non-approvers are read-only. The websocket `proposal.approve`/`reject`/`edit` handlers enforce the capability server-side (`forbidden` error otherwise). On approve, `_apply_proposal_dry_run` re-validates any staged Jira edits via Stage-16 `jira_validate_staged` but never calls live apply (suppressed by `STANDUP_DRY_RUN_ONLY`); the store records `approval` with actor/decided_at/dry_run_only/applied + the validation `apply_result` and broadcasts `proposal.updated`. `proposal.edit` shallow-merges a dry-run payload patch on still-proposed proposals.
  - Depends on: S20.proposals.1.

- [x] **S20.trace.1 — Add expandable tool-call/configuration bubble** ✅ DONE
  - Files: `web/src/routes/standup.tsx`, `web/src/components/standup-chat.tsx`, existing connector query hook.
  - Done: Jira Configuration stays minimized by default and expands into a trace dashboard with connector health, dry-run/live-write gates, websocket state/presence/message counts, proposal/tool trace placeholders, and cross-service association details grouped by detected token/source author.
  - Depends on: S20.ui.1, S20.agent.1.

- [x] **S20.auth.1 — Apply Stage-19 RBAC to standup route/actions** ✅ DONE
  - Files: `web/auth.py`, `web/standup_ws.py`, `web/src/components/auth-provider.tsx`, `web/src/routes/standup.tsx`, `docs/standup.md`.
  - Done: added the `canApproveStandupActions` capability (`Capability.CAN_APPROVE_STANDUP`, granted to `admin`) in both `web/auth.py` and the TS `auth-provider`. The standup websocket requires a resolved Stage-19 identity to join (closes unauthenticated clients with `1008` unless `AUTH_MODE=disabled`); the snapshot proxy is guarded by `require_user` (401 otherwise); approve/reject/edit require the approver capability server-side. Presence carries a `can_approve` flag; the UI shows an `approver`/`read-only` badge and disables tray actions for non-approvers. Verified live: viewer (`avery.stone`) approve → `forbidden`; admin (`simone.patel`) approve → `approved`. No `smoke_auth.sh` regression (83/0/3).
  - Depends on: S20.policy.1; integrate fully after Stage 19 backend exists.

- [x] **S20.verify.1 — Websocket + agent + dry-run smoke** ✅ DONE
  - Files: `scripts/smoke_standup_ws.py`, `IMPLEMENT.md`.
  - Done: `scripts/smoke_standup_ws.py` now authenticates two clients via Basic Auth seeded POC users (viewer `avery.stone`, approver `simone.patel`) and asserts the full path: two-client join/chat, link/mention/Jira-key extraction, dry-run `agent.summarize` proposal persistence, **viewer approve → `forbidden`**, **admin approve → `approved` with recorded actor + `applied=false` (dry-run only)**, and authenticated snapshot persistence. Verified green against the rebuilt stack. Snapshot proxy 401-without-auth and unauthenticated-ws-connect rejection also confirmed manually.
  - Depends on: S20.ws.1, S20.agent.1, S20.proposals.1.

- [x] **S20.verify.2 — UI build and standup screen-share review** ✅ DONE
  - Files: `web/src/routes/standup.tsx`, `web/src/components/standup-chat.tsx`, `IMPLEMENT.md`.
  - Done: `cd web && npm run build` passes (tsc + vite; only the pre-existing chunk-size warning). The `/standup` layout keeps the Jira Explorer dominant (xl two-column, ~1fr/23rem), the chat panel captures notes/links/mentions in the aside, the approval tray renders dry-run proposals with status/validation badges + Approve/Reject (capability-gated) + Summarize, and the Jira Configuration/tool-trace bubble stays collapsed by default. Approver vs read-only is reflected in the header badge.
  - Depends on: S20.explorer.1, S20.chat.1, S20.approval.1.

- [x] **S20.chat.2 — Deduplicate optimistic + echoed standup messages into one entry** ✅ DONE (resolved by the client-id reconciliation already in place)
  - Files: `web/src/components/standup-chat.tsx`, `web/standup_ws.py`, `web/standup_store.py`.
  - Done: the optimistic/echo duplicate is reconciled by client-id correlation rather than id-only dedup. The send payload carries the optimistic `id` (`web/src/components/standup-chat.tsx:610`); the server reads it as `client_message_id` (`web/standup_ws.py:410`, falling back from `id`), persists it (`web/standup_store.py:164`), and echoes it back in the broadcast `message`. On the client, `normalizeMessage` lifts `client_message_id` → `clientMessageId`, and `mergeMessages` builds a `clientToServerId` map so the local `pending` row is **dropped** when its echo (carrying the matching `clientMessageId`) arrives, while the surviving row is marked `acknowledgedLocal` → `pending:false`, `deliveryStatus:"sent"` — i.e. the echo reconciles the optimistic row into a single entry that loses the "sending" state. Snapshot/reconnect replay re-runs the same merge (dedup holds), and other participants' messages are unaffected (no `clientMessageId` match). Verified: no longer reproduces in current builds; `cd web && npm run build` clean.
  - Depends on: S20.chat.1.

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

> **Design decisions locked 2026-05-26 (see `docs/deep_agent_platform.md`):**
> (1) **Adopt the LangChain `deepagents` SDK** (`create_deep_agent` + `subagents=[...]`/`CompiledSubAgent`) as the runtime rather than extending the Stage-4 hand-rolled planner/builder — it provides delegation (`task`), isolated subagent context, per-subagent `tools`/`model`, and per-tool HITL (`interrupt_on`) on the LangGraph runtime we already use. (2) **One agent per external system**, with read/write gated **per-tool** via `interrupt_on` + `write_policy` (not separate reader/writer agents). (3) Existing graphs (`ask_data`, `docs_agent`) are wrapped as `CompiledSubAgent`, not rewritten. **Gating cost:** `deepagents` needs `langchain>=1.3 / langchain-core>=1.4`; we're on `0.3.28` — a 0.3→1.x upgrade is required first (`S21.upgrade.1`). The earlier per-profile-allowlist-on-Stage-4 design is the recorded fallback if the upgrade is too disruptive.
> **Roster (one per system):** orchestrator (router), atlassian_agent (Jira+Confluence), mongo_agent (`ask_data` wrap, read-only), github_agent (review+deploy), servicenow_agent (read + gated writes), aws_agent (describe/read), audit_agent (cross-system reads + Archer write), docs_agent + standup_agent (reuse existing). New environments (WAF/Splunk/Datadog) are added as config rows — see §14 of the design doc.

- [x] **S21.arch.1 — Write Deep Agent platform design doc** ✅ DONE
  - Files: `docs/deep_agent_platform.md` (new), `IMPLEMENT.md`.
  - Done: `docs/deep_agent_platform.md` selects the `deepagents` SDK (with the SDK→goal mapping table and the verbatim subagent schema), the one-agent-per-system roster with per-tool HITL, the LangChain 1.x upgrade as the gating risk, the `CompiledSubAgent` reuse of `ask_data`/`docs_agent`, the `profiles.yaml` shape, context packs, `interrupt_on` HITL resume, the `agent_run_*` runtime API + `/api/agents/*` proxies, security/audit/observability, the `DEEP_AGENT_RUNTIME_MODE` deployment path (incl. Bedrock), the extensibility recipe, verification intent, and the task map. §14 adds a **contributor's guide** justifying every agent + implementation decision from a learning perspective (for varied-experience adopters), with a step-by-step "add a new agent" recipe. Cross-references `docs/deep_agent.md`.

- [x] **S21.upgrade.1 — Upgrade to LangChain 1.x + install `deepagents`** ✅ DONE
  - Files: `mcp/requirements.txt`, `mcp/checkpointer.py`, `compose.yaml`, `sandbox-runtime/Dockerfile` (new), `.env.example`.
  - Done: bumped to the deepagents-compatible set — `deepagents==0.6.3`, `langchain-core==1.4.0`, `langchain==1.3.1` (pulled transitively), `langchain-openai==1.2.2`, `langgraph==1.2.1`, `langgraph-checkpoint-mongodb==0.4.0`, `openai==2.38.0`, `tiktoken==0.13.0`; relaxed `motor>=3.7,<4` (checkpoint-mongodb 0.4.0 needs `pymongo>=4.12`, which the old `motor==3.6.0` pin blocked) and `pydantic>=2.10,<3`. **One real API break, fixed:** checkpoint-mongodb 0.4.0 removed `langgraph.checkpoint.mongodb.aio.AsyncMongoDBSaver`; the unified `MongoDBSaver` now serves the async interface but its `from_conn_string` is a **sync** context manager — `mcp/checkpointer.py` switched to `with MongoDBSaver.from_conn_string(...)` inside our `@asynccontextmanager`. `mcp/llm.py` needed no change (uses the raw `openai` SDK + plain `ChatOpenAI(base_url/api_key/model/temperature)`, both stable in 1.x/2.x). The Dockerfile needed no change (already py3.12). **Verified live (mcp rebuilt + recreated, healthy):** container import-smoke of all langchain/langgraph modules + `server` + `deepagents` (0 failures); `smoke_deep_agent.sh` (planner/builder+checkpointer+sandbox+persistence) PASS; `smoke_ask_data.sh` 3/3; docs-agent HITL `interrupt`/`Command(resume)`/`MemorySaver` fresh→`waiting_approval`, resume `reject`→`completed` (0 applied); `smoke_agent.sh` PASS; `smoke_workflow.sh` PASS. Also added an **opt-in `sandbox` runtime container** (`sandbox-runtime/`, gated by the `sandbox` compose profile + `DEEP_AGENT_RUNTIME_MODE`) so default `up` is unchanged; it shares the `./sandbox` mount as uid 1000 and idles until S21.deploy.1 gives it the sidecar entrypoint. Stage-21 runtime env vars added to `.env.example`. (Upgrade was clean enough; the Stage-4 fallback was not needed.)
  - Depends on: S21.arch.1.

- [x] **S21.profile.1 — Define agent profile schema + `profiles.yaml` loader** ✅ DONE
  - Files: `mcp/deep_agent/profiles.py` (new), `mcp/deep_agent/profiles.yaml` (new), `.env.example`.
  - Done: `profiles.yaml` defines the orchestrator + 8 system agents (atlassian/mongo/github/servicenow/aws/audit/docs/standup) referencing **real** MCP + connector tool names; `profiles.py` has Pydantic models (`AgentProfile`/`OrchestratorProfile`/`PlatformProfiles`) declaring `name`/`description`/`model`/`allowed_tools`/`write_tools`/`write_policy`/`required_capability`/`context_packs`/`graph`/budgets, with **fail-fast** validation (write_tools ⊆ allowed_tools; no reserved runtime tools `task`/`write_todos`/`plan_task`/`run_plan`/`deep_agent`; read_only ⇒ no write_tools; write_tools ⇒ a Stage-19 capability; graph-backed ⇒ no allowed_tools; unique names). `interrupt_on()` emits `{t:True}` per write tool; `graph` marks `mongo_agent`→`ask_data`/`docs_agent`→`docs_agent` as future `CompiledSubAgent`s. `load_profiles`/`get_profiles` honor `DEEP_AGENT_PROFILES_FILE`; `validate_against_catalog()` defers live-tool checks to runtime. Verified in-container: 8 agents load, interrupt_on correct, all 5 negative cases reject, catalog check flags unknowns. Module is import-light (pydantic+yaml only; no deepagents import at load).
  - Depends on: S21.upgrade.1.

- [x] **S21.context.1 — Context packs for the system agents** ✅ DONE
  - Files: `mcp/deep_agent/context.py` (new), `mcp/standup_agent.py` story context (reused).
  - Done: `context.py` registers named, versioned `ContextPack`s (`jira_story_template` v1, `standup_labels` v1) built from **existing** Stage-20 material (`build_story_template_context`, `ACCEPTANCE_CRITERIA_FORMAT`, `DEFAULT_STANDUP_LABELS`) — no duplicated prompts. `render_packs(names)` emits one compact version-stamped block per pack for the subagent `system_prompt`; unknown packs raise (fail-fast, like profiles); `validate_profile_packs()` cross-checks every profile's `context_packs`. **Stage-24 convergence seam:** `_try_standup_templates_store()` reads the shared `standup_templates` store first, falling back to in-repo material, so neither side forks when Stage 24 lands. Verified in-container: both packs render from real standup content, unknown pack rejects, all profile pack refs validate clean. Import-light (no deepagents at load).
  - Depends on: S21.profile.1.

- [x] **S21.orch.1 — Orchestrator + per-tool allowlist enforcement** ✅ DONE
  - Files: `mcp/deep_agent/runtime.py` (new).
  - Done: `build_orchestrator()` compiles the validated profiles into a `deepagents` `create_deep_agent(...)` thin router — `tools=[]`, no system tools (deepagents injects `task`/`write_todos`), `system_prompt` says delegate to exactly one subagent via `task`. Each non-graph profile compiles to a subagent dict whose `tools` are LangChain `StructuredTool`s wrapping the single MCP seam `server._dispatch_tool`; graph profiles (`ask_data`/`docs_agent`) compile to `CompiledSubAgent` via `ask_data.build_graph()` / `docs_agent.build_docs_agent_graph()`. **Per-tool allowlist enforcement:** the wrapper re-checks membership at call time — a tool invoked outside its agent's allowlist returns a `[policy]` message and records a policy event (`policy_events()`), failing closed (defense in depth on top of the toolset already being scoped). Model selection hands deepagents a **configured `chat_model(role=...)`** (our upstream), not a provider string, so it never resolves to real OpenAI/Bedrock. `_live_tool_names()` builds the known-tool universe from static `TOOLS` + connector *classes* (so a real-but-disabled connector tool like `jira_apply_staged` is valid config); `validate_against_catalog` fails fast on genuinely unknown tools. Reserved-tool recursion guard holds (rejected at profile load). Verified in-container: orchestrator builds to a `CompiledStateGraph` over all 8 agents; out-of-allowlist call fails closed + records a policy event.
  - Depends on: S21.profile.1, S21.context.1.

- [x] **S21.runtime.1 — Typed agent runtime API/tools** ✅ DONE
  - Files: `mcp/server.py`, `mcp/deep_agent/runtime.py`, `web/main.py`, `web/src/lib/types.ts`, `web/src/lib/queries.ts`.
  - Done: `agent_profiles_list`, `agent_run_start` (`{agent?, goal, context_refs, mode}` — omit `agent` to let the orchestrator route), `agent_run_status`, `agent_run_resume`, `agent_run_cancel`, and `agent_run_artifacts` exist as MCP tools + `/api/agents/*` proxies with typed request/response models (no `any`); runs persist to `DEEP_AGENT_RUN_COLLECTION`. `agent_run_start` now persists a `running` record and spawns the orchestrator in the background so callers get a pollable `run_id` instead of blocking on long LLM/subagent hops. Web hooks cover profile list, start, status polling, resume, cancel, and artifacts.
  - Verified: `python3 -m py_compile mcp/deep_agent/runtime.py web/main.py` and `cd web && npm run build` clean.
  - Depends on: S21.orch.1.

- [x] **S21.hitl.1 — `interrupt_on` HITL interrupt/resume contract** ✅ DONE
  - Files: `mcp/deep_agent/runtime.py`, `mcp/server.py`, `web/main.py`, `web/src/routes/agents.tsx`, `web/src/lib/types.ts`, `scripts/smoke_agent_hitl.py` (new), `docs/deep_agent_platform.md`.
  - Done: a `write_tools` tool pauses the run via deepagents `interrupt_on`; `_extract_interrupt` parses the `HumanInTheLoopMiddleware` `HITLRequest` into a typed `ApprovalRequest` (`tool`, args `payload`, `rationale`, and `required_capability` resolved from the owning profile). `agent_run_resume({run_id, decision, actor, actor_capabilities})` builds the middleware's required `{"decisions": [...]}` payload (one per pending action), enforces the resuming actor's Stage-19 capability before approve/edit (`PermissionDeniedError` → web proxy 403), and downgrades approve→no-write reject when `DEEP_AGENT_DRY_RUN_ONLY` is on (write tools also keep their own `*_WRITES_ENABLED` gate). Pending approvals survive an MCP restart (run record + checkpoint both in Mongo). The `/agents` UI surfaces the required capability and disables Approve for users who lack it. **Verified live** (mcp rebuilt + recreated): pause→typed approval (`jira_apply_staged`/`canApplyJira`), approve-without-cap refused, approve-with-cap-under-dry-run applied nothing, and a paused approval survived `docker compose restart mcp` and resumed cleanly (`scripts/smoke_agent_hitl.py`); `smoke_agent.sh` + `smoke_ask_data.sh` still pass.
  - Depends on: S21.runtime.1.

- [x] **S21.agent.1 — Implement the baseline system agents** ✅ DONE
  - Files: `mcp/deep_agent/runtime.py` (CompiledSubAgent `messages` adapter for the graph-backed agents), `scripts/smoke_agents.py` (new), `docs/deep_agent_platform.md`.
  - Done: all 8 system agents (atlassian/mongo/github/servicenow/aws/audit/docs/standup) + orchestrator run with non-overlapping scopes. **Fixed the long-standing graph-agent hang** (the known runtime.1 CompiledSubAgent input-contract issue): deepagents requires a CompiledSubAgent runnable to consume *and* return a `messages` key, but `ask_data`'s `AskDataState` (`question`/`answer`) and `docs_agent`'s `DocsAgentState` have none — so the orchestrator→graph delegation passed `{messages}` the native graph ignored, produced no `messages`, and the run sat at `running` forever. Added `_messages_adapter` (a tiny `MessagesState`-in/out graph whose node lifts the delegated task via `_last_human_text`, runs the native `run_ask_data`/`run_docs_agent`, and returns the rendered result as an `AIMessage`); `_graph_runnable` now wraps both graphs through it. **Verified live** (`scripts/smoke_agents.py` with `RUN_GRAPH_AGENTS=1`): profiles/scopes match; aws/servicenow read-only agents complete scoped (correctly report disabled connectors, no write); orchestrator routes an un-targeted goal; **mongo_agent now completes ~12s with a grounded answer** ("23 open tickets") and **docs_agent completes** instead of hanging; the atlassian write agent pauses at `interrupt_on` for `jira_apply_staged` (cap `canApplyJira`). `smoke_ask_data.sh` (3/3), `smoke_agent.sh`, and `smoke_agent_hitl.py` still pass.
  - Depends on: S21.hitl.1.

- [x] **S21.extend.1 — Prove the config-only "add an agent" path** ✅ DONE
  - Files: `mcp/connectors/datadog.py` (new read-only mock connector), `mcp/connectors/__init__.py` (1 registry line), `mcp/deep_agent/profiles.yaml` (1 `datadog_agent` row), `.env.example` (`CONN_DATADOG_ENABLED`/`DATADOG_MCP_*`), `scripts/smoke_agent_extend.py` (new), `docs/deep_agent_platform.md` (§14 worked example).
  - Done: added a brand-new read-only `datadog_agent` (a new observability environment) end-to-end via **only** a connector class + one `_CONNECTOR_CLASSES` line + one `profiles.yaml` row — **no change to `runtime.py`, the orchestrator prompt, or `server._dispatch_tool`** (connector tools auto-route to the connector's `dispatch`, server.py:1834–1839). **Verified live** (`CONN_DATADOG_ENABLED=true`, mcp rebuilt): `datadog_agent` is the 9th entry in `agent_profiles_list` (read_only, no capability); `datadog_list_monitors` dispatches; a scoped goal ("list alerting monitors") runs to `completed` with typed output (surfaced the 1 alerting monitor + its finding/epic refs). `scripts/smoke_agent_extend.py` PASS; `python3 -m py_compile` clean.
  - Depends on: S21.agent.1.

- [x] **S21.ui.1 — Deep Agent operations/admin UI** ✅ DONE
  - Files: `web/src/routes/agents.tsx` (new), `web/src/App.tsx`, `web/src/components/app-sidebar.tsx`.
  - Done: `/agents` is canRunWorkflow-gated and reachable from the sidebar. Admin/operators can list profiles, select an agent (or leave blank for orchestrator routing), start a dry-run, poll status, inspect result/error/artifacts, view pending approval payloads, approve/reject via `agent_run_resume`, and cancel running jobs.
  - Verified: `cd web && npm run build` clean.
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
  - Done when: a profile's `provider: bedrock` maps that agent's `model` to a Bedrock model ID + region + IAM, or the Bedrock path is explicitly stubbed with interface + envs + IAM requirements; the OpenAI-compatible path remains unchanged.
  - Depends on: S21.deploy.1.

- [ ] **S21.obs.1 — Add runtime observability and metrics**
  - Files: `mcp/deep_agent/runtime.py`, `mcp/server.py`, optional metrics endpoint, docs.
  - Done when: structured logs and metrics cover active/completed/failed runs, pending approvals, token budgets, tool-call counts, retries, cancellations, and per-profile latency.
  - Depends on: S21.runtime.1.

- [ ] **S21.security.1 — Add redaction and policy audit trail**
  - Files: runtime dispatcher, audit helpers, docs.
  - Done when: tool inputs/outputs are redacted for secrets, denied tool calls (outside an agent's allowlist) are persisted as policy events, approvals include actor/roles/groups, and `read_only`/`dry_run_only`/`write_capable` policy flags are enforced.
  - Depends on: S21.hitl.1.

- [ ] **S21.verify.1 — Deep Agent platform smoke suite**
  - Files: `scripts/smoke_deep_agent_platform.sh` or `.py`, existing `scripts/smoke_deep_agent.sh` updates.
  - Done when: smoke lists agents, has the orchestrator route a goal to a subagent, runs Atlassian (dry-run) and Mongo (read-only) agent goals, validates `interrupt_on` HITL pause/resume, verifies a denied/out-of-allowlist tool call fails closed, checks persistence, and confirms no live external writes occur.
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

### 22e. Chat conversation readability: newest-first feed, collapsed query, slimmer banner

Follow-up polish on the focused `/chat` workspace after the column flip (S22.chat.3). Three independent issues:

- **Newest-first ordering.** The live conversation should render newest additions at the **top**, pushing older turns down. Today `ConversationFeed` renders oldest→newest with a scroll-to-bottom on send; invert so a new user/assistant turn appears at the top of the feed without the user having to scroll. Keep the request/response pairing legible (a turn and its reply should stay visually adjacent) and preserve the busy/"thinking…" indicator placement and `aria-live` semantics for screen readers.
- **Collapse the Mongo query by default.** Ask Data answers currently always append a `## Query used` section with the raw spec as a fenced ```json block (`mcp/ask_data.py` `format_*`). Only show that query inline when the user **specifically asks for it** (e.g. the question mentions "query"/"pipeline"/"how did you", or an explicit toggle). Otherwise present it as a **single expandable** element (collapsed by default) rendered as a ```json snippet — e.g. a `<details>`-style disclosure in the rendered Markdown, or a front-end collapsible that the chat transcript card understands. The default answer view should be the prose + evidence, with the query one click away.
- **Slim, dynamic hero banner.** The current `/chat` hero `Card` is a tall static marketing block that wastes vertical space. Replace it with something **dynamic** and compact: full viewport width but only ~100px tall. "Dynamic" = it should surface live/contextual content (e.g. message/turn count, active connector or MCP status, last-activity timestamp, a rotating tip, or a compact live signal) rather than fixed marketing copy. Free up the reclaimed vertical space for the conversation feed.

### Task checklist — Stage 22

- [x] **S22.chat.1 — Redesign focused `/chat` page from Dribbble reference** ✅ DONE
  - Files: `web/src/routes/chat.tsx`, `web/src/components/chat-assistant.tsx`.
  - Done: `/chat` now renders a polished dashboard-style assistant workspace with a navy/amber/teal hero, prompt chips, insight cards, context rail, upgraded transcript cards, and a shared composer that preserves normal chat and Ask Data behavior.

- [x] **S22.chat.2 — Add universal compact bottom chat across app views** ✅ DONE
  - Files: `web/src/App.tsx`, `web/src/components/chat-assistant.tsx`.
  - Done: non-`/chat` routes get a keyboard-focusable bottom assistant launcher that expands into a styled dialog/panel with quick prompts, transcript, Ask Data, and a link to the full chat view. It is hidden on `/chat`, and app content receives bottom padding only while the compact assistant is present.

- [x] **S22.wrangler.1 — Offer derived fields in successive Wrangler stages** ✅ DONE
  - Files: `web/src/routes/wrangler.tsx`, `web/src/lib/pipeline.ts`.
  - Done: Wrangler stage field options now derive from prior successful previews when available, fall back to static stage-output inference, include `$group` accumulator outputs and `$project` aliases, clear downstream previews after upstream edits, and surface stale selected fields with destructive styling/warnings rather than silently accepting them.

- [x] **S22.brand.1 — Replace top-left banner image and modernize sizing** ✅ DONE
  - Files: `web/src/components/app-sidebar.tsx`, `web/src/assets/d6057657-40c7-4112-85fa-06322881a692.png`, `web/src/vite-env.d.ts`.
  - Done: the sidebar's top-left mark now uses the Vite-managed `d6057657-40c7-4112-85fa-06322881a692.png` banner asset with `alt="LanGarland Fleet Dispatch"`, modern cropped sizing for expanded/collapsed sidebar states, and no dependency on an ephemeral `dist`-only path.

- [x] **S22.chat.3 — Flip `/chat` columns + compact suggested-prompt list** ✅ DONE
  - Files: `web/src/components/chat-assistant.tsx`.
  - Done: conversation feed + composer moved to the main wide right column (`xl:order-2`); suggested prompts moved to the narrow 18rem left rail (`xl:order-1`). Added a `variant: "chips" | "list"` prop to `PromptChips`; the rail renders Starter + Direct-data prompts as compact vertical lists. Dropped the redundant hero starter chips.

- [x] **S22.chat.4 — Newest-first live conversation feed** ✅ DONE
  - Files: `web/src/components/chat-assistant.tsx`.
  - Done: `ConversationFeed` reverses messages (newest at top, push older down); removed scroll-to-bottom `endRef`; "thinking…" indicator and `aria-live` preserved at top; `cd web && npm run build` clean.
  - Depends on: S22.chat.3.

- [x] **S22.chat.5 — Collapse Ask Data Mongo query unless requested** ✅ DONE
  - Files: `mcp/ask_data.py` (keyword heuristic + `<details>` wrapping), `mcp/server.py` (pass `question`), `web/src/components/markdown.tsx` (add `rehype-raw`), `web/package.json` (dep).
  - Done: `render_markdown` accepts `question` kwarg; when the question contains query-related keywords (`"query"`, `"pipeline"`, `"how did you"`, `"what query"`, `"show query"`, `"what did you run"`) the query section renders expanded inline; otherwise wrapped in `<details><summary>View query</summary>` collapsed by default. `python3 -m py_compile mcp/ask_data.py mcp/server.py` + `cd web && npm run build` clean.
  - Depends on: nothing (touches the formatter + transcript rendering).

- [x] **S22.chat.6 — Replace tall static hero with slim dynamic banner (~100px)** ✅ DONE
  - Files: `web/src/components/chat-assistant.tsx`.
  - Done: replaced the tall hero `Card` (badges + h2 + p + 3 insight cards) with a slim ~100px full-width banner showing assistant name, message count, last-activity `RelativeTimeFormat`, MCP badge, and a rotating tip from `CHAT_TIPS` cycling every 8s; reclaimed vertical space goes to the conversation feed; layout stays responsive; `cd web && npm run build` clean.
  - Depends on: S22.chat.3.

---

## Stage 23 — Confluence wire-up + cross-system data enrichment ("make the POC lively")

> **Status: COMPLETE & verified live (disabled/dry-run mode).** All `S23.*` tasks are done. Live Confluence tenant smoke still requires operator-supplied `CONFLUENCE_TOKEN`/`CONFLUENCE_MCP_URL`, but the connector gates and dry-run docs-sync path are implemented and verified.

**Goal:** Turn the dashboard from a thin demo into a *teachable, lively enterprise simulation*. Two threads:

1. **Confluence wire-up** via a single `CONFLUENCE_TOKEN` env var, following the same live-MCP pattern Stage 16 established for Jira (`mcp/connectors/jira.py`). When the token is present the connector talks to the hosted Atlassian MCP server; otherwise it stays on its (now-expanded) in-memory sample.
2. **Cross-system enrichment.** Grow the seeded Mongo collections and connector samples so every dashboard surface has dense, *internally-consistent* data, and the highest-value teaching artifact — **overlap chains** (`risk finding → Jira epic → Confluence page`, plus `commit → PR → epic`, `ServiceNow change → epic`, `Snowflake evidence query → finding`) — is visible end-to-end. The not-yet-wired services (ServiceNow, Snowflake, GitHub commits, Archer, AWS) keep their connector-sample shape but get more rows that *reference the same keys* as the live-ish Jira/Confluence/Mongo data, so the world looks coherent.

This is explicitly a **teaching environment** for coworkers learning deep agents, agentic workflows, and MCP. Process documentation (in the in-app `/docs` wiki and `docs/`) should explain *what each dashboard does and which agent/MCP path produces it*, not just describe the data.

### Why this shape

- The connector + seed-collection split already exists (`mcp/connectors/*`, `mongo-seed/*.js`, `mcp/db.py` `KNOWN_COLLECTIONS`). Stage 23 is **additive enrichment**, not new architecture: more rows, more cross-references, one connector promoted from mock-only to live-capable.
- The single most pedagogically valuable thing in an enterprise GRC stack is the **traceability chain**. A learner should be able to start at an Archer/audit risk finding, follow it to the Jira epic that remediates it, the GitHub commits/PRs that implement it, the ServiceNow change that ships it, the Snowflake query that evidences it, and the Confluence runbook/evidence page that documents it — all sharing `epic_key` / `ticket_refs` / `finding_id`. Stage 23 makes those keys line up across every collection and connector sample.
- `CONFLUENCE_TOKEN` (user's wording) is the live gate. To stay consistent with the existing `CONFLUENCE_MCP_URL` / `CONFLUENCE_MCP_TOKEN` surface, Stage 23 **adds `CONFLUENCE_TOKEN` as the primary credential** and treats the older `CONFLUENCE_MCP_TOKEN` as a fallback alias (no breaking rename), mirroring how Jira reads `JIRA_MCP_TOKEN`.

### 23a. Confluence live connector (Stage-16 parity)

Promote `mcp/connectors/confluence.py` from mock-only to live-capable, copying the proven shape of `mcp/connectors/jira.py`:

- Read `CONFLUENCE_TOKEN` first, fall back to `CONFLUENCE_MCP_TOKEN`; read `CONFLUENCE_MCP_URL` (hosted Atlassian MCP). When `CONN_CONFLUENCE_ENABLED=true` **and** a token + URL are present, drive the hosted server over JSON-RPC (SSE-framed `data:` parse, `Mcp-Session-Id` handling, Bearer auth) exactly as `JiraConnector._mcp_rpc` does. Otherwise keep returning the in-memory sample — never raise when disabled.
- Discover the live page-create / page-update / search tool names by `tools/list` first (the hosted server's exposed set varies by token scope), with a candidate-name list like Jira's `_EDIT_TOOL_CANDIDATES`.
- `health()` reports `healthy` only when enabled + URL + token; `degraded` with a clear message when enabled but missing creds; `disabled` otherwise. `summary()` keeps the `confluence_links` schema so `/overview` and `/architecture` keep rendering.
- Keep all real writes behind the existing gates: `CONN_CONFLUENCE_ENABLED` + `WORKFLOW_WRITES_ENABLED` (and, for docs sync, `DOCS_SYNC_ENABLED`). No live write path may fire from a disabled or dry-run connector. Reuse the deterministic mock page-id mint for dry-run so the Stage-14 docs-sync idempotency path still exercises end-to-end without a tenant.

### 23b. Confluence content collections + overlap chains

The current connector sample has 4 pages. Expand it (and add a backing Mongo collection so the wiki/overview can query, not just the connector summary) so each environment/program area has its own Confluence *space* with multiple pages, and **every page cross-references the Jira/Archer/Mongo keys that already exist** in the seed:

- Spaces modeled on the existing keys: `COMP` (Compliance-Runbooks), `ARCH` (Architecture-RFCs), `SRE` (SRE-Guides), plus new `SEC` (Security-Standards) and `DATA` (Data-Governance).
- Each page carries `matched_on.ticket_refs` / `matched_on.projects` / `matched_on.users` / labels that resolve to **real** rows in `epics`, `audit_findings`, `work_items`, `pr_records`, and the GitHub/ServiceNow/Snowflake/Archer connector samples.
- Add a `confluence_pages` collection (seed file) and add it to `KNOWN_COLLECTIONS` so Ask Data / Wrangler / mongo_query can traverse it read-only. The connector's `_sample()` becomes a thin view over the same canonical page set (single source of truth — define rows once).

### 23c. Cross-system seed enrichment (lively dashboards)

Grow the seeded collections and connector samples so dashboards are dense and consistent. **Every new row must reference an existing or co-added key** (no orphans):

- **Jira (`epics`, `work_items`, `tickets`):** add more epics/stories/sub-tasks spanning the 5 program areas, with statuses spread across the board (backlog → in-progress → blocked → done) and realistic due dates so `/overview` attention rules (overdue / due-soon / blocked) actually light up.
- **GitHub commits/PRs connector sample:** more commits/PRs tagged to the new epics, with a mix of `passing`/`failing`/`pending` checks so the topology weak-spot highlighting has signal.
- **ServiceNow connector sample:** change requests / incidents referencing the same `epic_key`s (change → epic overlap).
- **Snowflake connector sample:** evidence queries / result-set metadata referencing `finding_id` / control ids (evidence → finding overlap).
- **Archer connector sample:** risk findings / control assessments that are the *source* of the Jira epics (finding → epic overlap), sharing `finding_id`/`epic_key`.
- **AWS connector sample:** resources/accounts referenced by the SRE/infra epics.
- Keep all connector samples as their existing schema (`schema:` field unchanged) so `/overview`, `/architecture`, and `/hub` keep rendering without front-end changes. Enrichment is *more rows with consistent keys*, not new shapes.

### 23d. Process documentation (teachable environment)

Author docs that explain the *processes the dashboard executes*, aimed at coworkers learning deep agents / agentic workflows / MCP. These land in the in-app `/docs` wiki (system-of-record `docs` collection, via `mongo-seed/14-docs.js` additions or `scripts/import_docs.py`) **and** as Markdown under `docs/`:

- **"How the overlap chain works"** — risk finding → epic → commit/PR → change → evidence → Confluence page, with the exact collection/connector each hop reads and the key that joins them.
- **"Agentic workflows in this stack"** — the LangGraph workflow (`mcp/workflow/`), the standup cockpit (Stage 20), the docs-sync HITL apply gate (Stage 14), and the deep-agent platform (Stage 21) — what each does, where the human-in-the-loop gate is, and which MCP tools they call.
- **"MCP in this stack"** — agent ↔ MCP JSON-RPC, the connector registry, live vs. mock connectors, and how to enable a live connector (the `CONN_*_ENABLED` + token pattern), using Confluence as the worked example.
- Cross-link these from the existing `/architecture` and `/docs` surfaces; tag them so the (now-live-capable) Confluence sync can mirror the public ones into the `COMP`/`ARCH` spaces (dry-run by default).

### 23e. Env surface (additions — defaulted, live off by default)

| Var | Default | Required | Stage | Notes |
| --- | --- | --- | --- | --- |
| `CONFLUENCE_TOKEN` | — | no | 23 | Primary Confluence/Atlassian MCP bearer token (user-facing name). Falls back to `CONFLUENCE_MCP_TOKEN` if unset. Prefer a gitignored secret; never commit a value. |
| `CONFLUENCE_MCP_URL` | — | no | 23 | Hosted Atlassian MCP endpoint (e.g. `https://mcp.atlassian.com/v1/mcp/authv2`). Reused from existing surface. |
| `CONN_CONFLUENCE_ENABLED` | `false` | no | 23 | Master enable for the live Confluence path (existing flag; documented here for the live gate). |
| `CONFLUENCE_WRITES_ENABLED` | `false` | no | 23 | Extra write guardrail mirroring `JIRA_WRITES_ENABLED`; live page create/update requires this + `CONN_CONFLUENCE_ENABLED` + `WORKFLOW_WRITES_ENABLED`. |

> Update `.env.example` (and the gitignored `.env.local`) in the same change that adds these. `CONFLUENCE_BASE_URL` and `DOCS_CONFLUENCE_SPACE` already exist (Stage 14) — do not duplicate; reference them.

### Task checklist — Stage 23

- [x] **S23.conn.1 — Promote Confluence connector to live-capable (Stage-16 parity)**
  - Files: `mcp/connectors/confluence.py`, `.env.example`, `.env.local`.
  - Done when: connector reads `CONFLUENCE_TOKEN` (fallback `CONFLUENCE_MCP_TOKEN`) + `CONFLUENCE_MCP_URL`; drives the hosted Atlassian MCP over SSE-framed JSON-RPC with session handling when `CONN_CONFLUENCE_ENABLED=true` + creds present; `tools/list`-based tool-name discovery with a candidate list; `health()` reports healthy/degraded/disabled correctly; disabled/dry-run path never raises and still mints deterministic mock page ids; `python3 -m py_compile mcp/connectors/confluence.py` clean.
  - Depends on: nothing (mirrors `mcp/connectors/jira.py`).

- [x] **S23.conn.2 — Live writes behind explicit gates**
  - Files: `mcp/connectors/confluence.py`, `mcp/docs_sync.py`.
  - Done when: live `confluence_create_page`/`confluence_update_page` fire only when `CONN_CONFLUENCE_ENABLED` + `WORKFLOW_WRITES_ENABLED` + `CONFLUENCE_WRITES_ENABLED`; otherwise a dry-run plan is returned and logged to `doc_sync_log`; Stage-14 docs-sync idempotency (store `confluence_page_id`, update next time) still works against the mock.
  - Depends on: S23.conn.1.

- [x] **S23.data.1 — `confluence_pages` collection + canonical page set**
  - Files: `mongo-seed/15-confluence-pages.js` (new), `mcp/db.py` (`KNOWN_COLLECTIONS`), `mcp/connectors/confluence.py`.
  - Done when: a `confluence_pages` seed defines multi-page spaces (`COMP`/`ARCH`/`SRE`/`SEC`/`DATA`), each page's `matched_on` references real `epics`/`audit_findings`/`work_items` keys; `confluence_pages` is added to `KNOWN_COLLECTIONS` (read-only traversable by Ask Data/Wrangler); the connector `_sample()` reads from the same canonical set (no divergent copies).
  - Depends on: S23.conn.1.

- [x] **S23.data.2 — Jira/Mongo enrichment (more tickets, consistent keys, lit-up attention)**
  - Files: `mongo-seed/12-scale-data.js` (or a new `16-enrichment.js`), `mongo-seed/02-tickets.js`, `mongo-seed/04-epics.js`, `mongo-seed/06-work_items.js`, `mongo-seed/13-due-dates.js`.
  - Done when: more epics/stories/sub-tasks across 5 program areas with spread statuses + realistic due dates; `/overview` attention rules (overdue/due-soon/blocked) actually populate; no orphan keys (every `epic_key`/`ticket_ref`/`finding_id` resolves).
  - Depends on: nothing (additive seed rows).

- [x] **S23.data.3 — Connector-sample enrichment with cross-system overlap**
  - Files: `mcp/connectors/{github,servicenow,snowflake,archer,aws}.py`.
  - Done when: each connector's sample gains rows referencing the same `epic_key`/`finding_id`/`ticket_refs` as the Jira/Confluence/Mongo data, forming the full chain `archer finding → epic → commit/PR → servicenow change → snowflake evidence → confluence page`; schemas (`schema:` field) unchanged so `/overview`,`/architecture`,`/hub` render unchanged; checks-state mix retained for topology signal; `python3 -m py_compile` clean on each.
  - Depends on: S23.data.1, S23.data.2.

- [x] **S23.docs.1 — Process documentation: overlap chain + agentic workflows + MCP**
  - Files: `docs/overlap-chain.md` (new), `docs/agentic-workflows.md` (new), `docs/mcp-in-this-stack.md` (new), `mongo-seed/14-docs.js` (or `scripts/import_docs.py`).
  - Done when: three teaching docs exist under `docs/` and are imported into the in-app `docs` wiki collection; each names the exact collection/connector + join key for every hop; the MCP doc uses the Confluence live-enable as its worked example; docs are tagged `public` where appropriate so dry-run sync mirrors them.
  - Depends on: S23.data.1, S23.data.3 (so docs reference the real keys).

- [x] **S23.docs.2 — Cross-link teaching docs from Architecture + Docs surfaces**
  - Files: `web/src/routes/architecture.tsx`, `web/src/routes/docs.tsx` (or shared nav/data only — additive).
  - Done when: `/architecture` and `/docs` link to the new teaching docs; no regression to existing routes; `cd web && npm run build` clean.
  - Depends on: S23.docs.1.

- [x] **S23.verify.1 — End-to-end verification (disabled + live-gated)**
  - Files: `scripts/` (extend an existing smoke or add `scripts/smoke_confluence.sh`), `progress.md`.
  - Done when: with Confluence disabled, `/overview` + `/architecture` + Ask Data over `confluence_pages` render and the connector reports `disabled` without raising; the overlap chain is traceable by querying one `epic_key` across `audit_findings`/`epics`/`work_items`/`pr_records`/`confluence_pages` + connector samples and getting consistent hits; with `CONN_CONFLUENCE_ENABLED` + creds (operator-supplied), `health()` reports `healthy` and a dry-run page plan is produced; results logged in `progress.md`. `python3 -m py_compile mcp/*.py mcp/connectors/*.py` + `cd web && npm run build` clean.
  - Depends on: S23.conn.2, S23.data.3, S23.docs.2.

---

## Stage 24 — Standup reference rail: foldable Epics + Templates panels

> **Validated against the Stage-21 architecture change (2026-05-26).** Stage 21 adopted the LangChain `deepagents` SDK (`docs/deep_agent_platform.md`) and upgraded the MCP service to LangChain 1.x (`S21.upgrade.1`, done). Impact on Stage 24: **none of the epics-read tasks change** (S24.api.1/epics.1/verify.1 are plain `epics`-collection reads + UI). The **only** intersection is the templates prompt library — under the new architecture the `atlassian_agent` generates the Jira/Confluence artifacts these prompts describe, and agents consume prompts as **context packs** (`S21.context.1`). So `S24.templates.api.1`'s backend store is now the **shared source of truth** for both the panel preview and the Stage-21 agent context packs; keep it a plain data store (no binding to the old hand-rolled deep-agent). No tasks added/removed; `S24.templates.api.1` gains a convergence constraint. The LangChain 1.x bump does not affect Stage 24 (no Stage-24 code imports langchain/langgraph).

**Goal:** Give the `/standup` view two always-at-hand reference panels so a scrum master can drive backlog work *while the team is talking* without leaving the page or hunting through Jira/Confluence. Both panels are **collapsible** (fold to a one-line header) so they cost almost no vertical space when idle but expand to full reference detail on click. They surface the on-hand context a facilitator needs to quickly create stories, assign work, reclassify a story, add tags, or kick off ticket/doc generation.

This stage is **read-first and additive**. It does not introduce a new write path: Epics is a live read of the existing `epics` collection, the Templates **fields table** is a read of per-epic customized fields, and the Templates **prompt library** renders Markdown templates the MCP server already (or will) own. Editing of either is explicitly deferred to a future stage; the data shapes and component seams below are chosen so editing can be layered on without a rewrite.

> **Placement.** `/standup` today (`web/src/routes/standup.tsx`) is a two-column layout: Explorer-dominant main area + a right `aside` carrying the chat/approval tray and the collapsed Jira Configuration bubble. The two new panels live in that same `aside` (or a dedicated reference column on xl screens), above or below the Jira Configuration bubble, each as a self-contained collapsible card. Reuse the existing collapse idiom already used for the Jira Configuration bubble (`configOpen` + `ChevronDown/ChevronUp`), not a new dependency.

### 24a. Epics panel — active-epic quick reference

A foldable card titled **Epics** (collapsed shows count + a one-line summary, e.g. "4 active epics"). Expanded, it lists the **currently active epics** (those whose `status` is not done/archived — reuse the `overview_summary` "active" notion). Each epic row shows the most important fields a facilitator references mid-standup to create/triage stories:

- `epic_key` / `jira_key` (with a deep link to Jira via `JIRA_BASE_URL`)
- `title`
- `program_area`
- `status` and `priority` (as badges)
- `tags[]` / `regulation_refs[]` / `db_platform_combos[]` (the classification chips used when reclassifying or tagging a story)
- `ticket_refs[]` count and `finding_ids[]` linkage (so a facilitator can see what's already attached)

The list is compact and scannable; rows can expand to show the full field set. Selecting an epic row should set the standup context (e.g. emit an `explorer.selection`-style hint / set local selected-epic state) so the chat agent's "follow up on X" phrasing can resolve against it — wire this to the existing selection plumbing if cheap, otherwise leave a clearly-marked seam. **Read-only**; no inline edit.

### 24b. Templates panel — fields table + prompt library

A second foldable card titled **Templates**, containing **two** sub-sections:

**1. Per-epic customized-fields table.** A table showing, for each (active) epic, the customized/critical fields and their current values — the same fields a facilitator would set when creating or reclassifying a story under that epic (e.g. `program_area`, `priority`, `status`, `regulation_refs`, `db_platform_combos`, default labels/tags, epic link). This is a **read-only** projection now; it must be built so that **cells become editable in a future stage** — i.e. render values through a small presentational cell component and key the table off a typed field-spec list, not hardcoded `<td>`s, so an editor can drop in later. Add a visible "Editing coming soon" affordance.

**2. Prompt/template library — dropdown + Markdown viewport.** A window split into (a) a **dropdown-selectable list** of named Markdown templates/prompts and (b) a **Markdown rendering viewport** showing the selected template. These are the prompts the **MCP server** uses, executed via `tool_calls`, to generate **Jira tickets** and **Confluence docs**. Selecting a name renders its Markdown body using the existing `Markdown` component (`react-markdown` + `remark-gfm` + `rehype-highlight`, already used by `/docs` and `/architecture`) — **do not** add a new Markdown dependency. This is **read-only/preview** now but must be built for **future editability** (textarea-editor seam like `/docs`), so source the template bodies from a backend store/tool rather than inlining them in the component.

> **Architecture note (2026-05-26, Stage-21 deepagents adoption).** Stage 21 now builds the agent platform on the LangChain `deepagents` SDK (see `docs/deep_agent_platform.md`), where the **`atlassian_agent`** generates exactly these Jira tickets / Confluence docs and the agents load prompts/templates/schemas as **context packs** (`S21.context.1`). To avoid two divergent copies of the same generation prompts, the Stage-24 `standup_templates` backend store **is** that shared source of truth: the panel previews it, and the Stage-21 agents' context packs read from it. This is the only Stage-24 task touched by the architecture change — see the convergence notes on `S24.templates.api.1` below. It does not change what Stage 24 builds (still a read-only preview over a backend-owned template store); it fixes *where the store lives* so Stage 21 can consume it without a rewrite.

### 24c. Backend / data shape

Reuse existing infrastructure; add only thin read tools/proxies:

- **Epics + fields:** read the `epics` collection. Prefer reusing `overview_summary`'s epic roll-up or `get_rows("epics")` via `validate_spec`; expose to the web layer as a `/api/standup/epics` proxy (or extend an existing standup proxy) returning active epics with the 24a fields. No new write path.
- **Templates fields table:** derive the per-epic customized-field projection from the same epics read; define the field-spec (which keys are "customized/critical") in one typed place shared by backend shape and frontend table so the future editor and this view agree.
- **Prompt/template library:** the templates are MCP-owned prompts for ticket/doc generation. Source them where the standup agent already reasons about templates (`mcp/standup_agent.py` builds deterministic Jira story-template context; Stage-9 carries a workflow Jira template, `mcp/workflow/pr_template.py`). Expose a `standup_templates` MCP tool (list `{name, kind: jira|confluence, body_md}`) + a `/api/standup/templates` proxy. Bodies live in a backend-owned location (a `standup_templates` seed/collection or a templates module) so a future stage can make them editable and so `tool_calls` execute the same source the UI previews. **No live ticket/doc writes in this stage** — preview only; generation stays behind the existing dry-run/HITL gates. **(Stage-21 convergence:** this backend-owned store is the single source of truth the Stage-21 `atlassian_agent`/`standup_agent` context packs (`S21.context.1`) read from — keep it a plain data store, not logic bound to the old hand-rolled deep-agent, so either runtime can consume it.)

### 24d. Env surface (proposed)

| Var | Default | Required | Stage | Notes |
| --- | --- | --- | --- | --- |
| `STANDUP_EPICS_ACTIVE_ONLY` | `true` | no | 24 | Epics panel lists only non-done/archived epics; `false` shows all |
| `STANDUP_EPICS_LIMIT` | `25` | no | 24 | Max epics returned to the Epics panel / fields table |
| `STANDUP_TEMPLATES_ENABLED` | `true` | no | 24 | Master gate for the Templates prompt-library panel |

### 24e. Verification intent

1. `/standup` shows an **Epics** card and a **Templates** card; both are collapsed by default (one-line header) and expand on click without pushing the Explorer off-screen.
2. The Epics panel lists the active epics from the `epics` collection with key/title/program_area/status/priority/tags and Jira deep links; a done/archived epic is excluded (or shown only when `STANDUP_EPICS_ACTIVE_ONLY=false`).
3. The Templates **fields table** renders per-epic customized fields and values, read-only, with an "editing coming soon" affordance and a cell/field-spec structure ready for a future editor.
4. The Templates **prompt library** offers a dropdown of named templates and renders the selected one as Markdown in the viewport using the existing `Markdown` component; switching selection re-renders.
5. The template bodies are sourced from the backend (the same source `tool_calls` would execute), not inlined in the component.
6. No new external writes; existing dry-run/HITL gates untouched. Build/checks pass: `python3 -m py_compile mcp/*.py web/*.py`; `cd web && npm run build` clean.

### Task checklist — Stage 24

- [x] **S24.api.1 — Active-epics read proxy for the standup panels** ✅ DONE
  - Files: `mcp/server.py` (or reuse `overview_summary`/`get_rows`), `web/main.py`, `web/src/lib/queries.ts`, `web/src/lib/types.ts`.
  - Done when: a `/api/standup/epics` proxy returns active epics (gated by `STANDUP_EPICS_ACTIVE_ONLY`/`STANDUP_EPICS_LIMIT`) with `epic_key`/`jira_key`/`title`/`program_area`/`status`/`priority`/`tags`/`regulation_refs`/`db_platform_combos`/`ticket_refs`/`finding_ids`; a typed `StandupEpic` interface + `useStandupEpics()` hook exist (no `any`); errors surfaced; read-only (no write tool added). `python3 -m py_compile` + `cd web && npm run build` clean.
  - Depends on: S20.ui.1.

- [x] **S24.epics.1 — Foldable Epics reference card** ✅ DONE
  - Files: `web/src/routes/standup.tsx`, optional `web/src/components/standup-epics.tsx`.
  - Done when: a collapsible **Epics** card (reusing the existing `configOpen`/Chevron collapse idiom — no new dep) sits in the standup `aside`; collapsed header shows active count; expanded shows scannable rows with key/title/program_area/status+priority badges and classification chips (tags/regulation_refs/db_platform_combos), Jira deep links via `JIRA_BASE_URL`, and per-row expand for the full field set; selecting a row sets local selected-epic context (wired to existing selection plumbing if cheap, else a marked seam). Read-only. Build clean.
  - Depends on: S24.api.1.

- [x] **S24.templates.api.1 — `standup_templates` MCP tool + proxy (ticket/doc prompt library)** ✅ DONE
  - Files: `mcp/standup_templates.py` (new) or extend `mcp/standup_agent.py`, `mcp/server.py`, `web/main.py`, `web/src/lib/queries.ts`, `web/src/lib/types.ts`.
  - Done when: a `standup_templates` MCP tool lists `{name, kind: "jira"|"confluence", body_md, description?}` from a backend-owned source (seed/collection or templates module) — the *same* source that `tool_calls` use to generate Jira tickets/Confluence docs; a `/api/standup/templates` proxy + typed `useStandupTemplates()` hook expose it; gated by `STANDUP_TEMPLATES_ENABLED`. Bodies are not inlined in the frontend. **Future-edit seam:** structure leaves room for an upsert tool later (note it in code/comments); no edit endpoint added now. Build/compile clean.
  - **Stage-21 convergence (architecture note):** make this store the shared source of truth the deepagents `atlassian_agent`/`standup_agent` context packs (`S21.context.1`) will read — keep it a plain data store (collection/module) decoupled from any specific agent runtime (neither the old hand-rolled deep-agent nor deepagents), so both the panel and the agents consume one copy. Do **not** duplicate the prompts into agent code.
  - Depends on: S20.agent.1.

- [x] **S24.templates.ui.1 — Templates card: customized-fields table + prompt-library viewport** ✅ DONE
  - Files: `web/src/routes/standup.tsx`, optional `web/src/components/standup-templates.tsx`.
  - Done when: a collapsible **Templates** card holds two sub-sections — (1) a per-epic **customized-fields table** rendered from a typed field-spec list through a presentational cell component (read-only, with an "editing coming soon" affordance, structured so a future editor drops in), and (2) a **prompt library** with a dropdown of template names (from `useStandupTemplates`) and a Markdown viewport rendering the selected template via the existing `Markdown` component (no new Markdown dep); switching selection re-renders; editor seam noted for a future stage. Build clean.
  - Depends on: S24.api.1, S24.templates.api.1.

- [x] **S24.future.1 — Document the deferred editability path (feature improvement)** ✅ DONE
  - Files: `docs/standup.md`, `IMPLEMENT.md`.
  - Done when: `docs/standup.md` records that the Epics fields table and the template prompt library are **read-only in Stage 24** and captures the planned future feature — inline-editable epic fields and editable Markdown templates (textarea-editor like `/docs`, backed by an upsert MCP tool + audited write-layer) — including the component/data seams left in place so the editor can be added without a rewrite.
  - Depends on: S24.epics.1, S24.templates.ui.1.

- [x] **S24.verify.1 — Build + standup reference-rail review** ✅ DONE
  - Files: `IMPLEMENT.md`, `progress.md`.
  - Done when: `python3 -m py_compile mcp/*.py web/*.py` and `cd web && npm run build` pass; manual review confirms both cards are collapsed by default, expand without displacing the Explorer, the Epics panel lists active epics with the 24a fields + Jira links, the fields table is read-only with the future-edit affordance, and the prompt library dropdown renders each template as Markdown; results logged in `progress.md`.
  - Depends on: S24.epics.1, S24.templates.ui.1.

---

## Stage 26 — Chat runtime visibility and admin-selectable model routing (planned)

**Goal:** Make the focused `/chat` page transparent about which runtime is answering: the public agent endpoint, upstream provider, model, and any active Deep-Agent/subagent model assignments. This is initially read-only runtime visibility for every authenticated user. Later, admins should be able to select/modify provider/model routing safely through the auth system rather than editing env vars or code.

### Task checklist — Stage 26

- [x] **S26.chat-runtime.1 — Show active endpoint/provider/model for agent and subagents** ✅ DONE
  - Files: `agent/main.py`, `mcp/llm.py`, `mcp/deep_agent/profiles.py`, `mcp/deep_agent/runtime.py`, `mcp/server.py`, `web/main.py`, `web/src/components/chat-assistant.tsx`, `web/src/lib/queries.ts`, `web/src/lib/types.ts`, `docs/clients.md`, `IMPLEMENT.md`, `progress.md`.
  - Done when: `/chat` displays a compact runtime panel/banner showing the active OpenAI-compatible endpoint (redacted host/path only; no keys), provider, and model used by the main agent; the same panel lists Deep-Agent/subagent roles/profiles that may be delegated to (orchestrator, atlassian, mongo, github, servicenow, aws, audit, docs, standup) with each role's configured provider/model/endpoint and whether it inherits the upstream default; secrets/API keys are never exposed; values come from a server-side `/api/chat/runtime` proxy backed by an MCP/runtime-info tool, not from frontend env constants; unauthenticated users cannot read it; normal authenticated users get read-only visibility; admins with `canAdminAuth` (or a future narrower capability) see a clearly-marked future-control affordance for selecting/modifying provider/model, but no mutation endpoint is added in this first task; the design notes how a later task can persist admin overrides safely (validated allowlist, audit log, rollback, no secrets in JSON payloads); `python3 -m py_compile agent/*.py mcp/*.py web/*.py` and `cd web && npm run build` pass.
  - Git handoff: before coding, `git pull --ff-only origin main`; stage by explicit path only (`git add agent/main.py mcp/llm.py mcp/deep_agent/profiles.py mcp/deep_agent/runtime.py mcp/server.py web/main.py web/src/components/chat-assistant.tsx web/src/lib/queries.ts web/src/lib/types.ts docs/clients.md IMPLEMENT.md progress.md` as applicable — never `git add -A`/`.`/`commit -a`); inspect `git status --short` and `git diff --cached --stat`; commit with a focused message such as `feat(S26): show chat runtime model routing`; push the feature branch; merge via PR or fast-forward only after review/smokes pass.
  - Depends on: S21.profile.1, S21.orch.1, S22.chat.3.

---

## Stage 27 — Standup view layout: widenable chat + main-section reference grid (planned)

**Goal:** Improve the `/standup` cockpit layout for screen-share readability. Make the live chat panel **widenable** so a presenter can expand it for easier viewing during standup, move the **Epics** and **Approvals viewport** cards out of the narrow right rail and into the main left section as grid items, and keep the **Jira Configuration / tool trace** card rendered as a consistent grid item rather than something that disappears or destabilizes the grid when toggled.

### Task checklist — Stage 27

- [x] **S27.layout.1 — Widenable chat + Epics/Approvals in main grid + stable config/trace grid item** ✅ DONE
  - Files: `web/src/routes/standup.tsx`, `web/src/components/standup-chat.tsx`, `docs/standup.md`, `CHANGELOG.md`, `IMPLEMENT.md`, `progress.md`.
  - Done when: the standup chat panel has an expand/widen affordance (header toggle) that lets a presenter widen it (e.g. span the full row / both grid columns) and collapse it back to the rail width, with the chat remaining fully functional (send, presence, summarize) in both states; the **Epics** and **Approvals viewport** cards render in the main left section as grid items rather than only in the right `23rem` aside; the **Jira Configuration / tool trace** card always renders as a grid item and its show/hide toggle does not break the surrounding grid layout; the existing RBAC/dry-run gates, proposal Save/Submit/Reject flow, and websocket trace wiring are unchanged in behavior; `cd web && npm run build` passes.
  - Git handoff: before coding, confirm `git status` and `git log --oneline -1`; stage by explicit path only (`git add web/src/routes/standup.tsx web/src/components/standup-chat.tsx docs/standup.md CHANGELOG.md IMPLEMENT.md progress.md` — never `git add -A`/`.`/`commit -a`); inspect `git status --short` and `git diff --cached --stat`; commit with a focused message such as `feat(S27): widenable standup chat + main-grid reference rail`; push the feature branch; merge via PR or fast-forward only after review/build pass.
  - Depends on: S24.templates.ui.1, S25.approver.1.

---

## Stage 28 — Standup multi-session chat + "AI" action-item extraction (planned)

**Goal:** Make `/standup` support more than one conversation and turn freeform chat into approver-ready action items. Two parts: (1) a **New chat** control plus a session switcher so a team can start a fresh standup conversation and flip between past ones (each is an independent persisted session in the existing `StandupStore`); and (2) an **"AI"** button that reads the active session and extracts a structured brief — who said what (user identity), referenced tickets and known config items, related JSON/config records for those items (e.g. an AWS config item pulled through the existing connector tools), and any actions the user described — then emits **suggested action items phrased for the approver**, e.g. *"Create a new Jira ticket under Epic XYZ based on its relationship to ZYX"*, *"Update ticket ABC-12 to Blocked per the user's suggestion in chat"*, or *"Add a comment to ABC-1234 with the AWS config pulled for that resource."* The suggestions land in the existing dry-run **Approvals viewport** as proposals — nothing is applied without the Stage-25 approver Submit gate.

> **Reuse, don't reinvent.** Sessions are already keyed by arbitrary `session_id` in `web/standup_store.py::_ensure_session` (a "new chat" is a new id; "switch" loads another snapshot via the existing `GET /api/standup/sessions/{id}/snapshot`). Extraction already exists in `mcp/standup_agent.py::run_standup_summarize` / the `standup_summarize` MCP tool, which emits `summary`/`decisions`/`risks_blockers`/`follow_ups`/`service_associations`/`proposals` (incl. `new_jira_work` and `jira_edit`). The "AI" button is an **enrichment + dedicated UI affordance** over that pipeline, not a new agent. Config/JSON enrichment should call existing connector MCP tools (Jira/AWS/etc.) rather than adding new write paths. Keep everything dry-run; approval stays the Stage-25 path.

### Task checklist — Stage 28

- [ ] **S28.chat-sessions.1 — New-chat button + session switcher on `/standup`**
  - Files: `web/standup_ws.py` (add a `GET /api/standup/sessions` list endpoint), `web/standup_store.py` (add a `list_sessions()` returning id/title/sprint/updated_at/message+proposal counts; no schema change to stored sessions), `web/src/components/standup-chat.tsx` (accept a controlled `sessionId` + `onSessionChange`; reconnect the websocket when it changes), `web/src/routes/standup.tsx` (own `sessionId` state, render a **New chat** button + a switcher listing existing sessions), `web/src/lib/queries.ts`, `web/src/lib/types.ts` (session-list hook/types — append only), `docs/standup.md`, `CHANGELOG.md`, `IMPLEMENT.md`, `progress.md`.
  - Done when: `/standup` shows a **New chat** affordance that starts a fresh session (new generated `session_id`, e.g. `standup-<short-uuid>`, joined over the websocket) and a switcher (dropdown/list) of existing sessions sourced from a new authenticated `GET /api/standup/sessions` proxy; selecting one tears down and re-opens the chat websocket against that `session_id` and loads its snapshot (messages, proposals, agent runs) without a full page reload; the Approvals viewport, Epics, Templates, and trace panels all reflect the currently-selected session; presence is per-session (already true in `StandupConnectionManager`); the default `daily-standup` session still works for existing links; non-authenticated users are rejected exactly as today; `python3 -m py_compile web/*.py` and `cd web && npm run build` pass.
  - Git handoff: before coding, `git pull --ff-only origin main` (or confirm HEAD), then stage by explicit path only (`git add web/standup_ws.py web/standup_store.py web/src/components/standup-chat.tsx web/src/routes/standup.tsx web/src/lib/queries.ts web/src/lib/types.ts docs/standup.md CHANGELOG.md IMPLEMENT.md progress.md` — never `git add -A`/`.`/`commit -a`); inspect `git status --short` and `git diff --cached --stat`; commit with a focused message such as `feat(S28): multi-session standup chat + switcher`; push and merge via PR or fast-forward only after build/py-compile pass.
  - Depends on: S20.auth.1.

- [ ] **S28.ai-extract.1 — "AI" extraction button → enriched approver action items**
  - Files: `mcp/standup_agent.py` (extend the extraction to surface a structured `extraction` block: participants/user identity, referenced tickets, detected config items, and any user-requested actions; phrase `proposals[].title`/`rationale` as approver-facing imperatives), `mcp/server.py` (extend the existing `standup_summarize` tool args/result or add a sibling `standup_extract` tool — additive, disjoint region), `web/standup_ws.py` (handle an `agent.extract` websocket event distinct from `agent.summarize`, optionally calling connector tools to pull related config JSON for detected items), `web/standup_store.py` (persist the extraction brief alongside the agent run; no breaking change to proposal shape), `web/src/components/standup-chat.tsx` + `web/src/routes/standup.tsx` (an **"AI"** button that triggers `agent.extract`, and a panel that renders the extraction brief above the resulting proposals), `web/src/lib/types.ts`, `docs/standup.md`, `CHANGELOG.md`, `IMPLEMENT.md`, `progress.md`.
  - Done when: clicking **"AI"** on the active session runs an extraction that returns, in one structured result, (a) the participants/user identity referenced, (b) tickets/Jira keys mentioned, (c) known config items referenced and any related config/JSON pulled for them through **existing read-only connector tools** (e.g. AWS/Jira), and (d) the actions the user described or requested; the result is rendered as a readable brief and is turned into dry-run **proposals** whose titles/rationales read like approver instructions (the three example phrasings in the Goal must be representative of what is generated when the chat warrants them); every proposal remains `status:"proposed"`, `dry_run:true`, carries `source_message_ids`, and is staged/validated through the same Stage-16 path as `standup_summarize` (no live writes); the approver still Saves/Submits via the Stage-25 gates; when the model is unsupported or extraction fails, the handler degrades to a persisted dry-run placeholder exactly like `_handle_agent_summarize` does today; secrets/credentials from connectors are never echoed into proposals or the brief; `python3 -m py_compile mcp/*.py web/*.py` and `cd web && npm run build` pass; `scripts/smoke_standup_ws.py` still passes and is extended to cover an `agent.extract` round-trip producing at least one approver-phrased dry-run proposal.
  - Git handoff: before coding, confirm HEAD; stage by explicit path only (`git add mcp/standup_agent.py mcp/server.py web/standup_ws.py web/standup_store.py web/src/components/standup-chat.tsx web/src/routes/standup.tsx web/src/lib/types.ts scripts/smoke_standup_ws.py docs/standup.md CHANGELOG.md IMPLEMENT.md progress.md` — never `git add -A`/`.`/`commit -a`); inspect `git status --short` and `git diff --cached --stat`; commit with a focused message such as `feat(S28): AI extraction button for approver action items`; push and merge via PR or fast-forward only after smokes/build pass.
  - Depends on: S28.chat-sessions.1, S20.approval.1, S25.approver.1.

---

## Stage 29 — Standup approvals lifecycle + broader production apply + admin gate toggle (planned)

**Goal:** Close the gaps that surfaced while using the Approvals viewport: (1) proposals **accumulate forever** with no way to clear/dismiss decided ones, (2) only `jira_edit` proposals actually reach a live-write path — `new_jira_work` (create) and "add comment" are approved but **never executed** — and (3) the only way to leave dry-run today is editing env vars + restarting. This stage adds proposal **lifecycle controls** (dismiss/archive, optional clear-session), **extends the production apply path** to ticket creation and comments through existing connector tools, and adds an **admin-only UI toggle** for the web-side dry-run gate with an audit trail.

> **Gate architecture constraint (verified 2026-05-26).** The three gates are not read the same way. `STANDUP_DRY_RUN_ONLY` is read **per request in the web process** (`web/standup_ws.py::_apply_proposal_submit` via `_env_bool`), so it can be flipped live in-process. But `WORKFLOW_WRITES_ENABLED` (`mcp/db.py:71`) and `JIRA_WRITES_ENABLED` (`mcp/jira_staging.py:30`) are bound to **module constants at MCP import time** — a web-side button cannot change them; they still require their own env config + an MCP restart. The admin toggle in S29.gate-toggle.1 therefore controls **only** the web-side `STANDUP_DRY_RUN_ONLY` and must clearly state that the MCP-side gates remain independent. Treat that as the safety interlock: even with dry-run off, nothing writes unless the MCP process was itself started with the write gates enabled.

### Task checklist — Stage 29

- [ ] **S29.lifecycle.1 — Dismiss/archive decided proposals + clear-session control**
  - Files: `web/standup_store.py` (add `set_proposal_archived()`/`dismiss_proposal()` and an optional `clear_session_proposals()`; archived/dismissed proposals are retained in the store with a flag, not hard-deleted, for audit), `web/standup_ws.py` (handle `proposal.dismiss` / `proposal.archive` websocket events, approver-gated like `proposal.edit`), `web/src/components/standup-chat.tsx` (controls type adds `dismiss`/`archive`), `web/src/routes/standup.tsx` (per-proposal Dismiss/Archive control + a viewport filter that hides decided/archived by default with a "show all" toggle), `docs/standup.md`, `CHANGELOG.md`, `IMPLEMENT.md`, `progress.md`.
  - Done when: an approver can dismiss or archive a proposal so it leaves the active viewport without being lost from the audit record; the viewport defaults to showing only `proposed` (open) items with a toggle to reveal decided/archived; non-approvers cannot dismiss/archive (tooltip-disabled, same pattern as Save/Submit); archived state survives refresh/reconnect (persisted) and is reflected over the websocket to other participants; no existing proposal field is removed; `python3 -m py_compile web/*.py` and `cd web && npm run build` pass; `scripts/smoke_standup_ws.py` extended to cover a dismiss round-trip.
  - Git handoff: before coding, confirm HEAD; stage by explicit path only (`git add web/standup_store.py web/standup_ws.py web/src/components/standup-chat.tsx web/src/routes/standup.tsx docs/standup.md CHANGELOG.md IMPLEMENT.md progress.md` — never `git add -A`/`.`/`commit -a`); inspect `git status --short` + `git diff --cached --stat`; commit `feat(S29): standup approvals lifecycle (dismiss/archive/clear)`; push + merge via PR/fast-forward after smokes/build pass.
  - Depends on: S25.approver.1.

- [ ] **S29.apply.1 — Extend production apply beyond `jira_edit` (create + comment)**
  - Files: `mcp/connectors/jira.py` (wire a live create path behind `jira_create_issue` — currently a `MOCK-123` stub — and a live comment path, both gated by `JIRA_WRITES_ENABLED` + a `live_writer`, mirroring `_live_update_issue`/`apply_staged`), `mcp/jira_staging.py` (support staging/validating `new_jira_work` create payloads and comment actions, not just field edits), `web/standup_ws.py` (`_jira_edits_from_proposal` + `_apply_proposal_submit` must recognize `new_jira_work` and a `jira_comment` proposal type and route them to the right apply tool instead of the current "no supported production apply tool" branch), `docs/standup.md`, `CHANGELOG.md`, `IMPLEMENT.md`, `progress.md`, `.env.example` if a new gate is added.
  - Done when: a `new_jira_work` proposal, when approved with all live gates open, calls a real create tool (hosted Atlassian MCP) and records the created key; a comment proposal posts a real comment with the same gating; both remain dry-run plans when any gate is closed (no external write), exactly like the edit path; validation rejects creates/comments that target disallowed fields or missing context; secrets are never echoed; `python3 -m py_compile mcp/*.py web/*.py` passes and the existing Jira staging/apply smokes still pass; a dry-run apply plan for a create + a comment is shown to be produced without writing when gates are closed.
  - Git handoff: before coding, confirm HEAD; stage by explicit path only (`git add mcp/connectors/jira.py mcp/jira_staging.py web/standup_ws.py docs/standup.md CHANGELOG.md IMPLEMENT.md progress.md .env.example` as applicable — never `git add -A`/`.`/`commit -a`); inspect `git status --short` + `git diff --cached --stat`; commit `feat(S29): production apply for Jira create + comment proposals`; push + merge via PR/fast-forward after smokes pass.
  - Depends on: S25.approver.1, S16 (Jira staging tools).

- [x] **S29.gate-toggle.1 — Admin-only toggle for the web-side dry-run gate (audited)** ✅ DONE (web-side; lifecycle.1/apply.1 still open)
  - Files: `web/standup_ws.py` or `web/main.py` (add an admin-gated `GET`/`POST /api/standup/gates` proxy: GET returns the current effective gate state — web `STANDUP_DRY_RUN_ONLY` plus the read-only MCP-side `WORKFLOW_WRITES_ENABLED`/`JIRA_WRITES_ENABLED` as reported by an MCP info call or `.env` echo; POST flips the in-process `STANDUP_DRY_RUN_ONLY` only, guarded by `Depends(require_capability(Capability.CAN_ADMIN_AUTH))` and written to the auth audit log), `web/src/lib/queries.ts` + `web/src/lib/types.ts` (gates hook/types — append only), `web/src/routes/standup.tsx` (in the **Jira Configuration / tool trace** card, render the current gate state and, for `canAdminAuth` users only, a toggle/switch that flips dry-run with a clear warning; non-admins see read-only state), `docs/standup.md`, `CHANGELOG.md`, `IMPLEMENT.md`, `progress.md`.
  - Done when: an admin (`canAdminAuth`) sees a toggle in the config/trace card that flips the web process's `STANDUP_DRY_RUN_ONLY` at runtime (no restart) and the change is reflected in the next Submit's gating and audited (actor + before/after + timestamp); the UI **explicitly states** that `WORKFLOW_WRITES_ENABLED` and `JIRA_WRITES_ENABLED` are MCP-side, independent, and not changed by this toggle (so flipping dry-run alone does not enable live writes unless MCP was started with those gates on); non-admins get a 403 from the POST endpoint and a read-only display in the UI; unauthenticated requests get 401; the effective-state GET never leaks secrets; `python3 -m py_compile web/*.py` and `cd web && npm run build` pass.
  - Git handoff: before coding, confirm HEAD; stage by explicit path only (`git add web/standup_ws.py web/main.py web/src/lib/queries.ts web/src/lib/types.ts web/src/routes/standup.tsx docs/standup.md CHANGELOG.md IMPLEMENT.md progress.md` as applicable — never `git add -A`/`.`/`commit -a`); inspect `git status --short` + `git diff --cached --stat`; commit `feat(S29): admin toggle for standup dry-run gate`; push + merge via PR/fast-forward after build passes.
  - Depends on: S19 (auth/RBAC, `canAdminAuth`), S25.approver.1.

---

## Stage 30 — Enforce multi-agent worktree & commit hygiene (mechanism, not prose)

**Goal:** Stop the recurring collisions where a second agent works the main tree instead of its own worktree (COORDINATION.md rule 2) and where broad `git add -A`/`commit -a` sweeps another agent's unstaged edits into the wrong commit (Incident 2). Prose has not held — these rules live only in `COORDINATION.md` and depend on each agent reading, remembering, and self-policing. This stage moves enforcement to **mechanism**: hooks that block or warn at the moment of the action.

> **Two-agent reality (2026-05-26): the enforcement must catch BOTH agents.** This repo is worked by a Claude Code session *and* a separate **PiAgent** session. Claude Code hooks in `.claude/settings.json` (`SessionStart`/`PreToolUse`) only fire for Claude Code — they will not intercept PiAgent's git commands. Therefore the cross-agent backstop **must** be a **git-level hook** (`pre-commit`, wired via a tracked `core.hooksPath` so it's shared, not a local `.git/hooks/` file), because git runs it no matter which agent commits. The Claude Code hooks are the early, agent-specific layer; the git hook is the layer that also binds PiAgent. Neither layer may break PiAgent's normal flow (PLANTMUX tmux pane management is unrelated and must be left alone).

### Task checklist — Stage 30

- [ ] **S30.cc-hooks.1 — Claude Code SessionStart + PreToolUse guards** ✅ see implementation note
  - Files: `.claude/settings.json` (add a `hooks` block — additive; do not disturb the existing `permissions`), `.claude/hooks/session-start.sh`, `.claude/hooks/block-broad-git.sh`, `COORDINATION.md` (document the hooks), `IMPLEMENT.md`, `progress.md`.
  - Done when: a `SessionStart` (matcher `startup`+`resume`) hook injects `additionalContext` reminding the agent of the worktree rule + "stage by name, never `git add -A`/`.`/`commit -a`" and to read COORDINATION.md before editing shared files; a `PreToolUse` hook on `Bash` denies (via `hookSpecificOutput.permissionDecision:"deny"` with a `permissionDecisionReason`) any command matching `git add -A` / `git add .` / `git add --all` / `git commit -a`/`-am`, telling the agent to stage explicit paths; hooks use `${CLAUDE_PROJECT_DIR}` paths and the scripts are executable; the deny matcher does not false-trip on legitimate `git add <path>`; hooks are inert/harmless for PiAgent (they simply never fire); `bash -n` on both scripts passes and a manual stdin test (`echo '{"tool_input":{"command":"git add -A"}}' | .claude/hooks/block-broad-git.sh`) returns a deny decision while `git add web/x.tsx` returns allow/exit 0.
  - Git handoff: stage by explicit path only (`git add .claude/settings.json .claude/hooks/session-start.sh .claude/hooks/block-broad-git.sh COORDINATION.md IMPLEMENT.md progress.md`); inspect `git status --short` + `git diff --cached --stat`; commit `chore(S30): claude code worktree/commit hygiene hooks`.
  - Depends on: —.

- [x] **S30.git-hook.1 — Cross-agent `pre-commit` guard (binds PiAgent too)** ✅ DONE
  - Files: `scripts/git-hooks/pre-commit` (new, tracked + executable), `scripts/install-git-hooks.sh` (sets `git config core.hooksPath scripts/git-hooks`), `COORDINATION.md` (one-time install step), `CHANGELOG.md` (dev-tooling note), `IMPLEMENT.md`, `progress.md`.
  - Done: tracked `pre-commit` hook shared via `core.hooksPath` now runs for **any** committer including PiAgent. It checks staged `*.py` with `python3 -m py_compile` and staged `web/**/*.ts(x)` with `cd web && npx tsc -b --noEmit` when `web/node_modules` is present; otherwise it is a no-op for irrelevant staged files. `scripts/install-git-hooks.sh` installs the hook per clone/worktree and documents the expected `core.hooksPath=scripts/git-hooks` state. Both Claude Code and PiAgent must install/use this shared hook; Claude's local `.claude/` hooks remain the early layer, but the git hook is the cross-agent backstop.
  - Verified: installer sets `core.hooksPath`; `bash -n scripts/git-hooks/pre-commit scripts/install-git-hooks.sh`; clean staged-set hook run passes; direct `cd web && npx tsc -b --noEmit` passes.
  - Depends on: —.

- [ ] **S30.allowlist.1 — Tighten the git permission allowlist + claim convenience (optional polish)**
  - Files: `.claude/settings.local.json` (replace blanket `Bash(git add *)` with explicit-path patterns + rely on the deny hook; keep other git grants), optionally a `/claim-stage` helper that creates `../wt-S<n>` from HEAD + updates the COORDINATION.md owner table + drops a lock, `COORDINATION.md`, `IMPLEMENT.md`, `progress.md`.
  - Done when: the broad `Bash(git add *)` grant no longer silently permits `git add -A` (the deny hook is the guard, but the allowlist should not pre-authorize the dangerous form); legitimate stage-by-name still works without new prompts where reasonable; if the claim helper is added, one command creates the worktree + records ownership; no change degrades PiAgent.
  - Depends on: S30.cc-hooks.1.

---

## Stage 31 — Standup incoming-tickets triage bubble: unassigned Jira intake + workflow match + connector-hub enrichment (planned)

**Goal:** Give the scrum master and team an at-a-glance, screen-share-friendly **"Incoming tickets"** bubble in the `/standup` main section that surfaces **new Jira tickets routed to our team that are not yet assigned or addressed**, and for each one does the analysis a human would otherwise do by hand: (1) decide whether the request maps to a known **on-boarding** or **consultation** workflow, and (2) pull the entities named in the request — AWS account, RDS DB instance, AWS region, app-team id, users, emails, distribution lists — and look each up across the **Compliance Hub connector modules** (AWS, ServiceNow, GitHub, Mongo, etc.) to show recent activity/context. The card renders this enrichment inline so the team can decide handling/assignment fast and, when a workflow clearly applies, kick it off (dry-run proposal) immediately. This is **read-only intake + analysis + a dry-run proposal**; it never auto-assigns or writes without going through the existing Stage-25 approver Submit gate.

> **Reuse, don't reinvent.** Unassigned intake is a Jira *read* — use the existing `jira_search_issues`/`jira_list_issues` connector tools (filter to the team's project/queue where `assignee` is empty and status is new/triage), not a new write path. Entity extraction should extend the existing `parse_links_mentions` (`web/standup_store.py:88`) / `standup_agent` extraction rather than adding a second parser; add the new entity kinds (aws_account, rds_instance, aws_region, app_team_id, user, email, distribution_list) there. Workflow matching reuses the Stage-24 `standup_templates` material + the onboarding/consultation workflow definitions already in `workflow/` (do not duplicate the prompts). Connector lookups call **existing read-only connector tools** (`aws_list_rds_instances`/`aws_describe_instance`, `servicenow_search_findings`/`servicenow_get_change_request`, `github_search_repos`/`github_list_checks`, `mongo_query`/`mongo_aggregate`, and `connector_summary`/`connector_health`) — no new write tools. The bubble lives in the standup main `<section>` (`web/src/routes/standup.tsx:363`) as a **conditional grid item** that only renders when there is at least one unassigned incoming ticket, consistent with the Stage-27 grid layout. All proposals remain `status:"proposed"`, `dry_run:true`, gated by Stage-25/Stage-29 apply paths.

### Task checklist — Stage 31

- [x] **S31.intake.1 — Backend: unassigned incoming-ticket scan + entity extraction + workflow match + connector enrichment** ✅ DONE
  - Files: `mcp/standup_intake.py` (new — the intake/analysis workflow), `mcp/server.py` (add a read-only `standup_incoming_tickets` MCP tool: def + dispatch + handler, additive/disjoint region), `web/standup_store.py` (extend `parse_links_mentions` with the new entity kinds: aws_account, rds_instance, aws_region, app_team_id, user, email, distribution_list — append-only, no change to existing return keys), `web/main.py` (add an authenticated `GET /api/standup/incoming` proxy), `web/src/lib/types.ts`, `web/src/lib/queries.ts` (incoming-tickets hook/types — append only), `docs/standup.md`, `CHANGELOG.md`, `IMPLEMENT.md`, `progress.md`.
  - Done when: a read-only `standup_incoming_tickets` tool returns, per unassigned/unaddressed ticket routed to the team (sourced via existing `jira_search_issues`/`jira_list_issues` reads — assignee empty + new/triage status, capped by a limit), a structured record containing: the ticket key/summary/reporter/created; the **extracted entities** (aws_account, rds_instance, aws_region, app_team_id, users, emails, distribution_lists); a **workflow match** result (which on-boarding/consultation workflow applies, or none, with a confidence/rationale) computed against the existing `standup_templates`/`workflow/` definitions; and a **connector-hub enrichment** block keyed by those entities — recent activity/info pulled **only through existing read-only connector tools** (AWS RDS describe, ServiceNow findings/changes, GitHub repos/checks, Mongo queries) with each source's health/availability surfaced; secrets/credentials from connectors are never echoed; when a connector is disabled or returns nothing, the record degrades gracefully (clearly "no data"/"connector disabled") rather than erroring; `GET /api/standup/incoming` proxies it for authenticated users (read context only); `python3 -m py_compile mcp/*.py web/*.py` and `cd web && npm run build` pass.
  - Git handoff: before coding, `git pull --ff-only origin main` (or confirm HEAD); stage by explicit path only (`git add mcp/standup_intake.py mcp/server.py web/standup_store.py web/main.py web/src/lib/types.ts web/src/lib/queries.ts docs/standup.md CHANGELOG.md IMPLEMENT.md progress.md` — never `git add -A`/`.`/`commit -a`); inspect `git status --short` + `git diff --cached --stat`; commit `feat(S31): incoming-ticket intake scan + workflow match + connector enrichment`; push the feature branch; merge via PR or fast-forward only after build/py-compile pass.
  - Depends on: S20.explorer.1 (Jira reads), S23 (connector enrichment data), S24.templates.ui.1 (workflow/template material).

- [x] **S31.bubble.1 — Standup cockpit: conditional "Incoming tickets" bubble with enrichment + one-click workflow kickoff (dry-run)** ✅ DONE
  - Files: `web/src/routes/standup.tsx` (render a conditional grid item in the main `<section>` that appears only when `incoming.length > 0`), `web/src/components/standup-incoming.tsx` (new — the bubble: per-ticket card showing extracted entities, matched workflow + rationale, and the connector-hub enrichment with per-source badges), `web/src/lib/queries.ts`/`types.ts` (consume the S31.intake.1 hook), `docs/standup.md`, `CHANGELOG.md`, `IMPLEMENT.md`, `progress.md`.
  - Done when: when the team has ≥1 unassigned incoming ticket, a clearly-labeled **Incoming tickets** card renders in the standup main section (grid item consistent with the Stage-27 layout) and is **absent** (no empty card) when there are none; each ticket shows its key/summary/reporter, the extracted entities as chips, the matched on-boarding/consultation workflow (or "no match") with rationale, and a compact connector-hub enrichment panel (recent activity per source with health/availability indicators, secrets never shown); the scrum master can, for a clearly-matched ticket, trigger that workflow as a **dry-run proposal** that lands in the existing Approvals viewport (no assignment/write happens without the Stage-25 approver Submit gate); non-approvers can view the bubble and trigger a dry-run proposal but cannot apply it; the card polls/refreshes with the rest of the cockpit and does not destabilize the grid when it appears/disappears; `cd web && npm run build` passes.
  - Git handoff: before coding, confirm HEAD; stage by explicit path only (`git add web/src/routes/standup.tsx web/src/components/standup-incoming.tsx web/src/lib/queries.ts web/src/lib/types.ts docs/standup.md CHANGELOG.md IMPLEMENT.md progress.md` — never `git add -A`/`.`/`commit -a`); inspect `git status --short` + `git diff --cached --stat`; commit `feat(S31): incoming-tickets cockpit bubble + workflow kickoff`; push + merge via PR/fast-forward after build passes.
  - Depends on: S31.intake.1, S25.approver.1 (dry-run proposal → approver Submit gate), S27.layout.1 (main-grid layout).

---

## Stage 32 — LDAP directory module + identity-driven hub enrichment (planned)

**Goal:** Add an **enterprise directory (LDAP) module** that performs user lookups — email, full name, assigned groups, manager, reporting hierarchy, and position/title — modeled on a live `python-ldap` integration bound by an **application service-account ID**, but **faked** for this POC: the module exposes exactly the entities a successful `python-ldap` bind + search would return, against a seeded fixture of **200 fake users** carrying the common LDAP attributes of a typical enterprise (so a later swap to a live server is a drop-in). On top of that, add **identity-driven enrichment**: given a resolved user, search the **Compliance Hub connector modules** for that person's recent activity, infer their **team(s)** from directory groups + activity, and pull team-context (e.g. Confluence space overviews/technical pages, ServiceNow assignment groups) so an assistant or workflow can guide the user or route to the correct workflow. The first consumer is **Stage 31** (a ticket reporter / named user in an incoming ticket gets resolved + enriched); the module is general so future workflows reuse it.

> **Reuse, don't reinvent — and respect the existing auth privacy boundary.** Stage 19 already has a minimal `DirectoryAdapter` (`web/auth_ldap.py`, S19.ldap.1) whose `lookup_user` is deliberately capped at 6 keys for **RBAC** (username/display_name/email/groups/source/lookup_ts). **Do not widen that contract.** The richer fields here (manager, hierarchy, position, DLs, department, location, employee id) are an **enrichment** concern, so they live in a **new, separate MCP-side directory module** (`mcp/connectors/ldap.py`, connector-shaped: `health`/`summary`/`tools`) used for context/enrichment, not for authorization. Group→team and activity lookups call **existing read-only connector tools** (`confluence_search_pages`/`confluence_get_page`, `servicenow_search_findings`/`servicenow_get_change_request`, `github_search_repos`, `mongo_query`) — no new write paths. The faked module must shape its return like real `python-ldap` results (DN, attribute dict) so swapping in a live bind later changes only the adapter internals.

### Task checklist — Stage 32

- [x] **S32.ldap.1 — Faked python-ldap directory module + 200-user fixture with enterprise attributes** ✅ DONE
  - Files: `mcp/connectors/ldap.py` (new — connector-shaped directory module: an `LdapDirectory` with a faked-bind/`search` surface returning `python-ldap`-shaped results — DN + attribute dict — behind a clean method API `lookup_user`/`lookup_groups`/`lookup_manager`/`lookup_hierarchy`/`lookup_position`; app-ID/service-account bind modeled via env, no live network in POC mode), `mcp/connectors/__init__.py` (register the connector in `_CONNECTOR_CLASSES`), `scripts/seed_ldap_users.py` (new — generate + persist 200 fake users), a fixture data file (`mcp/fixtures/ldap_users.json` or Mongo `directory_users`), `mcp/server.py` (read-only MCP tools `ldap_lookup_user` + `ldap_lookup_manager_chain` — def + dispatch + handler, additive/disjoint region), `.env.example` (LDAP module env: `LDAP_ENABLED`, `LDAP_MODE=fixture|live`, `LDAP_APP_ID`, `LDAP_BIND_DN`, `LDAP_BASE_DN`, `LDAP_SERVER_URI`, `LDAP_USERS_FILE` — defaulted, fixture mode on), `docs/ldap-directory.md` (new), `CHANGELOG.md`, `IMPLEMENT.md`, `progress.md`.
  - Done when: 200 fake users are seeded, each with the **common enterprise LDAP attributes** — `cn`, `displayName`, `givenName`/`sn`, `mail`, `sAMAccountName`/`uid`, `userPrincipalName`, `title` (position), `department`, `division`, `manager` (DN ref forming a real reporting hierarchy, not random), `directReports`, `memberOf` (groups, incl. team + distribution-list groups), `telephoneNumber`, `physicalDeliveryOfficeName`/`l` (location), `employeeID`, `employeeType`, `distinguishedName` — with internally-consistent manager→report chains (e.g. ~3–4 management tiers) and groups that map to plausible teams; `LdapDirectory` (fixture mode) resolves a user by email/uid/DN and returns the `python-ldap`-shaped result, plus typed helpers for groups/manager/hierarchy/position; `ldap_lookup_user` and `ldap_lookup_manager_chain` MCP tools return that data **without secrets** (no bind password, no raw service-account creds ever echoed); the connector reports `health`/`summary` like the others and is **off-by-default-safe** (disabled → clear "directory disabled" rather than error); the live-LDAP path is stubbed with the interface + the `python-ldap` call sites marked TODO so a real bind drops in without touching callers; `python3 -m py_compile mcp/*.py scripts/seed_ldap_users.py` passes and a fixture round-trip (lookup a seeded user → manager chain resolves to the top) is demonstrated.
  - Git handoff: before coding, `git pull --ff-only origin main` (or confirm HEAD); stage by explicit path only (`git add mcp/connectors/ldap.py mcp/connectors/__init__.py scripts/seed_ldap_users.py mcp/fixtures/ldap_users.json mcp/server.py .env.example docs/ldap-directory.md CHANGELOG.md IMPLEMENT.md progress.md` as applicable — never `git add -A`/`.`/`commit -a`); inspect `git status --short` + `git diff --cached --stat`; commit `feat(S32): faked python-ldap directory module + 200-user fixture`; push the feature branch; merge via PR or fast-forward only after py-compile + fixture round-trip pass.
  - Depends on: S19.ldap.1 (existing minimal adapter — kept separate), S9/S23 (connector framework).

- [x] **S32.enrich.1 — Identity-driven hub enrichment: team inference + activity/context lookup** ✅ DONE
  - Files: `mcp/identity_enrichment.py` (new — given a resolved directory user, infer team(s) from `memberOf` groups + recent activity, then gather context), `mcp/server.py` (read-only MCP tool `identity_enrichment` — def + dispatch + handler, additive/disjoint region), `web/main.py` (authenticated `GET /api/identity/{user}/enrichment` proxy), `web/src/lib/types.ts`, `web/src/lib/queries.ts` (enrichment hook/types — append only), `docs/ldap-directory.md`, `CHANGELOG.md`, `IMPLEMENT.md`, `progress.md`.
  - Done when: `identity_enrichment` accepts a user identity (email/uid), resolves them via `S32.ldap.1`, infers their **team(s)** from directory groups (+ corroborating activity), and returns a structured enrichment block: the user's directory summary (name/title/manager/team — no secrets); **recent activity** across **existing read-only connector tools** (e.g. ServiceNow assignment-group records, GitHub authored PRs/repos, Mongo ticket/finding ownership); and **team context** (e.g. the team's Confluence space overview + key technical pages via `confluence_search_pages`/`confluence_get_page`, ServiceNow assignment group) intended to guide assistance or workflow routing; every connector source reports availability and degrades to "no data"/"connector disabled" instead of erroring; no credentials/secrets are ever echoed; `GET /api/identity/{user}/enrichment` proxies it for authenticated users (read context only); `python3 -m py_compile mcp/*.py web/*.py` and `cd web && npm run build` pass.
  - Git handoff: before coding, confirm HEAD; stage by explicit path only (`git add mcp/identity_enrichment.py mcp/server.py web/main.py web/src/lib/types.ts web/src/lib/queries.ts docs/ldap-directory.md CHANGELOG.md IMPLEMENT.md progress.md` — never `git add -A`/`.`/`commit -a`); inspect `git status --short` + `git diff --cached --stat`; commit `feat(S32): identity-driven hub enrichment (team + activity + context)`; push + merge via PR/fast-forward after build/py-compile pass.
  - Depends on: S32.ldap.1, S23 (connector enrichment data).

- [x] **S32.s31.1 — Wire identity enrichment into the Stage 31 incoming-tickets bubble** ✅ DONE
  - Files: `mcp/standup_intake.py` (S31 backend — resolve each incoming ticket's reporter + any extracted `user`/`email`/`distribution_list` entities through `identity_enrichment`, attaching the directory/team/context block to the per-ticket record), `web/src/components/standup-incoming.tsx` (S31 UI — render the resolved reporter's team/manager/title + a compact "who & their team" context panel alongside the existing entity/workflow/connector enrichment), `docs/standup.md`, `docs/ldap-directory.md`, `CHANGELOG.md`, `IMPLEMENT.md`, `progress.md`.
  - Done when: an incoming ticket in the Stage-31 bubble shows, for its reporter (and any user/DL entities in the request), the resolved directory identity (name/title/manager/team — no secrets) and the team-context enrichment, so the scrum master can see *who* asked, *what team* they're on, and *relevant team docs/activity* to route or assist; the enrichment is read-only and degrades gracefully when the directory or a connector is disabled; nothing about this path assigns or writes outside the existing Stage-25 dry-run/approver gate; `python3 -m py_compile mcp/*.py` and `cd web && npm run build` pass.
  - Git handoff: before coding, confirm HEAD; stage by explicit path only (`git add mcp/standup_intake.py web/src/components/standup-incoming.tsx docs/standup.md docs/ldap-directory.md CHANGELOG.md IMPLEMENT.md progress.md` — never `git add -A`/`.`/`commit -a`); inspect `git status --short` + `git diff --cached --stat`; commit `feat(S32): identity enrichment in the Stage 31 incoming-tickets bubble`; push + merge via PR/fast-forward after build passes.
  - Depends on: S32.enrich.1, S31.intake.1, S31.bubble.1.

- [x] **S32.github-history.1 — Use identity to list GitHub repo history and map repos to applications** ✅ DONE
  - Files: `mcp/identity_enrichment.py` (extend enrichment to derive GitHub identities from LDAP email/uid and query GitHub history), `mcp/connectors/github.py` (add/read-only helper if needed for commits/events by author), `mcp/server.py` (tool schema/dispatch updates if a dedicated read-only `github_user_history` tool is added), `web/src/lib/types.ts`, `web/src/components/standup-incoming.tsx` (render repo/app hints when present), `docs/ldap-directory.md`, `CHANGELOG.md`, `IMPLEMENT.md`, `progress.md`.
  - Done when: identity enrichment uses the resolved user's email/uid to check GitHub history for commits or other repo interactions via existing/read-only GitHub connector data first (no writes, no token/secret echo); returns a compact list of repositories the user has interacted with (repo name, interaction kind such as commit/PR/check, most recent timestamp when known, evidence count); maps those repos to applications/environments using the internal app environment data available in the stack (e.g. Mongo app/team/environment records or connector summaries) and includes `application`, `environment`, `team`, and confidence/rationale when a mapping is found; when mapping data is missing, listing the repos alone is accepted as the first slice and the response clearly marks app mapping as `unknown`; disabled/missing GitHub data degrades to `connector disabled`/`no data` instead of failing; Stage-31 incoming-ticket identity context can show the repo list/app hints for the reporter or named users; `python3 -m py_compile mcp/*.py` and `cd web && npm run build` pass.
  - Git handoff: before coding, confirm HEAD; stage by explicit path only (`git add mcp/identity_enrichment.py mcp/connectors/github.py mcp/server.py web/src/lib/types.ts web/src/components/standup-incoming.tsx docs/ldap-directory.md CHANGELOG.md IMPLEMENT.md progress.md` as applicable — never `git add -A`/`.`/`commit -a`); inspect `git status --short` + `git diff --cached --stat`; commit `feat(S32): map identity GitHub history to applications`; push + merge via PR/fast-forward after build/py-compile pass.
  - Depends on: S32.enrich.1, S9/S23 GitHub connector data, internal app environment records.

---

## Stage 33 — Standup chat composer pinned to the viewport bottom (planned)

**Goal:** On `/standup`, the chat **text input must stay aligned to the bottom of the browser window and remain on-screen without scrolling** — so standup attendees keep their eyes on the main viewport with the scrum master while still being able to type at any time. Today the chat lives in an `<aside>` grid column (`web/src/routes/standup.tsx:702`) and the composer (`<form>` at `web/src/components/standup-chat.tsx:715`) is the last child of the card; on tall content / smaller viewports the input can fall below the fold and require scrolling to reach. Make the composer always reachable by making the chat column a viewport-anchored, internally-scrolling region: the message list scrolls inside the card while the header + composer stay fixed, with the composer pinned to the bottom of the visible viewport.

> **Reuse, don't reinvent — and don't regress Stage-27.** The chat card is already a flex column (`flex min-h-0 flex-1 flex-col`) with an internally-scrolling message list (`min-h-0 flex-1 overflow-y-auto`, `standup-chat.tsx:681`) and the composer as the trailing flex child — so the bones are right; the fix is making the chat **column height track the viewport** and stick. Approach: make the `<aside>` (or the chat card) `sticky` to the top with a viewport-derived height (e.g. `sticky top-[<header offset>] h-[calc(100vh-<offset>)]`) so the card fills the visible window and its trailing composer sits at the bottom edge, the list scrolling between. Keep the Stage-27 **Widen/Collapse** toggle working in both states and the `min-h-0`/`overflow` chain intact (don't reintroduce a double scrollbar). CSS/layout only — no change to chat send/presence/websocket logic.

### Task checklist — Stage 33

- [x] **S33.chat-bottom.1 — Pin the standup chat composer to the viewport bottom** ✅ DONE
  - Files: `web/src/routes/standup.tsx` (make the chat `<aside>`/column viewport-anchored — `sticky` + `h-[calc(100vh-…)]` so it tracks the visible window), `web/src/components/standup-chat.tsx` (ensure the card fills its column and the composer is the pinned trailing element with the message list as the only scroll region), `docs/standup.md`, `CHANGELOG.md`, `IMPLEMENT.md`, `progress.md`.
  - Done: the chat `<aside>` is now `xl:sticky xl:top-5 xl:h-[calc(100vh-2.5rem)] xl:self-start` so the chat column tracks the visible window; the chat `Card` keeps its flex-column + internally-scrolling message list (`min-h-0 flex-1 overflow-y-auto`) and trailing `<form>` composer, with `xl:min-h-0` added so it fills the fixed-height column rather than forcing a 22rem floor — the composer now sits at the bottom edge of the viewport while history scrolls inside the card. The Stage-27 Widen/Collapse toggle is unaffected (it changes the grid column width, not the sticky behavior); below `xl` the prior flow layout is retained. Layout/CSS only — chat send/presence/summarize/websocket logic untouched; `cd web && npm run build` passes (tsc + vite).
  - Git handoff: before coding, `git pull --ff-only origin main` (or confirm HEAD); stage by explicit path only (`git add web/src/routes/standup.tsx web/src/components/standup-chat.tsx docs/standup.md CHANGELOG.md IMPLEMENT.md progress.md` — never `git add -A`/`.`/`commit -a`); inspect `git status --short` + `git diff --cached --stat`; commit `feat(S33): pin standup chat composer to viewport bottom`; push + merge via PR/fast-forward after build passes.
  - Depends on: S20.chat.1 (chat panel), S27.layout.1 (widenable chat + main grid).

---

## Stage 34 — Frontend load performance: route code-splitting + vendor chunking

**Goal:** A fresh browser session was slow and "things weren't loading" because the SPA shipped as a **single ~1.7MB JS bundle** (no code-splitting): every route plus heavy libraries (React Flow, Recharts, react-markdown + highlight.js) had to download and parse before first paint, so a cold cache showed a blank screen and could stall. Split the bundle so the initial load pulls only the shell + landing route.

### Task checklist — Stage 34

- [x] **S34.codesplit.1 — Lazy-load routes + split vendor chunks** ✅ DONE
  - Files: `web/src/App.tsx` (route `React.lazy` + `Suspense`), `web/src/routes/overview.tsx` + `web/src/components/overview-trend-chart.tsx` (lazy chart), `web/vite.config.ts` (`manualChunks`), `CHANGELOG.md`, `IMPLEMENT.md`, `progress.md`.
  - Done: every route except the eager landing `Overview` is `React.lazy()` behind a `<Suspense>` fallback, so a fresh session downloads the shell + landing route instead of all routes. `vite.config.ts` `manualChunks` splits `vendor-react`, `vendor-flow` (`@xyflow/react`, ~54KB gz — only on `/architecture`), `vendor-charts` (`recharts`, ~109KB gz), `vendor-markdown` (`react-markdown`/`rehype-highlight`/`highlight.js`/`remark-gfm`, ~102KB gz — only on `/docs`,`/chat`), and `vendor-query`. Overview's single AreaChart is extracted to a lazy `overview-trend-chart` so recharts no longer blocks the landing paint. Result: the old single `index-*.js` (~1.7MB / ~500KB gz) is replaced by an `index` chunk of ~116KB gz plus on-demand route/vendor chunks; the build's chunk-size warning is gone. Behavior unchanged; `cd web && npm run build` passes.
  - Git handoff: stage by explicit path only (`git add web/src/App.tsx web/src/routes/overview.tsx web/src/components/overview-trend-chart.tsx web/vite.config.ts CHANGELOG.md IMPLEMENT.md progress.md` — never `git add -A`/`.`/`commit -a`); inspect `git status --short` + `git diff --cached --stat`; commit `perf(S34): route code-splitting + vendor chunking`; push + merge via PR/fast-forward after build passes.
  - Depends on: —.

---

## Stage 25 — Standup production approvals viewport

**Goal:** Promote the existing Standup dry-run approval tray into a restricted production-approval workflow for the named approver `simone.patel@lanGarland.com`. The regular `/standup` view can continue to stage proposals in dry-run form, but Simone's auth-resolved approver view should expose an approval viewport that shows **all staged changes**, lets the approver edit any necessary fields before finalizing, and then applies the approved production updates through the existing Stage-16/Stage-20 gates rather than stopping at dry-run validation.

### Task checklist — Stage 25

- [x] **S25.approver.1 — Simone standup approver view with editable production apply** ✅ DONE
  - Files: `web/auth.py`, `web/src/components/auth-provider.tsx`, `web/standup_ws.py`, `web/standup_store.py`, `web/src/routes/standup.tsx`, `docs/standup.md`, `scripts/smoke_standup_ws.py`, `IMPLEMENT.md`, `progress.md`.
  - Done when: the auth system grants `simone.patel@lanGarland.com` the standup approver capability (`canApproveStandupActions`) in a durable, auditable way (group/capability preferred over one-off UI checks; email matching case-insensitive); the approver's `/standup` view includes a distinct **Approvals** viewport listing every staged proposal/change for the session (new Jira work, Jira edits, links, Confluence/doc proposals when present) with status, source messages, rationale, validation result, and target service; every editable payload field needed by an approver can be changed inline before apply; **Save** persists the edited staged payload without applying; **Submit** revalidates the saved payload and then invokes the production apply path (`jira_apply_staged` and future equivalent connector apply tools) only when all live-write gates are explicitly enabled (`STANDUP_DRY_RUN_ONLY=false`, `JIRA_WRITES_ENABLED=true`, `WORKFLOW_WRITES_ENABLED=true`, plus any connector-specific gate); non-approvers can view only allowed read context and cannot save/submit; approvals record actor, timestamp, original payload, edited payload, validation result, apply result, and dry-run/live mode; rejected/failed applies remain recoverable and auditable; smoke coverage proves viewer forbidden, Simone save-only, Simone submit with dry-run gates still blocked, and Simone submit with test/live gates reaches the apply path; `python3 -m py_compile web/*.py scripts/smoke_standup_ws.py` and `cd web && npm run build` pass.
  - Git handoff: before coding, `git pull --ff-only origin main`; stage by explicit path only (`git add web/auth.py web/standup_ws.py web/standup_store.py web/src/components/auth-provider.tsx web/src/routes/standup.tsx docs/standup.md scripts/smoke_standup_ws.py IMPLEMENT.md progress.md` as applicable — never `git add -A`/`.`/`commit -a`); inspect `git status --short` and `git diff --cached --stat`; commit with a focused message such as `feat(S25): add standup production approvals viewport`; push the feature branch; merge via PR or fast-forward only after review/smokes pass.
  - Depends on: S20.approval.1, S20.auth.1, S24.templates.ui.1 (only if Confluence/doc template proposals are included in the first production viewport slice; Jira-only production apply may start earlier).

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
| `CONFLUENCE_TOKEN` | — | no | 23 | Primary Confluence/Atlassian MCP bearer token; falls back to `CONFLUENCE_MCP_TOKEN` |
| `CONFLUENCE_MCP_TOKEN` | — | no | 9 | Legacy/fallback Confluence MCP bearer token |
| `CONFLUENCE_WRITES_ENABLED` | `false` | no | 23 | Extra live Confluence write gate; also requires connector + workflow/docs gates |
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
| `STANDUP_EPICS_ACTIVE_ONLY` | `true` | no | 24 | Epics panel lists only non-done/archived epics; `false` shows all |
| `STANDUP_EPICS_LIMIT` | `25` | no | 24 | Max epics returned to the Epics panel / fields table |
| `STANDUP_TEMPLATES_ENABLED` | `true` | no | 24 | Master gate for the Templates prompt-library panel |
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

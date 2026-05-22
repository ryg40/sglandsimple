# Progress

## Status
**Stages 0–2, 4, 6–12, 13, 15–17 COMPLETE. Stage 3 transport/expose COMPLETE locally (manual external-client smoke pending). Stage 14 COMPLETE incl. docs-agent LangGraph HITL apply gate. Stage 18 architecture v2 mostly done (export/docs/verify remaining). Stage 19 auth/RBAC code complete with Basic-mode integrated verification green. Stage 20 standup substantial slice done (identity/proposals/agent context/trace done; approval/RBAC/full rebuilt-stack verify remaining). Stages 21–22 all TBD. Stage 5 SHELVED.**
Work branch: `main`; latest observed HEAD before current work: `39816e0` (`docs: add S19.logout.1 task + update progress/coordination for logout feature`).

## Session 2026-05-22 (pi agent) — S19 auth login hotfix

User reported web GUI login not working. Root cause had two parts:

1. **`perm/auth/users.json` missing** — the auth seed script (`web/auth_seed.py`) had never been run, so `/data/auth/users.json` didn't exist inside the container. Web logs showed `auth: users file not found: /data/auth/users.json` on every request.
2. **`auth_seed.py` not in Docker image** — `web/Dockerfile` only copied `main.py` and `auth.py`, but `auth.py` does `from auth_seed import verify_password` at runtime, causing `ModuleNotFoundError: No module named 'auth_seed'` on every login attempt (HTTP 500).

**Fix:**
- Ran `AUTH_BASIC_SEED_PASSWORD=changeme-poc AUTH_BASIC_USERS_FILE=./perm/auth/users.json python3 web/auth_seed.py` to generate the missing user credentials file (6 seeded users).
- Added `auth_seed.py` to the Dockerfile COPY line: `COPY main.py auth.py auth_seed.py ./`
- Rebuilt & restarted web container: `docker compose up --build -d web`
- Verified login works: `curl -u 'simone.patel@lanGarland.com:changeme-poc' http://localhost:5452/api/architecture` → 200

**Files changed:**
- `web/Dockerfile` — added `auth_seed.py` to COPY
- `perm/auth/users.json` — generated (gitignored, persisted via bind mount)

**Follow-up:** `AUTH_BASIC_SEED_PASSWORD` is currently unset in `.env`, so the seed script defaults to `changeme-poc` with a warning. Production deployments should set this to a real secret.

## Session 2026-05-22 (pi agent) — landing S13/S15/S19/S20 + worktree cleanup

Picked up handoff from previous multi-agent session. All co-mingled changes across S13, S15, S18, S19, S20 were disentangled and committed by stage.

**Commits landed (6):**
- `064af8d` feat(S15): ask_data deadline + batch notes + wrangler bulk projection + pipeline code view
- `fdd3c02` feat(S13): migrate hardcoded color literals to semantic tokens (6 components, ported from pi-stage13-15 worktree)
- `98850b3` feat(S19): web auth/RBAC — identity resolution, route guards, UI gating, actor audit
- `2a3e853` feat(S20): standup Jira cockpit — websocket chat, dry-run agent, session persistence
- `17553f3` docs: update IMPLEMENT.md + progress.md checkboxes
- `8ef52e8` docs: update COORDINATION.md

**S13 cleanup:** Ported 5 token-migration files from pi-stage13-15 worktree via direct copy (connection-bubble, hub-columns, relate-panel, workflow-stepper, hub). Workflow.tsx required surgical application — token changes only, preserving S19 auth gating (DisabledWithTooltip, useAuth).

**S19 audit.1 fix:** The parallel Claude agent's audit.1 task was incomplete — MCP-side functions accepted `actor` param but `web/main.py` never injected it. Fixed by: (1) guards store resolved user in `request.state.user`, (2) `_actor_from_request()` extracts it, (3) all 14 write endpoints now inject `actor` dict into MCP tool args.

**Worktree cleanup:**
- Removed 2 stale Claude worktrees (`.claude/worktrees/agent-*`) — content confirmed fully in main
- Removed pi-stage13-15 worktree + branch — S13 changes ported
- Removed 6 disposable subagent report files
- Pruned stale branch refs

**Build verification:** py_compile + npm run build both green. Merged to main and pushed.

## Session 2026-05-22 (docs-wiki agent) — S18/S19 doc tasks + Stage 5 shelved + coordination
- **S18.discovery.1 DONE** — `docs/architecture-inventory-template.md` (new): capture form for environments/accounts, AWS network detail (VPC/subnet/CIDR/SG), compute & data nodes (hostname/IP/instance_type/storage/retention/runbook_slug), integrations/edges (protocol/auth_mode/agentic_status), RISK→artifact flow checklist, and a known-unknowns table. All infra values `TBD`; field names align with the Stage-18 graph schema. Importable into the Docs Wiki.
- **S19.policy.1 DONE** — `docs/auth-rbac.md` (new): group→role→capability map, `/api/*` capability requirements (401 vs 403), SSO-prod / Basic-POC assumptions + all six `AUTH_MODE`s, seeded POC users, LDAP/auth-agent privacy boundary, and a non-blocking open-questions list.
- **Stage 5 (Copilot upstream) SHELVED** per user — `IMPLEMENT.md` header marked SHELVED + added to Out of scope; narrative retained for revival. Recorded in agent memory.
- **Coordination hardening** — `COORDINATION.md`: golden rule 7 (stage by name, never `git add -A`), new "IMPLEMENT.md commit protocol", and Incident 2 (commit `b171cd7` swept the S18/S19 checkbox flips). Both main-tree agents share branch `stage-14-docs-wiki`.
- Doc-only session; no code/build touched. Commits `5e7dd06` (docs) + `35a6e26` (coordination), cherry-picked to `main` this session.

## Stage 11 — Compliance command center: Overview page (DONE)
- **`overview_summary` MCP tool** (`mcp/overview.py`): reads `audit_findings`, `epics`, `work_items`, `pr_records` + the connector registry; evaluates six attention rules server-side (overdue, due_soon, prioritized, high_severity, blocked_pr, stalled); returns `{kpis, attention[], connectors[], tables{}, generated_at}` in one round-trip.
- **`GET /api/overview` proxy** (`web/main.py`): calls `overview_summary` via `_mcp_tool` + `_extract_json_block`.
- **Seed additions** (`mongo-seed/06-work_items.js`, `07-pr_records.js`, `13-due-dates.js`): due dates + staleness/check fixtures added so all attention rules have real data; applied via `scripts/reseed.sh`.
- **`useOverview()` query hook** (`web/src/lib/queries.ts`, `types.ts`): polls every 30 s; `placeholderData: (prev) => prev` prevents page blanking on refetch.
- **Overview SPA route** (`web/src/routes/overview.tsx`): 6 `StatCard` KPI row, full-width `AttentionPanel` (`web/src/components/attention-panel.tsx`), connector-health strip, 2×2 `MiniTable` grid (`web/src/components/mini-table.tsx`), retained activity trend.
- **Smoke test** (`scripts/smoke_overview.sh`): green — `/api/overview` returns all four sections; KPIs `{open_findings:4, active_epics:4, inflight_work_items:4, open_prs:2, connectors_healthy:1/8, attention:10}`; 10-item ranked attention list (overdue → due_soon → blocked_pr); `tools/list` returns 32 tools including `overview_summary`.
- **Env vars** (all optional, all defaulted): `OVERVIEW_DUE_SOON_DAYS=14`, `OVERVIEW_STALE_DAYS=7`, `OVERVIEW_ATTENTION_LIMIT=10`, `OVERVIEW_TABLE_ROWS=5`, `OVERVIEW_POLL_MS=30000`.

## Stage 12 — Domain-rich connector data + cross-system topology (DONE)
- **Mock data** (`S12.mock.*`, `S12.field.*`): every connector's `summary()` now returns a `schema` hint + domain-shaped `sample_data`:
  - AWS — multi-service inventory (RDS/S3/CloudTrail/KMS/ELB/IAM) with account/region/resource-id/service/status; one prod RDS row has `audit_logging:"disabled"` (a weak-spot).
  - Jira — active sprint + canonical issue fields (`fields.*`) grouped by epic; flagged/neglected tickets.
  - ServiceNow — canonical `incident` + `change_request` tables (impact/urgency/priority, cmdb_ci, sla_due, cab_required, etc.); P1 incident + high-risk change.
  - GitHub — commits per project auto-tagged to epics + `checks_state` (one failing).
  - Confluence — related articles with canonical content shape + `matched_on` relatedness.
  - Snowflake/MongoDB/Archer — schema hints + filled-out rows.
- **Topology** (`S12.topo.*`): `mcp/topology.py` builds `{nodes,edges,concerns,zones}`; `topology_graph` MCP tool + `GET /api/topology` proxy. 8 nodes / 11 edges / 6 ranked concerns.
- **Architecture page** (`S12.web.1/2`): new `/architecture` route (sidebar entry) — React Flow (`@xyflow/react`) interactive diagram, zoned layout, teal edges (red+animated for concerns), pan/zoom/minimap/controls, node tooltips, right-rail clickable concern list deep-linking to the Hub.
- **Hub** (`S12.web.3`): schema-keyed column registry (`web/src/components/hub-columns.tsx`) — AWS + ServiceNow now render (were empty), Jira sprint header + epic grouping, GitHub tags + checks badge, Confluence `matched_on` chips.
- **Persistence** (`S12.persist.1`): Mongo moved to a host bind mount `./perm/db:/data/db` (named volume removed); `./perm/` gitignored; `scripts/reseed.sh` re-applies seeds (init scripts only run on first empty-dir init). **Proven**: a marker row survived `docker compose down && docker compose up --build -d`.

## Stage 13 — Fleet-Dispatch design system (DONE, one follow-up)
- `web/src/index.css` tokens remapped to brand palette: navy `#1A1446` canvas (dark = default/headline look), amber `#FFD000` primary, teal `#06748C` secondary, white text; charts lead amber+teal; destructive/success kept for meaning.
- Font → Roboto, self-hosted via `@fontsource/roboto` (offline-safe), imported in `main.tsx`.
- **Follow-up `S13.cleanup.1` (partial)**: status-color literals remain in `hub-columns.tsx`/`hub.tsx`/`workflow-stepper.tsx` by design (red/green semantics); fuller token migration of non-semantic blues/purples is open.

## Stage 14 — Docs Wiki + Confluence sync (COMPLETE)
- **Data model (S14.model.1, DONE)**: `mongo-seed/14-docs.js` seeds `docs`/`doc_revisions`/`doc_sync_log` (incl. one deliberately-stale doc to exercise lifecycle). `mcp/db.py` gained docs system-of-record helpers — `docs_list/get/upsert/set_flags/search`, `doc_sync_log_append/recent`, `docs_set_confluence_id` — all auditing via `_audit(source="docs_*")`. Flags validated against the 14b enums (`status` ∈ up_to_date/needs_attention/archivable/archived; `visibility` ∈ internal/public).
- **CRUD tools (S14.api.1, DONE)**: `mcp/docs.py` adds path-grouped tree building + `derive_status` lifecycle (needs_attention when stale > `DOCS_REVIEW_DAYS`; archivable when stale AND unreferenced). `mcp/server.py` registers + dispatches 7 tools (`docs_list/get/upsert/set_flags/search/sync/agent_run`). Verified: upsert v1→v3 with revisions preserved + audit row written.
- **Confluence sync (S14.sync.1, DONE — dry-run)**: `mcp/docs_sync.py` maps `path`→Confluence ancestor pages, pushes public docs idempotently (stores `confluence_page_id`, updates in place after), `tags[]`→labels, logs every action to `doc_sync_log`. Connector gained `confluence_update_page` + create now returns a deterministic page id. Dry-run by default; live only when `DOCS_SYNC_ENABLED` + `CONN_CONFLUENCE_ENABLED` + `WORKFLOW_WRITES_ENABLED`. Verified plan mirrors `runbooks/` into space `COMP`, no outbound calls.
- **Agent (S14.agent.1, DONE & verified live)**: `mcp/docs_agent.py` is a checkpointed LangGraph `StateGraph` — `do_reconcile → do_triage → do_suggest → apply_gate (interrupt) → apply_approved → END`, compiled with `MemorySaver` keyed by `thread_id`. A fresh run pauses at the gate (`status="waiting_approval"`, returns `run_id` + proposals); resuming with `{run_id, resume_decision}` (slugs / `"all"` / `"reject"`) applies only approved proposals via an audited `docs_upsert` (`source="docs_agent_apply"`). The `/docs` Agent panel renders the gate (per-proposal checkboxes + Apply selected / Apply all / Reject). Verified live: fresh→waiting_approval; resume `reject`→completed, no writes; resume `all` on a seeded `needs_attention` doc → v1→v2, status→`up_to_date`, new audited revision. (Gotcha: LangGraph 0.2.62 rejects a node name equal to a state-key name — nodes are `do_*`.)
- **Smoke (S14.verify.1, backend DONE)**: `scripts/smoke_docs.sh` is green — tools registered, CRUD+revision+audit, flag transitions, dry-run sync plan mirrors tree, agent emits proposals without applying.
- **Env (defaulted, sync off)**: `DOCS_REVIEW_DAYS=90`, `DOCS_CONFLUENCE_SPACE=COMP`, `DOCS_SYNC_ENABLED=false`, `DOCS_DEFAULT_VISIBILITY=internal` — added to `.env.example` + `.env.local`.
- **Migration + web (S14.migrate.1/S14.web.1/S14.web.2, DONE)**: `scripts/import_docs.py` imports the repo `.md` corpus as v1 wiki docs; `/api/docs*` proxies and typed hooks landed; `/docs` SPA route provides tree, Markdown view, editor/preview, flag/tag controls, search, sync and agent actions, plus review queue.

## Stage 15 — Operational fixes & UX quick-wins (partial)
- **S15.wrangler.2 COMPLETE**: `/wrangler` now has an XL-screen MongoDB aggregation JS panel that renders `db.<collection>.aggregate([...])`, updates after successful preview/run/save/load, preserves the last successful pipeline when visual edits are invalid or untested, and supports copy-to-clipboard for the full pipeline and each individual stage snippet. Verified with `cd web && npm run build`.
- Still open: `S15.wrangler.1` bulk projection actions and `S15.askdata.1` timeout/empty-response fix.

## Stage 17 — Builder model upgrade to APEX + per-role `max_tokens` (COMPLETE)
- Builder subagent now runs on `Qwen3.6-35B-A3B-APEX-MTP-I-Balanced` (port 9292) with 60k `max_tokens`.
- Agent endpoint retains `qwen3.6-27b` as default upstream model.
- Fixed: agent omits `tools` field when empty (upstream vLLM rejects `tools: []`).
- New `llm_max_tokens(role)` helper in `mcp/llm.py` for per-role token budgets.
- Verified: agent plain chat, tool dispatch (echo, summarize_text), builder math, builder code gen.

## Verified live (rebuilt stack)
- `/api/topology` → 8 nodes, 11 edges, 6 concerns (prod RDS logging disabled, P1 incident, 2 neglected tickets, failing checks, high-risk change).
- `/api/connectors` → schema + non-empty sample_data for all connectors.
- `/architecture` → HTTP 200; web `/healthz` ok; all containers healthy.
- Persistence survives `down && up --build`.

## Key files changed / committed this session
- `IMPLEMENT.md` — archived completed sections; added/updated roadmap stages **18** (architecture diagram v2), **19** (SSO/Basic Auth + LDAP RBAC), **20** (Standup Jira cockpit), **21** (Deep Agent platform); env surface updated.
- `IMPLEMENT-ARCHIVE.md`, `COORDINATION.md` — archive + multi-agent coordination rules.
- `mcp/docs_agent.py`, `mcp/server.py` — Stage 14 docs-agent converted to checkpointed LangGraph HITL apply gate and exposed via MCP.
- `web/main.py`, `web/src/lib/{queries,types}.ts`, `web/src/routes/docs.tsx` — Docs Wiki web proxies/hooks/UI plus docs-agent apply/reject controls.
- `mcp/db.py`, `web/src/routes/sheet.tsx` — Stage 6 followups: accurate row counts, NL column reactivity, boolean/string-array editors.
- `caddy/Caddyfile.snippet.example`, `docs/clients.md`, `mcp/server.py` — Stage 3 SSE framing and optional Caddy MCP snippet.
- `scripts/import_docs.py` — Stage 14 markdown corpus importer.
- `web/src/routes/wrangler.tsx` — Stage 15 live MongoDB aggregation JS panel + copy actions.

## Session 2026-05-22 (Stage 20 standup orchestration) — YOLO vertical slice
- **S20.policy.1 DONE** — `docs/standup.md` documents roles (session owner/scrum-master/product owner, participant, observer, admin fallback), dry-run policy, `STANDUP_DRY_RUN_ONLY` / `JIRA_WRITES_ENABLED` interaction, and current limitations.
- **S20.ui.1 / S20.explorer.1 DONE** — `/standup` route added with sidebar navigation; Jira Explorer is the dominant panel, reusing `JiraEditableGrid`; `allowApply={false}` disables apply from Standup until approval/RBAC lands while Hub keeps normal Stage-16 behavior.
- **S20.chat.1 DONE (initial live slice)** — `StandupChat` connects to `/api/standup/ws/daily-standup`, handles snapshot/chat/presence/error events, retries/falls back to local capture, highlights URLs/Jira keys/@mentions, and reports association count to the configuration panel.
- **S20.links.1 DONE** — link/mention/Jira-key extraction in both MCP helper (`mcp/standup_agent.py`) and web websocket store (`web/standup_store.py`) for Jira, Confluence, GitHub, ServiceNow/SNOW, Archer, Snowflake, MongoDB, generic URLs, and @mentions.
- **S20.agent.1 DONE (dry-run helper)** — MCP tools `standup_link_context` and `standup_summarize` registered; outputs stay `proposed`/`dry_run`, never stage Jira or mutate external systems; unsupported planner models fail fast.
- **S20.model.1 / S20.ws.1 DONE (web-owned JSON persistence)** — `web/standup_store.py` stores sessions/messages/proposals/agent_runs in `STANDUP_STORE_PATH`, `/data/auth/standup_sessions.json` when mounted, or `/tmp/sglandsimple_standup_sessions.json` for local dev; `web/standup_ws.py` exposes snapshot + websocket fanout for join/chat/typing/placeholder summarize/approve/reject.
- **S20.verify.1 PARTIAL** — `scripts/smoke_standup_ws.py` added for two-client websocket smoke. Direct store smoke passed; full websocket smoke requires rebuilt/running web container.

## Audit findings 2026-05-22 (parallel-agent diff audit)
- Created `docs/parallel-agent-diff-audit.md` documenting dirty tracked/untracked files, stale worktrees, and recommended handling order.
- See `COORDINATION.md` for commit protocol; current tree has co-mingled S15/S19/S20/S22 changes pending explicit staging by path.

## Next agent — start here
1. **Read `COORDINATION.md` first** — respect file ownership, especially shared files (`IMPLEMENT.md`, `web/main.py`, `mcp/server.py`, `mcp/db.py`, `web/src/lib/{queries,types}.ts`).
2. **Stage 14 — COMPLETE.** All `S14.*` done incl. the docs-agent LangGraph apply-gate; eligible for archival to `IMPLEMENT-ARCHIVE.md` on the next pass.
3. **`progress.md` was restored** after being overwritten by an S20 subagent. Older Stage 11-17 history is preserved above; newer S20 notes are appended below.
4. `S13.cleanup.1` — finish migrating non-semantic color literals to tokens.
5. `S15.*` — wrangler bulk projection (`S15.wrangler.1`) and ask_data timeout fixes (`S15.askdata.1`), per `IMPLEMENT.md` ownership map. `S15.wrangler.2` is complete.
6. **Stage 18–22** — architecture diagram v2 (partially done), web auth/RBAC (in progress), Standup Jira cockpit (vertical slice done, needs landing), UX/chat polish + Wrangler derived fields — see `IMPLEMENT.md` and `docs/parallel-agent-diff-audit.md`.

## Session 2026-05-22 (pi agent) — S19 logout button + credential cache fix

User reported that login persisted even in a new incognito browser — no way to sign out.

**Root cause:** HTTP Basic Auth browsers cache credentials per-origin. There is no JavaScript API to clear them. The only reliable way is to force a 401 response with `WWW-Authenticate`, which causes the browser to forget its cached credentials.

**Changes:**

1. **`web/main.py`** — Added `POST /api/logout` endpoint that raises HTTP 401 with `WWW-Authenticate: Basic realm="sglandsimple"` (Basic Auth mode) or plain 401 (other modes). This forces the browser to clear its credential cache for the origin.

2. **`web/src/lib/queries.ts`** — Added `useLogout()` mutation that:
   - Calls `fetch("/api/logout", { method: "POST" })` (raw fetch, not `api.post`, because the 401 is intentional)
   - Swallows the expected 401 error
   - Clears all React Query cache via `qc.clear()`
   - Hard-navigates to `/` to trigger the browser's native login prompt

3. **`web/src/components/topbar.tsx`** — Added `LogOut` icon button next to the authenticated display name. Calls `logout.mutate()` on click. Disabled while logout is in progress.

**Files changed:**
- `web/main.py` — `POST /api/logout` endpoint
- `web/src/lib/queries.ts` — `useLogout()` hook
- `web/src/components/topbar.tsx` — logout button
- `IMPLEMENT.md` — S19.logout.1 task added + checked
- `COORDINATION.md` — S19 status updated

**Verification:**
- `python3 -m py_compile web/main.py` — passes
- `cd web && npm run build` — passes (tsc + vite, clean)

## Session 2026-05-22 (S20.agent.2 subagent) — standup agent template/docs context
- **S20.agent.2 DONE** — `mcp/standup_agent.py` now builds deterministic story template context for `standup_summarize`: Stage-9 Jira story template shape, acceptance-criteria format, default standup labels, priority/story-point guidance, selected epic/issue context, Docs Wiki docs, and Confluence links.
- New `new_jira_work` proposals remain dry-run/proposed and are normalized with `summary`, `description`, `issue_type`, `acceptance_criteria`, `labels`, `priority`, `story_points`, `epic_link`, `doc_links`, `related_links`, and `source_message_ids` defaults when missing.
- `docs/standup.md` documents the template/context behavior.
- Validation: `python3 -m py_compile mcp/standup_agent.py` passed. An optional direct Python import smoke could not run in the host environment because `langchain_openai` is not installed outside the container/venv.

## Session 2026-05-22 (S20.identity.1 subagent) — standup auth identity wiring
- **S20.identity.1 DONE** — Standup chat now uses Stage-19 `/api/me` identity via `useAuth()` for display name/email, sends `display_name` + `email` on websocket `join` and `chat.message`, and falls back to the existing Browser suffix when no authenticated user is available.
- Backend websocket identity resolution now calls `auth.resolve_user(websocket)` where possible, tracks `ClientState.email`, keeps legacy header/query/payload fallback for disabled/no-user cases, includes `display_name`/`email` in presence, and persists `author_email` on standup messages.
- Validation: `python3 -m py_compile web/standup_ws.py web/standup_store.py web/main.py` and `cd web && npm run build` passed.

## Session 2026-05-22 (S20.trace.1 subagent) — standup trace bubble UI
- **S20.trace.1 UI DONE** — `/standup` Jira Configuration / tool trace stays collapsed by default and expands into dry-run/live-write gates, connector health, websocket/presence/message trace, dry-run agent/tool placeholders, and cross-service association details.
- `StandupChat` now emits association metadata and trace telemetry to the parent route without backend changes.
- Validation: `cd web && npm run build` passed (Vite chunk-size warning only).

## Session 2026-05-22 (S20.proposals.1 subagent) — standup proposal persistence + dry-run Jira staging
- **S20.proposals.1 DONE** — websocket `agent.summarize` now calls MCP `standup_summarize`, persists an `agent_run`, and stores returned proposals as JSON-backed `standup_proposals` with `status=proposed`, `dry_run=true`, `dry_run_payload`, `validation_state`, source message IDs, rationale, actor, and timestamps.
- `new_jira_work` proposals are retained as dry-run standup proposals pending HITL approval/apply. `jira_edit` proposals with `edits[]` or `issue_key`/`changes` are staged through existing Stage-16 `jira_stage_edits` and immediately validated with `jira_validate_staged`; no `jira_apply_staged` call or live external write occurs.
- Websocket broadcasts `agent.running`, `agent.summary`, `proposal.created`, and `proposal.updated`; unsupported/unavailable agent calls degrade to a persisted dry-run placeholder instead of losing the request.
- **S20.verify.1 backend smoke expanded (partial)** — `scripts/smoke_standup_ws.py` now triggers `agent.summarize`, asserts the proposed/dry-run shape including `validation_state`, and verifies proposal persistence through the snapshot endpoint. Full approval/RBAC/live container smoke remains for later.
- Validation: `python3 -m py_compile web/standup_store.py web/standup_ws.py scripts/smoke_standup_ws.py` passed.

## Session 2026-05-22 (pi orchestrator) — coordination cleanup + integrated verification pass
- Re-read and updated `COORDINATION.md`; future edits stayed scoped to Stage 19 admin diagnostics and Stage 20 standup sections. No broad staging planned; commit must stage named paths only.
- **S19.admin.1 DONE** — `/api/auth/diagnostics` is guarded by `canAdminAuth`; `/auth-admin` renders auth mode, group/role/capability mappings, cache status, LDAP adapter status, seeded POC identity hints, and recent denial reasons. Fixed Badge variants to match the project design-system API and updated `web/Dockerfile` so `auth_ldap.py`/`auth_explain.py` are present in the runtime image.
- Stage 20 docs/checklists reconciled to actual implementation: identity, agent template context, proposal persistence/staging, and trace bubble are complete; approval/RBAC/full rebuilt-stack verification remain open.
- Validation: `python3 -m py_compile mcp/*.py web/*.py scripts/*.py` passed; `cd web && npm run build` passed after fixing `/auth-admin` badge variants; rebuilt/restarted web with `docker compose up --build -d mcp web`; regenerated POC Basic users with `AUTH_BASIC_SEED_PASSWORD=changeme-poc AUTH_BASIC_USERS_FILE=./perm/auth/users.json python3 web/auth_seed.py`; `bash scripts/smoke_auth.sh` passed (83 pass / 0 fail / 3 skipped mode-specific checks); `scripts/smoke_standup_ws.py` passed; `/api/auth/diagnostics` smoke passed for admin user.

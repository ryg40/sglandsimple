# Progress

## Status
**Stage 11 COMPLETE & verified live; Stage 12 COMPLETE & verified live (re-verified this session); Stage 3 re-verified live; Stage 13 COMPLETE (one follow-up); Stage 14 BACKEND COMPLETE & verified live (web UI + migrate pending); Stage 17 COMPLETE.**
Work branch: `stage-14-docs-wiki`.

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

## Stage 14 — Docs Wiki + Confluence sync (BACKEND DONE & verified live; web UI + migrate pending)
- **Data model (S14.model.1, DONE)**: `mongo-seed/14-docs.js` seeds `docs`/`doc_revisions`/`doc_sync_log` (incl. one deliberately-stale doc to exercise lifecycle). `mcp/db.py` gained docs system-of-record helpers — `docs_list/get/upsert/set_flags/search`, `doc_sync_log_append/recent`, `docs_set_confluence_id` — all auditing via `_audit(source="docs_*")`. Flags validated against the 14b enums (`status` ∈ up_to_date/needs_attention/archivable/archived; `visibility` ∈ internal/public).
- **CRUD tools (S14.api.1, DONE)**: `mcp/docs.py` adds path-grouped tree building + `derive_status` lifecycle (needs_attention when stale > `DOCS_REVIEW_DAYS`; archivable when stale AND unreferenced). `mcp/server.py` registers + dispatches 7 tools (`docs_list/get/upsert/set_flags/search/sync/agent_run`). Verified: upsert v1→v3 with revisions preserved + audit row written.
- **Confluence sync (S14.sync.1, DONE — dry-run)**: `mcp/docs_sync.py` maps `path`→Confluence ancestor pages, pushes public docs idempotently (stores `confluence_page_id`, updates in place after), `tags[]`→labels, logs every action to `doc_sync_log`. Connector gained `confluence_update_page` + create now returns a deterministic page id. Dry-run by default; live only when `DOCS_SYNC_ENABLED` + `CONN_CONFLUENCE_ENABLED` + `WORKFLOW_WRITES_ENABLED`. Verified plan mirrors `runbooks/` into space `COMP`, no outbound calls.
- **Agent (S14.agent.1, PARTIAL)**: `mcp/docs_agent.py` runs reconcile→triage→suggest. Triage flags stale/unreferenced (verified legacy doc → archivable). Suggestions are HIL proposals (`proposed_body_md`), **never auto-applied** (`applied_any:false` verified); applying = a separate audited `docs_upsert`. Remaining: wire into a checkpointed LangGraph `StateGraph` for interrupt/resume at the apply gate; add `/api/docs/agent` proxy.
- **Smoke (S14.verify.1, backend DONE)**: `scripts/smoke_docs.sh` is green — tools registered, CRUD+revision+audit, flag transitions, dry-run sync plan mirrors tree, agent emits proposals without applying.
- **Env (defaulted, sync off)**: `DOCS_REVIEW_DAYS=90`, `DOCS_CONFLUENCE_SPACE=COMP`, `DOCS_SYNC_ENABLED=false`, `DOCS_DEFAULT_VISIBILITY=internal` — added to `.env.example` + `.env.local`.
- **PENDING**: S14.migrate.1 (`scripts/import_docs.py` — import the repo `.md` corpus as v1 docs), S14.web.1 (`/api/docs*` proxies + `useDocs*` hooks), S14.web.2 (`/docs` SPA route: tree + Markdown view + editor + flag/tag controls + search + review queue).

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

## Key files changed (Stages 12–13, 17)
- `IMPLEMENT.md` (Stage 17 section + task checklist)
- `docs/deep_agent.md` (builder model + `BUILDER_MAX_TOKENS` docs)
- `agent/main.py` — conditional `tools`, `UPSTREAM_MAX_TOKENS`
- `mcp/llm.py` — `llm_max_tokens()` helper
- `mcp/deep_agent/builder.py` — `max_tokens` on builder calls
- `.env.local`, `.env.example` — new env vars, updated `BUILDER_MODEL`
- `mcp/connectors/{aws,jira,servicenow,github,confluence,snowflake,mongodb,archer}.py`
- `mcp/topology.py` (new), `mcp/server.py`
- `web/main.py`
- `web/src/routes/architecture.tsx` (new), `web/src/components/hub-columns.tsx` (new)
- `web/src/routes/hub.tsx`, `web/src/lib/{queries,types}.ts`, `web/src/App.tsx`, `web/src/components/app-sidebar.tsx`
- `web/src/index.css`, `web/src/main.tsx`, `web/package.json`
- `compose.yaml`, `.gitignore`, `scripts/reseed.sh` (new)
- `IMPLEMENT.md`, `progress.md`

## Next agent — start here
1. **Stage 14 web UI** — `S14.web.1` (`/api/docs*` proxies in `web/main.py` + `useDocs*` hooks in `queries.ts`/`types.ts`; the 7 MCP tools are ready to proxy) then `S14.web.2` (`/docs` route + sidebar entry; reuse the `Markdown` component; tree + editor-with-preview + flag/tag controls + search + review queue; loading/empty/error per Stage-8).
2. **Stage 14 corpus import** — `S14.migrate.1` (`scripts/import_docs.py`): import root + `docs/` `.md` files as v1 wiki docs via `docs_upsert`, path-mapped slugs, idempotent.
3. **Stage 14 agent** — finish `S14.agent.1`: wrap `mcp/docs_agent.py` in a checkpointed LangGraph `StateGraph` (interrupt at the apply gate) + add `/api/docs/agent` proxy.
4. `S13.cleanup.1` — finish migrating non-semantic color literals to tokens.

# Progress

## Status
**Stage 12 COMPLETE & verified live; Stage 13 COMPLETE (one follow-up); Stage 14 DOCUMENTED (not built).**
Work branch: `stage12-dynamic-overview-mockdata`.

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

## Stage 14 — Docs Wiki + Confluence sync (DOCUMENTED ONLY)
- Full spec + task checklist in `IMPLEMENT.md`. Not implemented. In-app MkDocs/Docusaurus-style library; MongoDB system of record (`docs`/`doc_revisions`/`doc_sync_log`); per-doc visibility/status/tags; public docs sync to Confluence mirroring the path tree; LangGraph agent for reconcile→triage→suggest. Start at `S14.model.1`.

## Verified live (rebuilt stack)
- `/api/topology` → 8 nodes, 11 edges, 6 concerns (prod RDS logging disabled, P1 incident, 2 neglected tickets, failing checks, high-risk change).
- `/api/connectors` → schema + non-empty sample_data for all connectors.
- `/architecture` → HTTP 200; web `/healthz` ok; all containers healthy.
- Persistence survives `down && up --build`.

## Key files changed (Stages 12–13)
- `mcp/connectors/{aws,jira,servicenow,github,confluence,snowflake,mongodb,archer}.py`
- `mcp/topology.py` (new), `mcp/server.py`
- `web/main.py`
- `web/src/routes/architecture.tsx` (new), `web/src/components/hub-columns.tsx` (new)
- `web/src/routes/hub.tsx`, `web/src/lib/{queries,types}.ts`, `web/src/App.tsx`, `web/src/components/app-sidebar.tsx`
- `web/src/index.css`, `web/src/main.tsx`, `web/package.json`
- `compose.yaml`, `.gitignore`, `scripts/reseed.sh` (new)
- `IMPLEMENT.md`, `progress.md`

## Next agent — start here
1. `S13.cleanup.1` — finish migrating non-semantic color literals to tokens.
2. Stage 14 — build the docs wiki (`S14.model.1` →).
3. Stage 11 (Overview command center) is still documented-only if not yet built — check before starting.

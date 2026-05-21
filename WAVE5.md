# Wave 5 — React Dashboard: Bubbles, Workflow Lane, Report Export

**Goal:** The SPA shows the connection grid, workflow stepper, and report download buttons.

---

## Wave 5.1 — S9.web.1: Connector proxy routes + types/hooks

**Files:** `web/main.py`, `web/src/lib/types.ts`, `web/src/lib/queries.ts`, `web/src/lib/api.ts`

1. **Backend routes** in `web/main.py`:
   - `GET /api/connectors` → proxy MCP `connector_list` tool → returns list of bubbles.
   - `GET /api/connectors/{name}` → proxy MCP `connector_get` tool → returns detail + recent items.
   - `GET /api/reports/download?finding_id=&format=` → proxy `report_pdf` / `report_ppt` and stream the file back with correct `Content-Type` + `Content-Disposition: attachment`.
2. **TS types** in `types.ts`:
   - `ConnectorBubble`, `ConnectorDetail`, `WorkflowRun`, `WorkflowStep`, `ReportDownload`.
3. **Query hooks** in `queries.ts`:
   - `useConnectors()` → polls every 30s.
   - `useConnector(name)` → detail + recent items.
   - `useReportDownload()` → mutation that triggers download via window.URL.createObjectURL.

---

## Wave 5.2 — S9.web.2: Connections grid (bubbles)

**Files:** `web/src/routes/hub.tsx` (or extend `overview.tsx`), `web/src/components/connection-bubble.tsx`

1. **ConnectionBubble** component:
   - Status dot (`green` = healthy, `yellow` = degraded, `gray` = disabled/placeholder, `red` = error).
   - Name + system icon (use lucide-react icons).
   - One-line summary metric (e.g., "3 open issues", "25 log rows", "Not connected").
   - Last-sync timestamp.
   - Click opens a **detail drawer** (shadcn Sheet component) showing recent items + tool buttons.
2. **Hub route** (`/hub`):
   - Responsive grid: 2 cols mobile, 4 cols desktop.
   - Skeleton cards while loading.
   - Error state with retry button.

---

## Wave 5.3 — S9.web.3: Workflow lane + "Relate everything" view

**Files:** `web/src/routes/workflow.tsx`, `web/src/components/workflow-stepper.tsx`, `web/src/components/relate-panel.tsx`

1. **WorkflowStepper** component:
   - Horizontal stepper (7 steps: Finding → Epic → Ticket → Branch → PR → Docs → Report).
   - Each step shows its artifact:
     - Finding: severity badge + requirement text.
     - Epic: Jira key + title + platform chips.
     - Ticket: key + summary + assignee placeholder.
     - Branch: branch name + commit count.
     - PR: PR number + check status chips.
     - Docs: Confluence page title + last updated.
     - Report: PDF/PPT download buttons.
   - Active step highlighted; completed steps green check; future steps gray.
   - Click any step → opens detail drawer.
2. **RelatePanel** component:
   - Single panel that shows ALL associated records for the selected finding/epic.
   - Sections: Finding card, Epic card, Work items table, PRs table, Docs table, Log samples table.
   - Every record clickable → opens detail view.

3. **Workflow route** (`/workflow`):
   - Top: finding/epic selector (dropdown of `audit_findings`).
   - Middle: the stepper.
   - Bottom: RelatePanel.
   - "Run workflow" button (calls `workflow_run` MCP tool → starts dry-run).
   - "Approve" buttons appear at interrupt gates.

---

## Wave 5.4 — S9.web.4: Report export buttons

**Files:** `web/src/routes/workflow.tsx` (add buttons), `web/main.py` (download proxy already done in 5.1)

1. In the final step of the stepper:
   - "Export PDF" button → calls `POST /api/reports/download?finding_id=...&format=pdf` → triggers browser download.
   - "Export PPT" button → same for pptx.
2. Loading state while generating.
3. Error toast if generation fails.

---

## Wave 5.5 — Navigation wiring

**Files:** `web/src/App.tsx`, `web/src/components/app-sidebar.tsx`

1. Add `/hub` and `/workflow` routes to `App.tsx`.
2. Add "Compliance Hub" and "Workflow" to the sidebar NAV array in the "Tools" group.
3. Ensure active route highlighting works.

---

## Commit checkpoint

```bash
git add .
git commit -m "S9 Wave 5: React dashboard — connection bubbles, workflow stepper, report export"
# Build the SPA
cd web && npm run build
docker compose build web
```

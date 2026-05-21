# Wave 6 — Verification: End-to-End Smoke Tests

**Goal:** The entire Stage 9 stack is verified in mock mode with no live credentials.

---

## Wave 6.1 — S9.verify.1: `scripts/smoke_workflow.sh`

**Files:** `scripts/smoke_workflow.sh`

1. **Setup**
   ```bash
   #!/usr/bin/env bash
   set -euo pipefail
   BASE_URL="${WEB_URL:-http://localhost:5452}"
   MCP_URL="${MCP_URL:-http://localhost:5451/mcp}"
   ```
2. **Seed a finding** via MCP `tools/call`:
   ```bash
   curl -s "$MCP_URL" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"insert_workflow","arguments":{"collection":"audit_findings","doc":{"source":"smoke","regulation":"SOX-404","requirement":"Test audit logging requirement","severity":"high","status":"open","epic_id":"epic-rds-001"}}}}'
   ```
3. **Dry-run the workflow**:
   ```bash
   curl -s "$MCP_URL" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"workflow_run","arguments":{"finding_id":"<from_step_2>"}}}}'
   ```
4. **Assert collections populated**:
   ```bash
   # Check work_items exists for this finding
   curl -s "$MCP_URL" ... tools/call find_workflow ...
   # Check workflow_runs has a completed entry
   # Check audit_log grew with source="workflow_*" entries
   ```
5. **Generate a report**:
   ```bash
   curl -s "$MCP_URL" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"report_pdf","arguments":{"finding_id":"<id>"}}}}'
   ```
6. **Assert report file exists**:
   ```bash
   test -f /sandbox/reports/*.pdf
   ```

---

## Wave 6.2 — S9.verify.2: Build + dashboard walkthrough

**Manual checklist** (run by human):

1. [ ] `docker compose up --build -d` brings up all 4 services healthy.
2. [ ] Open `http://<host>:5452/hub` → 8 connection bubbles render; all show "disabled/placeholder" state.
3. [ ] Click MongoDB bubble → detail drawer shows collection counts (employees=30, tickets=40, etc.).
4. [ ] Navigate to `/workflow` → select the seeded RDS finding.
5. [ ] Click "Run workflow" → stepper advances through all 7 steps.
6. [ ] At interrupt gates (PR approval, Doc approval), "Approve" buttons appear; click them to continue.
7. [ ] Final step shows "Export PDF" + "Export PPT" buttons; click PDF → file downloads.
8. [ ] Open downloaded PDF → contains finding, epic, mock work items, PR, doc, and log samples.
9. [ ] `/api/audit/recent` shows `audit_log` rows with `source="workflow_*"`.
10. [ ] `scripts/smoke_workflow.sh` passes (exit 0).

---

## Wave 6.3 — Live connector flip test

**Optional** (requires real credentials):

1. Set `CONN_SNOWFLAKE_ENABLED=true` + Snowflake credentials in `.env.local`.
2. `docker compose up -d`.
3. Snowflake bubble shows "healthy".
4. Snowflake detail drawer shows real recent items.
5. `snowflake_query` tool returns real data.
6. Set `CONN_SNOWFLAKE_ENABLED=false` → bubble returns to "disabled".

---

## Commit checkpoint

```bash
git add .
git commit -m "S9 Wave 6: end-to-end smoke tests and verification"
```

---

## Full Stage 9 merge

```bash
# After all waves pass
git checkout main
git merge stage9-w6 --no-ff -m "Stage 9: Compliance workflow hub"
git push origin main
```

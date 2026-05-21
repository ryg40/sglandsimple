# Wave 3 — LangGraph Orchestrator: Steps 1→6 with Approval Interrupts

**Goal:** The workflow engine can walk a finding through the full lifecycle end-to-end, in dry-run mode.

---

## Wave 3.1 — S9.workflow.2: LangGraph orchestrator (dry-run core)

**Files:** `mcp/workflow/graph.py`, `mcp/workflow/nodes.py`, `mcp/workflow/__init__.py`

1. Define the graph in `graph.py`:
   ```python
   builder = StateGraph(WorkflowState)
   builder.add_node("capture_finding", nodes.capture_finding)
   builder.add_node("link_epic", nodes.link_epic)
   builder.add_node("generate_ticket", nodes.generate_ticket)
   builder.add_node("coding_branch", nodes.coding_branch)
   builder.add_node("open_pr", nodes.open_pr)
   builder.add_node("post_approval_docs", nodes.post_approval_docs)
   builder.add_conditional_edges("capture_finding", edges.route_after_finding)
   # ... etc
   ```
2. **Approval interrupts** at two gates:
   - Before `open_pr`: `interrupt({"message": "Approve PR creation?", "preview": branch_name + diff_summary})`
   - Before `post_approval_docs`: `interrupt({"message": "Approve Confluence doc update?", "preview": epic_log_section})`
3. **Dry-run mode**: When `WORKFLOW_WRITES_ENABLED=false`, each node:
   - Generates the artifact it would create (ticket payload, branch name, PR body, doc section).
   - Persists it to Mongo with `dry_run=true` flag.
   - Does **not** call the live connector.
   - Returns the artifact in the state.

---

## Wave 3.2 — S9.workflow.3: Jira ticket generation from epic template

**Files:** `mcp/workflow/jira_template.py`

1. Given `finding` + `epic`, produce a best-practice Jira story payload:
   ```json
   {
     "project": { "key": epic.jira_key.split("-")[0] },
     "summary": f"[{epic.jira_key}] Implement {finding.requirement[:60]}",
     "description": f"**Regulation:** {finding.regulation}\\n**Requirement:** {finding.requirement}\\n**Severity:** {finding.severity}",
     "issuetype": { "name": "Story" },
     "customfield_epic_link": epic.jira_key
   }
   ```
2. When live: calls `jira_create_issue` connector tool.
3. When dry-run: returns the payload JSON + a mock key (e.g., `MOCK-123`).

---

## Wave 3.3 — S9.workflow.4: PR template + Actions/review wiring (dry-run)

**Files:** `mcp/workflow/pr_template.py`

1. Generate:
   - Branch name: `feature/MOCK-123-rds-audit-logging`
   - PR body with checklist (compliance checks, test coverage, doc updates).
   - Required checks: `compliance-scan`, `unit-tests`, `integration-tests`.
   - Reviewers: `copilot` + 2 team member placeholders.
2. When live: calls `github_create_branch` + `github_open_pr` + `github_list_checks`.
3. When dry-run: returns the template + mock PR URL (`https://github.com/org/repo/pull/MOCK-456`).

---

## Wave 3.4 — S9.workflow.5: Confluence Epic-Log documentation (dry-run)

**Files:** `mcp/workflow/epic_log.py`

1. Render an Epic-Log section:
   - Heading: the Jira ticket key + summary.
   - Body: compliance requirement, implementation notes, PR link, test results.
   - Footer: "Last updated by workflow run <run_id>".
2. When live: calls `confluence_create_page` (or page update) connector tool.
3. When dry-run: returns the rendered markdown + mock Confluence URL.

---

## Wave 3.5 — Cross-link persistence

**Files:** `mcp/workflow/graph.py` (update nodes)

After each step completes (in both dry-run and live mode):
1. Upsert a `work_item` doc linking `finding_id` ↔ `epic_id` ↔ `jira_key`.
2. Upsert `pr_records`, `doc_records` with the generated URLs.
3. Write to `workflow_runs` with `step_index` and `artifacts`.
4. Audit-log every write with `source="workflow_<step_name>"`.

---

## Commit checkpoint

```bash
git add .
git commit -m "S9 Wave 3: LangGraph orchestrator steps 1-6 with dry-run and interrupts"
docker compose build mcp
```

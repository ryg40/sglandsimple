# Wave 1 — Foundation: Data Model, Connector Protocol, and Workflow Skeleton

**Goal:** Land the server-side substrate that everything else in Stage 9 builds on.

---

## Wave 1.1 — S9.model.1: New MongoDB collections + seed data

**Files:** `mongo-seed/04-epics.js`, `mongo-seed/05-audit_findings.js`, `mongo-seed/06-work_items.js`, `mcp/db.py`, `compose.yaml` (verify seed mount)

1. Add seed JS files for each new collection:
   - `epics` — include the **RDS priority epic**: `{ _id: "epic-rds-001", jira_key: "RDS-LOG-1", title: "RDS Audit Logging", regulation_refs: ["SOX-404", "PCI-DSS-10.2"], db_platform_combos: ["RDS MySQL", "RDS PostgreSQL", "RDS MariaDB"], priority: "high", status: "in_progress" }`
   - `audit_findings` — one sample finding linked to the RDS epic: `{ source: "manual", regulation: "SOX-404", requirement: "Database audit logs must capture login events, SQL errors, and SQL queries", severity: "high", status: "open", epic_id: "epic-rds-001" }`
   - `work_items`, `pr_records`, `doc_records`, `log_samples`, `workflow_runs` — empty schema docs so the collections exist.
2. Mount the new seeds in `compose.yaml` (they already use `mongo-seed:/docker-entrypoint-initdb.d`).
3. In `mcp/db.py`, add a `WORKFLOW_COLLECTIONS` tuple separate from `KNOWN_COLLECTIONS`:
   ```python
   WORKFLOW_COLLECTIONS = ("audit_findings", "epics", "work_items", "pr_records", "doc_records", "log_samples", "workflow_runs")
   ```
4. Add `find_workflow()`, `insert_workflow()`, `update_workflow()` helpers that validate collection is in `WORKFLOW_COLLECTIONS`, enforce `source="workflow_*"` audit prefix, and call the existing `_audit()` writer.

---

## Wave 1.2 — S9.connect.2 + S9.connect.3: Connector protocol + registry + MongoDB reference connector

**Files:** `mcp/connectors/__init__.py`, `mcp/connectors/base.py`, `mcp/connectors/mongodb.py`, `mcp/server.py`

1. Create `mcp/connectors/base.py` with the `Connector` protocol:
   ```python
   class Connector(Protocol):
       name: str
       async def health(self) -> dict: ...
       async def summary(self) -> dict: ...
       def tools(self) -> list[dict]: ...
   ```
2. Create `mcp/connectors/__init__.py` with:
   - A registry dict keyed by connector name.
   - An `init_connectors()` coroutine that instantiates each connector, reads its `CONN_*_ENABLED` flag, and stores it.
   - A `get_connector(name)` helper.
3. Create `mcp/connectors/mongodb.py`:
   - Wraps existing `mongo_list_collections`, `mongo_describe_collection`, `mongo_query`, `mongo_aggregate` into the Connector protocol.
   - `health()` pings MongoDB via `db._client`.
   - `summary()` returns collection counts.
   - This serves as the **reference implementation** — all other connectors copy this pattern.
4. In `mcp/server.py`:
   - Call `init_connectors()` at startup.
   - Dynamically append connector tools to the `TOOLS` list from `registry.values()`.
   - Wire `_dispatch_tool()` to route connector tool calls to the right connector.

**Mock rule:** Every connector's `health()` and `summary()` must work even when `CONN_*_ENABLED=false`. When disabled, tools return `{"content": [{"type":"text","text":"... disabled"}], "isError": false}`.

---

## Wave 1.3 — S9.workflow.1: Workflow state models + collections wiring

**Files:** `mcp/workflow/models.py`, `mcp/workflow/__init__.py`, `mcp/db.py` (extend workflow helpers)

1. Create `mcp/workflow/models.py` with Pydantic v2 models:
   - `AuditFinding`, `Epic`, `WorkItem`, `PrRecord`, `DocRecord`, `LogSample`, `WorkflowRun`
   - Each uses `Field(alias="_id", default_factory=lambda: str(ObjectId()))` with `populate_by_name=True` so JSON consumers see `_id`.
   - Cross-link by `finding_id`, `epic_id`, `work_item_id`, etc.
2. `WorkflowState` (used by the LangGraph graph):
   ```python
   class WorkflowState(TypedDict):
       finding_id: str
       epic_id: str
       step_index: int
       artifacts: dict[str, Any]
       status: str  # "running" | "waiting_approval" | "completed" | "failed"
   ```
3. In `mcp/db.py`, add `find_workflow_run(run_id)`, `upsert_workflow_run(run_id, doc)`, `list_workflow_runs(finding_id=None)` helpers backed by `workflow_runs`.

---

## How to launch Wave 1

```bash
# From the repo root
git checkout -b stage9-w1

# Launch all three tasks in parallel via Pi subagent
pi subagent async wave1 \
  tasks:
    - agent: worker, task: "Implement Wave 1.1 — new MongoDB collections + seed data for Stage 9. Add mongo-seed/*.js for epics (RDS priority epic), audit_findings, work_items, pr_records, doc_records, log_samples, workflow_runs. Add WORKFLOW_COLLECTIONS allowlist and CRUD helpers in mcp/db.py with audited writes (source=workflow_*). Commit after each sub-task.", output: .pi/wave1.1.md, progress: true
    - agent: worker, task: "Implement Wave 1.2 — Connector protocol + registry + MongoDB reference connector. Create mcp/connectors/{base,__init__,mongodb}.py. Registry reads CONN_*_ENABLED. Mongo connector wraps existing mongo_* tools. Wire into mcp/server.py TOOLS + _dispatch_tool. Mock returns when disabled.", output: .pi/wave1.2.md, progress: true
    - agent: worker, task: "Implement Wave 1.3 — Workflow Pydantic models + collections wiring. Create mcp/workflow/models.py with AuditFinding, Epic, WorkItem, PrRecord, DocRecord, LogSample, WorkflowRun, WorkflowState. Cross-link by id. Add find/upsert/list helpers in mcp/db.py for workflow_runs.", output: .pi/wave1.3.md, progress: true
```

**Depends on:** S9 already planned in IMPLEMENT.md (Stage 8 complete).  
**Produces:** Foundation for all connector and workflow work in Waves 2–5.

---

## Commit checkpoint

After all three tasks finish and you've verified `docker compose build mcp` passes:

```bash
git add .
git commit -m "S9 Wave 1: data model, connector protocol, workflow skeleton"
```

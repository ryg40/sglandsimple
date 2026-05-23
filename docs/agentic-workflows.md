# Agentic workflows in this stack

The important teaching point in this repo is that **all workflow logic runs server-side**. The web app, IDE clients, and OpenAI-compatible callers only see tools and final answers.

## The three workflow layers

| Layer | Entry point | State / storage | Exact hand-off key |
| --- | --- | --- | --- |
| Agent service tool loop | `agent/` `/v1/chat/completions` | in-request message list | upstream `tool_calls[].id -> role:"tool" tool_call_id` |
| MCP tools | `mcp/server.py` `tools/call` | tool-specific code paths | `params.name` selects the MCP tool |
| LangGraph workflows | `mcp/*.py` graphs (`ask_data`, `web_research`, `deep_agent`, `docs_agent`) | Mongo or checkpointer state | workflow-specific ids such as `plan_id`, `thread_id`, `doc_id` |

## Workflow 1: ask_data

`ask_data` is the simplest enterprise example: natural language in, read-only Mongo answer out.

Key joins the workflow can traverse:

- `audit_findings.epic_id -> epics._id`
- `work_items.finding_id -> audit_findings._id`
- `work_items.epic_id -> epics._id`
- `pr_records.work_item_id -> work_items._id`

Why it matters: the model does not get raw database freedom. It plans against the allowlisted read layer in `mcp/db.py`.

## Workflow 2: docs agent

The docs wiki is the clearest human-in-the-loop workflow already in the stack.

| Step | File | Reads / writes | Join key |
| --- | --- | --- | --- |
| Reconcile | `mcp/docs_agent.py`, `mcp/docs_sync.py` | reads `docs`; may prepare Confluence sync actions | `docs.confluence_page_id` |
| Triage | `mcp/docs_agent.py` | reads `docs.last_reviewed_at`, `status`, `visibility` | `docs._id` |
| Suggest | `mcp/docs_agent.py` | drafts a proposed revision | proposal `slug` |
| Apply | `mcp/docs_agent.py` + `docs_upsert` | writes `doc_revisions`, updates `docs.version` | `doc_revisions.doc_id -> docs._id` |
| Audit | `mcp/docs_sync.py` / docs helpers | writes `doc_sync_log` | `doc_sync_log.doc_id -> docs._id` |

This is the best workflow to show when explaining why the graph lives in MCP instead of the browser.

## Workflow 3: deep agent

Stage 4 adds a planner/builder split.

- `plan_task` creates a plan and stores it in `deep_agent_plans`.
- `run_plan` executes it and stores results in `deep_agent_runs`.
- Exact persistence join: `deep_agent_runs.plan_id -> deep_agent_plans.plan_id`.
- Exact execution join inside the plan: each step uses `depends_on[] -> steps[].id`.

This is the teaching example for "agentic" meaning **multi-step, stateful, tool-using**, not just "LLM answered in a chat box."

## Workflow 4: compliance hub runs

The Stage 9 workflow hub uses workflow records that point back to the same domain objects:

- `workflow_runs.finding_id -> audit_findings._id`
- `workflow_runs.epic_id -> epics._id`

That link is what makes the hub, overview, and architecture pages feel like one system instead of isolated demos.

## What to emphasize in demos

1. **Client asks once.**
2. **Server decides whether tools are needed.**
3. **MCP owns the real workflow graph.**
4. **Mongo collections keep the workflow grounded in enterprise-shaped data.**
5. **Human approval is explicit** where the repo needs it (`docs_agent` apply gate, Jira staged changes).

## Where Stage 23 fits

Stage 23 does not invent a new workflow model. It makes existing workflows more teachable by enriching the overlap between:

- Mongo collections such as `audit_findings`, `epics`, `work_items`, `pr_records`
- connector samples such as GitHub, Confluence, Archer, ServiceNow, Snowflake, AWS
- in-app teaching docs under `/docs`

That is why the best Stage 23 demos start with one shared key (`RDS-LOG-1` or `finding-smoke-001`) and show multiple workflows converging on it.

# Overlap chain: trace one compliance finding through the stack

This stack gets easier to teach when you can follow one concrete identifier across multiple systems.

Use the RDS audit-logging storyline already seeded in the repo:

- **Finding:** `audit_findings._id = finding-smoke-001`
- **Epic record:** `epics._id = epic-rds-001`
- **Human Jira key:** `epics.jira_key = RDS-LOG-1`

## Current grounded chain in this repo

| Hop | Source | Exact join key | Example row(s) | Why it matters |
| --- | --- | --- | --- | --- |
| 1 | Mongo `audit_findings` | `audit_findings.epic_id -> epics._id` | `finding-smoke-001 -> epic-rds-001` | The compliance finding points at the remediation epic record. |
| 2 | Mongo `epics` | `epics.jira_key` | `epic-rds-001 -> RDS-LOG-1` | This is the human-facing project key most other systems can share. |
| 3 | Mongo `work_items` | `work_items.finding_id -> audit_findings._id` and `work_items.epic_id -> epics._id` | `wi-rds-logging-01`, `wi-rds-docs-05` | Work items split the finding into implementation and documentation tasks. |
| 4 | Mongo `pr_records` | `pr_records.work_item_id -> work_items._id` and `pr_records.epic_id -> epics._id` | `pr-rds-logging-501` | Shows delivery activity tied back to the same epic. |
| 5 | `mcp/connectors/github.py` sample | `sample_data[].epic_key -> epics.jira_key` | commits `a1f9c02`, `7d3e1b8` with `epic_key=RDS-LOG-1` | Lets the architecture and hub pages show code changes against the compliance story. |
| 6 | `mcp/connectors/confluence.py` sample | `sample_data[].matched_on.ticket_refs[] -> epics.jira_key` or `work_items.jira_key` | page `100401` references `RDS-LOG-1`; page `100433` references `RDS-LOG-1` and `RDS-LOG-2` | Gives the learner a documentation/evidence endpoint for the same work. |

## Read the chain left-to-right

1. Start at `mongo-seed/05-audit_findings.js`.
2. Follow `epic_id` into `mongo-seed/04-epics.js`.
3. Follow the same `_id` and `finding_id` into `mongo-seed/06-work_items.js`.
4. Follow `work_item_id` into `mongo-seed/07-pr_records.js`.
5. Switch to connector samples:
   - `mcp/connectors/github.py` uses `epic_key`.
   - `mcp/connectors/confluence.py` uses `matched_on.ticket_refs[]`.
6. Ask the learner which join is machine-safe (`_id`) and which is business-safe (`jira_key`).

## Current gaps to call out honestly

Stage 23 is about making the overlap chain more complete. Today these systems are adjacent but not yet fully keyed into the same story:

- `mcp/connectors/archer.py` already uses `epic_key`, but its sample `finding_id` values (`arch-f-*`) are not yet the same as Mongo `audit_findings._id` values.
- `mcp/connectors/servicenow.py` does not yet expose a shared `epic_key` or `ticket_refs` field.
- `mcp/connectors/snowflake.py` does not yet expose `finding_id` or `ticket_refs` in sample rows.
- `mcp/connectors/aws.py` shows the affected infrastructure (`rds-postgres-prod-02`, `audit-logs-archive-prod`) but does not yet carry the same business join keys.
- Stage 23 also plans a canonical Mongo `confluence_pages` collection so Confluence pages are queryable alongside the connector sample.

## Stage 23 target chain

The teaching target is:

`archer finding -> Mongo/Jira epic -> work item -> GitHub commit/PR -> ServiceNow change -> Snowflake evidence -> Confluence page`

Recommended join keys by hop:

- **Risk to epic:** `finding_id` and/or `epic_key`
- **Epic to implementation:** `epic_id` or `epic_key`
- **Implementation to docs/evidence:** `ticket_refs[]`, `jira_key`, `finding_id`

## Good demo questions

- "Show me everything related to `RDS-LOG-1`."
- "Which Confluence pages cite `RDS-LOG-2`?"
- "Which PRs and work items are still open for `finding-smoke-001`?"
- "Where does the evidence trail stop today, and which Stage 23 enrichment closes that gap?"

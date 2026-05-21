# Wave 2 — Connectors: All 8 System Implementations

**Goal:** Every connection bubble exists and speaks its protocol, returning mock data when disabled.

---

## Wave 2.1 — S9.connect.4: MCP-client connectors (Jira, Confluence, GitHub, AWS)

**Files:** `mcp/connectors/jira.py`, `mcp/connectors/confluence.py`, `mcp/connectors/github.py`, `mcp/connectors/aws.py`, `mcp/requirements.txt` (add httpx if missing)

Each connector:
1. Reads `CONN_*_ENABLED` + `*_MCP_URL` + `*_MCP_TOKEN` from env.
2. When **enabled**: acts as an MCP client to its upstream MCP server. Uses `httpx.AsyncClient` with the provided token.
3. When **disabled**: `health()` returns `{"status": "disabled"}`; `summary()` returns mock data; tools return a clean "disabled" message.
4. Exposes system-specific tools:
   - Jira: `jira_search_issues`, `jira_create_issue`, `jira_get_epic`
   - Confluence: `confluence_search_pages`, `confluence_create_page`
   - GitHub: `github_search_repos`, `github_create_branch`, `github_open_pr`, `github_list_checks`
   - AWS: `aws_list_rds_instances`, `aws_describe_instance`

**Pattern:** Each tool function is an async coroutine that validates args, dispatches to the upstream MCP server (or returns mock when disabled), and returns the standard `{content, isError}` envelope.

---

## Wave 2.2 — S9.connect.5 + S9.connect.6: ServiceNow REST + Snowflake SQL adapters

**Files:** `mcp/connectors/servicenow.py`, `mcp/connectors/snowflake.py`

1. **ServiceNow**
   - `health()`: GET `/api/now/table/sys_user?sysparm_limit=1` with `SERVICENOW_TOKEN`.
   - `summary()`: count open incidents + change requests.
   - Tools: `servicenow_search_findings`, `servicenow_get_change_request`.
   - Mock when disabled: returns a sample finding + CR.

2. **Snowflake**
   - `health()`: `SELECT CURRENT_VERSION()` via `snowflake-connector-python` (add to `mcp/requirements.txt`).
   - `summary()`: row count in the audit log warehouse table.
   - Tool: `snowflake_query` — read-only SQL, validated/limited like `mongo_query`.
   - Mock when disabled: returns sample login/sql-error/sql-query rows.

---

## Wave 2.3 — S9.connect.7: Archer placeholder connector

**Files:** `mcp/connectors/archer.py`

1. Typed contract with `health()`, `summary()`, `tools()`.
2. Always returns mock data ("placeholder" status).
3. Tool: `archer_search_findings` — returns a static list of 2 sample findings.
4. UI bubble renders "not connected / placeholder" gracefully.

---

## Commit checkpoint

```bash
git add .
git commit -m "S9 Wave 2: all 8 connector implementations (mock + live)"
docker compose build mcp  # verify
```

"""Jira connector client using standard Protocol pattern."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .base import Connector

# Candidate tool names on the upstream Atlassian MCP server that perform an
# issue edit. The hosted server's exposed set varies by token scope; apply
# uses the first one that's actually advertised by tools/list.
_EDIT_TOOL_CANDIDATES = ("editJiraIssue", "updateJiraIssue", "jira_update_issue", "edit_issue")


class JiraConnector:
    """Connector for Jira MCP server.

    When CONN_JIRA_ENABLED=true and JIRA_MCP_URL/JIRA_MCP_TOKEN point at the
    hosted Atlassian MCP server (https://mcp.atlassian.com/v1/mcp/authv2),
    the live apply path drives that server over JSON-RPC (SSE-framed) with a
    Bearer token. Otherwise everything stays on the in-memory sample.
    """

    name = "jira"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.mcp_url = os.environ.get("JIRA_MCP_URL", "")
        self.mcp_token = os.environ.get("JIRA_MCP_TOKEN", "")
        self.base_url = os.environ.get("JIRA_BASE_URL", "https://enterprise.atlassian.net")
        self._session_id: str | None = None
        self._rpc_id = 0

    async def health(self) -> dict:
        if not self.enabled:
            return {"status": "disabled"}
        if not self.mcp_url or not self.mcp_token:
            return {"status": "degraded", "error": "Missing JIRA_MCP_URL or JIRA_MCP_TOKEN"}
        return {"status": "healthy", "url": self.mcp_url}

    # ---- live Atlassian MCP client ----------------------------------------

    @staticmethod
    def _parse_sse(text: str) -> dict[str, Any]:
        """The hosted server replies as text/event-stream; pull the JSON-RPC
        object out of the last `data:` line."""
        out: dict[str, Any] = {}
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                try:
                    out = json.loads(line[len("data:"):].strip())
                except json.JSONDecodeError:
                    continue
        return out

    async def _mcp_rpc(self, client: httpx.AsyncClient, method: str, params: dict | None = None) -> dict[str, Any]:
        self._rpc_id += 1
        headers = {
            "Authorization": f"Bearer {self.mcp_token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        body = {"jsonrpc": "2.0", "id": self._rpc_id, "method": method, "params": params or {}}
        r = await client.post(self.mcp_url, json=body, headers=headers)
        sid = r.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid
        r.raise_for_status()
        return self._parse_sse(r.text)

    async def _live_tool_names(self, client: httpx.AsyncClient) -> list[str]:
        await self._mcp_rpc(
            client,
            "initialize",
            {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "langarland", "version": "0.1"}},
        )
        res = await self._mcp_rpc(client, "tools/list")
        return [t.get("name") for t in (res.get("result", {}) or {}).get("tools", [])]

    async def health(self) -> dict:
        if not self.enabled:
            return {"status": "disabled"}
        if not self.mcp_url or not self.mcp_token:
            return {"status": "degraded", "error": "Missing JIRA_MCP_URL or JIRA_MCP_TOKEN"}
        return {"status": "healthy", "url": self.mcp_url}

    # Active sprint board, tickets grouped by epic, modeled on the real Jira
    # issue + Agile-API shapes. `fields.*` mirror the REST API; top-level
    # convenience keys (epic_key, age_days, flagged) drive the topology
    # weak-spot rules. `flagged`/high `age_days` marks a neglected ticket.
    _ACTIVE_SPRINT = {
        "id": 1042, "name": "Compliance Sprint 24", "state": "active", "boardId": 7,
        "startDate": "2026-05-16", "endDate": "2026-05-30",
        "goal": "Close RDS audit-logging stories + branch security gates",
        "committed": 34, "completed": 13,
    }

    @staticmethod
    def _issue(key, summary, issuetype, status, cat, priority, assignee, reporter,
               labels, components, points, epic_key, epic_name, created, updated,
               duedate, age_days, flagged):
        return {
            "key": key,
            "fields": {
                "summary": summary,
                "issuetype": {"name": issuetype},
                "status": {"name": status, "statusCategory": {"name": cat}},
                "priority": {"name": priority},
                "assignee": {"displayName": assignee},
                "reporter": {"displayName": reporter},
                "labels": labels,
                "components": [{"name": c} for c in components],
                "customfield_story_points": points,
                "parent": {"key": epic_key, "fields": {"summary": epic_name}},
                "created": created,
                "updated": updated,
                "duedate": duedate,
            },
            # convenience top-level keys (denormalized for rules + simple rendering)
            "summary": summary, "status": status, "assignee": assignee,
            "epic_key": epic_key, "epic_name": epic_name, "story_points": points,
            "updated": updated, "duedate": duedate, "age_days": age_days, "flagged": flagged,
        }

    _SAMPLE = [
        _issue.__func__("RDS-LOG-2", "Enable RDS MySQL audit trail logs + ship to S3", "Story", "In Progress", "In Progress",
                        "High", "Sultan DevOps", "Alex SecOps", ["compliance", "sox-404"], ["database"], 5,
                        "RDS-LOG-1", "RDS Audit Logging", "2026-05-12", "2026-05-21", "2026-05-28", 0, False),
        _issue.__func__("RDS-LOG-3", "Enable RDS PostgreSQL pgaudit extension", "Story", "To Do", "To Do",
                        "High", "Sultan DevOps", "Alex SecOps", ["compliance"], ["database"], 5,
                        "RDS-LOG-1", "RDS Audit Logging", "2026-05-12", "2026-05-19", "2026-05-29", 2, False),
        _issue.__func__("RDS-LOG-4", "Backfill RDS MariaDB log retention to 400 days", "Story", "Blocked", "In Progress",
                        "Medium", "Sarah SRE", "Sultan DevOps", ["compliance", "pci-dss"], ["database"], 3,
                        "RDS-LOG-1", "RDS Audit Logging", "2026-04-30", "2026-05-06", "2026-05-22", 15, True),
        _issue.__func__("SEC-SCAN-101", "Integrate GitHub repo scanner alerts for branch compliance", "Story", "To Do", "To Do",
                        "High", "Alex SecOps", "Alex SecOps", ["security"], ["ci"], 8,
                        "SEC-SCAN", "CI Branch Security Gates", "2026-05-10", "2026-05-20", "2026-05-30", 1, False),
        _issue.__func__("SEC-SCAN-104", "Add secret-scanning push protection to all infra repos", "Story", "In Progress", "In Progress",
                        "Medium", "Alex SecOps", "Alex SecOps", ["security"], ["ci"], 5,
                        "SEC-SCAN", "CI Branch Security Gates", "2026-05-11", "2026-05-18", "2026-05-31", 3, False),
        _issue.__func__("ALB-ROT-202", "Automate certificate rotation in AWS load balancer pipeline", "Task", "Deferred", "To Do",
                        "Low", "Sarah SRE", "Sarah SRE", ["tls"], ["sre"], 3,
                        "ALB-ROT", "Cert Rotation Automation", "2026-04-20", "2026-04-28", "2026-06-15", 23, True),
    ]

    def _summary_payload(self, status: str) -> dict:
        return {
            "status": status,
            "schema": "jira_sprint",
            "open_issues_count": sum(1 for r in self._SAMPLE if r["status"] != "Done"),
            "flagged_count": sum(1 for r in self._SAMPLE if r["flagged"]),
            "base_url": self.base_url,
            "active_sprint": self._ACTIVE_SPRINT,
            "sample_data": self._SAMPLE,
        }

    async def summary(self) -> dict:
        return self._summary_payload("disabled" if not self.enabled else "healthy")

    def tools(self) -> list[dict]:
        return [
            {
                "name": "jira_search_issues",
                "description": "Search Jira issues using JQL.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "jql": {"type": "string", "description": "Jira Query Language string."}
                    },
                    "required": ["jql"],
                },
            },
            {
                "name": "jira_create_issue",
                "description": "Create a new issue/stub in Jira.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string"},
                        "summary": {"type": "string"},
                        "description": {"type": "string"},
                        "issuetype": {"type": "string", "default": "Story"},
                        "epic_link": {"type": "string"},
                    },
                    "required": ["project", "summary", "description"],
                },
            },
            {
                "name": "jira_get_epic",
                "description": "Retrieve details for a Jira epic.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "epic_key": {"type": "string"}
                    },
                    "required": ["epic_key"],
                },
            },
            # Stage 16 — HIL-gated bulk editing. These work regardless of the
            # CONN_JIRA_ENABLED live flag; nothing reaches Jira until apply runs
            # with JIRA_WRITES_ENABLED=true.
            {
                "name": "jira_list_issues",
                "description": "List current sprint issues overlaid with any staged (pending) edits and their stage status.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "jira_stage_edits",
                "description": "Stage bulk field edits to issues as human-in-the-loop drafts (NOT written to Jira). Resets each edited issue to 'staged'.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "edits": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "issue_key": {"type": "string"},
                                    "changes": {"type": "object", "description": "field -> new value"},
                                },
                                "required": ["issue_key", "changes"],
                            },
                        }
                    },
                    "required": ["edits"],
                },
            },
            {
                "name": "jira_validate_staged",
                "description": "Validate staged edits against field/enum rules, marking each validated or invalid with per-field errors.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"issue_keys": {"type": "array", "items": {"type": "string"}}},
                },
            },
            {
                "name": "jira_revert_staged",
                "description": "Discard staged edits (all, or a given set of issue keys) so the grid returns to live Jira state.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"issue_keys": {"type": "array", "items": {"type": "string"}}},
                },
            },
            {
                "name": "jira_apply_staged",
                "description": "Apply VALIDATED staged edits. Dry-run plan unless JIRA_WRITES_ENABLED=true; refuses unvalidated rows.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"issue_keys": {"type": "array", "items": {"type": "string"}}},
                },
            },
        ]

    async def _live_update_issue(self, issue_key: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Live Jira write path — only invoked by apply when JIRA_WRITES_ENABLED.

        Drives the hosted Atlassian MCP server: discover an edit tool from
        tools/list, then tools/call it with the issue key + field updates.
        Raises if no edit tool is exposed for this token's scope (apply then
        records the issue as skipped rather than silently dropping it).
        """
        if not self.enabled or not (self.mcp_url and self.mcp_token):
            raise RuntimeError("Jira connector not configured for live writes")
        async with httpx.AsyncClient(timeout=30) as client:
            names = await self._live_tool_names(client)
            edit_tool = next((c for c in _EDIT_TOOL_CANDIDATES if c in names), None)
            if not edit_tool:
                raise RuntimeError(
                    f"Atlassian MCP exposes no issue-edit tool for this token (saw: {names}). "
                    "Cannot apply live; keep JIRA_WRITES_ENABLED=false or grant Jira write scope."
                )
            res = await self._mcp_rpc(
                client,
                "tools/call",
                {"name": edit_tool, "arguments": {"issueIdOrKey": issue_key, "fields": fields}},
            )
            return {"key": issue_key, "tool": edit_tool, "result": res.get("result")}

    @staticmethod
    def _envelope(payload: Any, is_error: bool = False) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}], "isError": is_error}

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        # Stage 16 — staging tools are available regardless of the live flag.
        if name in (
            "jira_list_issues",
            "jira_stage_edits",
            "jira_validate_staged",
            "jira_revert_staged",
            "jira_apply_staged",
        ):
            import jira_staging as stg

            try:
                if name == "jira_list_issues":
                    return self._envelope(await stg.list_issues(list(self._SAMPLE)))
                if name == "jira_stage_edits":
                    return self._envelope(
                        await stg.stage_edits(args.get("edits") or [], list(self._SAMPLE))
                    )
                if name == "jira_validate_staged":
                    return self._envelope(await stg.validate_staged(args.get("issue_keys")))
                if name == "jira_revert_staged":
                    return self._envelope(await stg.revert_staged(args.get("issue_keys")))
                if name == "jira_apply_staged":
                    return self._envelope(
                        await stg.apply_staged(args.get("issue_keys"), live_writer=self._live_update_issue)
                    )
            except Exception as e:  # noqa: BLE001
                return self._envelope({"error": f"{type(e).__name__}: {e}"}, is_error=True)

        if not self.enabled:
            return {
                "content": [{"type": "text", "text": f"Jira connector is disabled. Tool '{name}' returned generic stub payload."}],
                "isError": False,
            }

        if name == "jira_search_issues":
            return {
                "content": [{"type": "text", "text": "[]"}],
                "isError": False,
            }
        if name == "jira_create_issue":
            return {
                "content": [{"type": "text", "text": '{"key": "MOCK-123", "status": "success"}'}],
                "isError": False,
            }
        if name == "jira_get_epic":
            return {
                "content": [{"type": "text", "text": '{"key": "' + args.get("epic_key", "MOCK") + '", "status": "in_progress"}'}],
                "isError": False,
            }
        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}

"""Jira connector client using standard Protocol pattern."""

from __future__ import annotations

import os
from typing import Any

from .base import Connector


class JiraConnector:
    """Connector for Jira MCP server."""

    name = "jira"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.mcp_url = os.environ.get("JIRA_MCP_URL", "")
        self.mcp_token = os.environ.get("JIRA_MCP_TOKEN", "")
        self.base_url = os.environ.get("JIRA_BASE_URL", "https://enterprise.atlassian.net")

    async def health(self) -> dict:
        if not self.enabled:
            return {"status": "disabled"}
        if not self.mcp_url or not self.mcp_token:
            return {"status": "degraded", "error": "Missing JIRA_MCP_URL or JIRA_MCP_TOKEN"}
        return {"status": "healthy", "url": self.mcp_url}

    # Active sprint board, tickets grouped by epic. `flagged`/high `age_days`
    # marks a neglected ticket the topology surfaces as a weak-spot.
    _ACTIVE_SPRINT = {"name": "Compliance Sprint 24", "ends": "2026-05-30", "committed": 34, "completed": 13}

    _SAMPLE = [
        {"key": "RDS-LOG-2", "summary": "Enable RDS MySQL audit trail logs + ship to S3", "status": "In Progress",
         "assignee": "Sultan DevOps", "epic_key": "RDS-LOG-1", "epic_name": "RDS Audit Logging",
         "story_points": 5, "updated": "2026-05-21", "age_days": 0, "flagged": False},
        {"key": "RDS-LOG-3", "summary": "Enable RDS PostgreSQL pgaudit extension", "status": "To Do",
         "assignee": "Sultan DevOps", "epic_key": "RDS-LOG-1", "epic_name": "RDS Audit Logging",
         "story_points": 5, "updated": "2026-05-19", "age_days": 2, "flagged": False},
        {"key": "RDS-LOG-4", "summary": "Backfill RDS MariaDB log retention to 400 days", "status": "Blocked",
         "assignee": "Sarah SRE", "epic_key": "RDS-LOG-1", "epic_name": "RDS Audit Logging",
         "story_points": 3, "updated": "2026-05-06", "age_days": 15, "flagged": True},
        {"key": "SEC-SCAN-101", "summary": "Integrate GitHub repo scanner alerts for branch compliance", "status": "To Do",
         "assignee": "Alex SecOps", "epic_key": "SEC-SCAN", "epic_name": "CI Branch Security Gates",
         "story_points": 8, "updated": "2026-05-20", "age_days": 1, "flagged": False},
        {"key": "SEC-SCAN-104", "summary": "Add secret-scanning push protection to all infra repos", "status": "In Progress",
         "assignee": "Alex SecOps", "epic_key": "SEC-SCAN", "epic_name": "CI Branch Security Gates",
         "story_points": 5, "updated": "2026-05-18", "age_days": 3, "flagged": False},
        {"key": "ALB-ROT-202", "summary": "Automate certificate rotation in AWS load balancer pipeline", "status": "Deferred",
         "assignee": "Sarah SRE", "epic_key": "ALB-ROT", "epic_name": "Cert Rotation Automation",
         "story_points": 3, "updated": "2026-04-28", "age_days": 23, "flagged": True},
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
        ]

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
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

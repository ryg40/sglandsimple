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

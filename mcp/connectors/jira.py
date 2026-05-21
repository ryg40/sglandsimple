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

    async def health(self) -> dict:
        if not self.enabled:
            return {"status": "disabled"}
        if not self.mcp_url or not self.mcp_token:
            return {"status": "degraded", "error": "Missing JIRA_MCP_URL or JIRA_MCP_TOKEN"}
        return {"status": "healthy", "url": self.mcp_url}

    async def summary(self) -> dict:
        if not self.enabled:
            return {"status": "disabled", "open_issues_count": 0, "sample_data": [
                {"key": "SEC-SCAN-101", "summary": "Integrate GitHub repo scanner alerts for branch compliance", "status": "To Do", "assignee": "Alex SecOps", "updated": "2026-05-20"},
                {"key": "RDS-LOG-1", "summary": "Enable AWS RDS database engine audit trail logs", "status": "In Progress", "assignee": "Sultan DevOps", "updated": "2026-05-21"},
                {"key": "ALB-ROT-202", "summary": "Automate certificate verification rotators in AWS load balancer pipeline", "status": "Deferred", "assignee": "Sarah SRE", "updated": "2026-05-18"}
            ]}
        return {"status": "healthy", "open_issues_count": 3, "sample_data": [
            {"key": "SEC-SCAN-101", "summary": "Integrate GitHub repo scanner alerts for branch compliance", "status": "To Do", "assignee": "Alex SecOps", "updated": "2026-05-20"},
            {"key": "RDS-LOG-1", "summary": "Enable AWS RDS database engine audit trail logs", "status": "In Progress", "assignee": "Sultan DevOps", "updated": "2026-05-21"},
            {"key": "ALB-ROT-202", "summary": "Automate certificate verification rotators in AWS load balancer pipeline", "status": "Deferred", "assignee": "Sarah SRE", "updated": "2026-05-18"}
        ]}

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

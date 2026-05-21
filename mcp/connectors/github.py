"""GitHub connector client using Protocol pattern."""

from __future__ import annotations

import os
from typing import Any

from .base import Connector


class GitHubConnector:
    """Connector for GitHub MCP server."""

    name = "github"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.mcp_url = os.environ.get("GITHUB_MCP_URL", "")
        self.mcp_token = os.environ.get("GITHUB_MCP_TOKEN", "")

    async def health(self) -> dict:
        if not self.enabled:
            return {"status": "disabled"}
        if not self.mcp_url or not self.mcp_token:
            return {"status": "degraded", "error": "Missing GITHUB_MCP_URL or GITHUB_MCP_TOKEN"}
        return {"status": "healthy", "url": self.mcp_url}

    # Recent commits across active projects, auto-tagged to epics. A failing
    # checks_state is a weak-spot the topology highlights.
    _SAMPLE = [
        {"sha": "a1f9c02", "message": "feat(rds): emit MySQL audit events to S3 sink", "repo": "infra-terraform",
         "project": "RDS Audit Logging", "author": "sultan-devops", "committed": "2026-05-21",
         "epic_key": "RDS-LOG-1", "tags": ["epic:RDS-LOG", "compliance", "sox-404"], "pr_number": 398, "checks_state": "passing"},
        {"sha": "7d3e1b8", "message": "fix(rds): pgaudit role grants for postgres prod", "repo": "infra-terraform",
         "project": "RDS Audit Logging", "author": "sultan-devops", "committed": "2026-05-21",
         "epic_key": "RDS-LOG-1", "tags": ["epic:RDS-LOG", "compliance"], "pr_number": 401, "checks_state": "failing"},
        {"sha": "c52a9f4", "message": "feat(scan): wire repo scanner alerts into branch gate", "repo": "sec-gates",
         "project": "CI Branch Security Gates", "author": "alex-secops", "committed": "2026-05-20",
         "epic_key": "SEC-SCAN", "tags": ["epic:SEC-SCAN", "security"], "pr_number": 412, "checks_state": "passing"},
        {"sha": "e08b7aa", "message": "chore(scan): enable push protection org-wide", "repo": "sec-gates",
         "project": "CI Branch Security Gates", "author": "alex-secops", "committed": "2026-05-19",
         "epic_key": "SEC-SCAN", "tags": ["epic:SEC-SCAN", "security"], "pr_number": 414, "checks_state": "pending"},
        {"sha": "9b1d460", "message": "feat(alb): cert-manager helm chart for edge LB", "repo": "infra-k8s",
         "project": "Cert Rotation Automation", "author": "sarah-sre", "committed": "2026-05-18",
         "epic_key": "ALB-ROT", "tags": ["epic:ALB-ROT", "tls"], "pr_number": 420, "checks_state": "passing"},
    ]

    def _summary_payload(self, status: str) -> dict:
        return {
            "status": status,
            "schema": "github_commits",
            "commits_count": len(self._SAMPLE),
            "prs_count": len({r["pr_number"] for r in self._SAMPLE if r.get("pr_number")}),
            "failing_checks": sum(1 for r in self._SAMPLE if r["checks_state"] == "failing"),
            "sample_data": self._SAMPLE,
        }

    async def summary(self) -> dict:
        return self._summary_payload("disabled" if not self.enabled else "healthy")

    def tools(self) -> list[dict]:
        return [
            {
                "name": "github_search_repos",
                "description": "Search GitHub repositories.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"}
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "github_create_branch",
                "description": "Create a new branch in a GitHub repository.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string"},
                        "branch": {"type": "string"},
                        "source": {"type": "string", "default": "main"},
                    },
                    "required": ["repo", "branch"],
                },
            },
            {
                "name": "github_open_pr",
                "description": "Open a pull request.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string"},
                        "title": {"type": "string"},
                        "head": {"type": "string"},
                        "base": {"type": "string", "default": "main"},
                        "body": {"type": "string"},
                    },
                    "required": ["repo", "title", "head"],
                },
            },
            {
                "name": "github_list_checks",
                "description": "List checks/status runs on a PR/commit.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string"},
                        "ref": {"type": "string"},
                    },
                    "required": ["repo", "ref"],
                },
            },
        ]

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {
                "content": [{"type": "text", "text": f"GitHub connector is disabled. Tool '{name}' returned generic stub payload."}],
                "isError": False,
            }

        if name == "github_search_repos":
            return {"content": [{"type": "text", "text": "[]"}], "isError": False}
        if name == "github_create_branch":
            return {"content": [{"type": "text", "text": '{"branch": "' + args.get("branch", "dev") + '", "status": "created"}'}], "isError": False}
        if name == "github_open_pr":
            return {"content": [{"type": "text", "text": '{"url": "https://github.com/org/repo/pull/123", "number": 123, "status": "open"}'}], "isError": False}
        if name == "github_list_checks":
            return {"content": [{"type": "text", "text": '[{"name": "compliance-scan", "status": "completed", "conclusion": "success"}]'}], "isError": False}

        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}

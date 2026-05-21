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

    async def summary(self) -> dict:
        if not self.enabled:
            return {"status": "disabled", "prs_count": 0}
        return {"status": "healthy", "prs_count": 2}

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

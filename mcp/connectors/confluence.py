"""Confluence connector client."""

from __future__ import annotations

import os
from typing import Any

from .base import Connector


class ConfluenceConnector:
    """Connector for Confluence MCP server."""

    name = "confluence"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.mcp_url = os.environ.get("CONFLUENCE_MCP_URL", "")
        self.mcp_token = os.environ.get("CONFLUENCE_MCP_TOKEN", "")

    async def health(self) -> dict:
        if not self.enabled:
            return {"status": "disabled"}
        if not self.mcp_url or not self.mcp_token:
            return {"status": "degraded", "error": "Missing CONFLUENCE_MCP_URL or CONFLUENCE_MCP_TOKEN"}
        return {"status": "healthy", "url": self.mcp_url}

    async def summary(self) -> dict:
        if not self.enabled:
            return {"status": "disabled", "pages_count": 0, "sample_data": [
                {"id": "pg-01", "title": "Runbook: SOX-404 Database Audit Logging Procedure", "space": "Compliance-Runbooks", "editor": "Sultan DevOps", "last_updated": "2026-05-18"},
                {"id": "pg-02", "title": "CI/CD Secure Branch Scanning Policy & Compliance Standards", "space": "Architecture-RFCs", "editor": "Alex SecOps", "last_updated": "2026-05-20"},
                {"id": "pg-03", "title": "AWS certificate verification & Rotations (ALB Pipeline)", "space": "SRE-Guides", "editor": "Sarah SRE", "last_updated": "2026-05-21"}
            ]}
        return {"status": "healthy", "pages_count": 12, "sample_data": [
            {"id": "pg-01", "title": "Runbook: SOX-404 Database Audit Logging Procedure", "space": "Compliance-Runbooks", "editor": "Sultan DevOps", "last_updated": "2026-05-18"},
            {"id": "pg-02", "title": "CI/CD Secure Branch Scanning Policy & Compliance Standards", "space": "Architecture-RFCs", "editor": "Alex SecOps", "last_updated": "2026-05-20"},
            {"id": "pg-03", "title": "AWS certificate verification & Rotations (ALB Pipeline)", "space": "SRE-Guides", "editor": "Sarah SRE", "last_updated": "2026-05-21"}
        ]}

    def tools(self) -> list[dict]:
        return [
            {
                "name": "confluence_search_pages",
                "description": "Search Confluence pages.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"}
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "confluence_create_page",
                "description": "Create a Confluence page.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "space": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["title", "body"],
                },
            },
        ]

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {
                "content": [{"type": "text", "text": f"Confluence connector is disabled. Tool '{name}' returned generic stub payload."}],
                "isError": False,
            }

        if name == "confluence_search_pages":
            return {"content": [{"type": "text", "text": "[]"}], "isError": False}
        if name == "confluence_create_page":
            return {"content": [{"type": "text", "text": f'{{"url": "https://confluence.example.com/pages/{args.get("title", "page")}", "status": "success"}}'}], "isError": False}

        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
